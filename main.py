from fastapi import FastAPI, Depends, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import Site, Deal, PriceSnapshot, get_db, engine, Base, SessionLocal
from scheduler import start_scheduler, scrape_in_background, scrape_single_site
import os
import threading


# NUCLEAR RESET: Drop ALL tables and recreate
def nuclear_reset():
    try:
        with engine.begin() as conn:
            if "sqlite" in str(engine.url):
                conn.execute(text("DROP TABLE IF EXISTS deals"))
                conn.execute(text("DROP TABLE IF EXISTS price_snapshots"))
                conn.execute(text("DROP TABLE IF EXISTS sites"))
                print("✅ Dropped ALL tables (SQLite)")
            else:
                conn.execute(text("DROP TABLE IF EXISTS price_snapshots"))
                conn.execute(text("DROP TABLE IF EXISTS deals"))
                conn.execute(text("DROP TABLE IF EXISTS sites"))
                print("✅ Dropped ALL tables (PostgreSQL)")
    except Exception as e:
        print(f"⚠️ Nuclear reset error: {e}")


nuclear_reset()

Base.metadata.create_all(bind=engine)
print("✅ Recreated ALL tables with correct schema")

app = FastAPI(title="Mali Mali Treasure Hunter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    start_scheduler()


def extract_price_value(price_str: str) -> float:
    try:
        clean = price_str.replace('KSh', '').replace('KES', '').replace(',', '').strip()
        return float(clean)
    except:
        return 0.0


def inject_affiliate(link: str, affiliate_id: str) -> str:
    if not affiliate_id:
        return link
    separator = "&" if "?" in link else "?"
    return f"{link}{separator}utm_source=mali_mali&utm_medium=extension&aff_id={affiliate_id}"


@app.get("/deals")
def get_deals(db: Session = Depends(get_db)):
    deals = db.query(Deal).filter(Deal.is_active == 1).order_by(Deal.discovered_at.desc()).all()

    deals_list = []
    for deal in deals:
        site = db.query(Site).filter(Site.name == deal.store).first()
        aff_id = site.affiliate_id if site else None
        tracked_link = inject_affiliate(deal.link, aff_id)

        snapshots = db.query(PriceSnapshot).filter(
            PriceSnapshot.store == deal.store,
            PriceSnapshot.product == deal.product
        ).order_by(PriceSnapshot.recorded_at.asc()).all()

        prices = [extract_price_value(s.price) for s in snapshots if extract_price_value(s.price) > 0]
        lowest_price = min(prices) if prices else 0
        highest_price = max(prices) if prices else 0
        current_price = extract_price_value(deal.price)

        price_trend = "stable"
        if len(prices) > 1:
            if current_price == lowest_price:
                price_trend = "lowest"
            elif current_price < prices[-2]:
                price_trend = "dropped"
            elif current_price > prices[-2]:
                price_trend = "increased"

        deals_list.append({
            "store": deal.store,
            "product": deal.product,
            "price": deal.price,
            "link": tracked_link,
            "image_url": deal.image_url,
            "discovered_at": deal.discovered_at,
            "price_history": {
                "lowest": f"KSh {lowest_price:,.0f}" if lowest_price > 0 else "N/A",
                "highest": f"KSh {highest_price:,.0f}" if highest_price > 0 else "N/A",
                "trend": price_trend,
                "snapshots_count": len(snapshots)
            }
        })

    return {"status": "success", "count": len(deals_list), "deals": deals_list}


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(db: Session = Depends(get_db)):
    sites = db.query(Site).all()
    deals = db.query(Deal).filter(Deal.is_active == 1).order_by(Deal.discovered_at.desc()).limit(20).all()

    sites_html = ""
    for site in sites:
        sites_html += f"""
        <tr id="site-row-{site.id}">
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; font-weight: 600;">{site.name}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                <span style="background: {'#d1fae5; color: #059669' if site.affiliate_id else '#f3f4f6; color: #9ca3af'}; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600;">
                    {site.affiliate_id or 'Not Set'}
                </span>
            </td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #6b7280; font-size: 13px;">{site.url}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <button onclick="refreshSite({site.id}, '{site.name}')" class="action-btn refresh-site-btn" title="Refresh this store only">🔄</button>
                    <button onclick="openEditModal({site.id}, '{site.name.replace("'", "\\'")}', '{site.url}', '{site.affiliate_id or ''}', '{site.product_selector}', '{site.title_selector}', '{site.price_selector}', '{site.link_selector}')" class="action-btn edit-btn" title="Edit store details">✏️</button>
                    <form method="POST" action="/admin/delete/{site.id}" style="display:inline;" onsubmit="return confirm('Delete {site.name}? This will also delete all deals from this store.');">
                        <button type="submit" class="action-btn delete-btn" title="Delete store">🗑️</button>
                    </form>
                </div>
            </td>
        </tr>
        """

    deals_html = ""
    for deal in deals:
        image_html = ""
        if deal.image_url:
            image_html = f'<img src="{deal.image_url}" style="width: 40px; height: 40px; object-fit: contain; border-radius: 6px; margin-right: 10px; background: #f9fafb; vertical-align: middle;">'

        deals_html += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{deal.store}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{image_html}{deal.product[:50]}{'...' if len(deal.product) > 50 else ''}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #dc2626; font-weight: 700;">{deal.price}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;"><a href="{deal.link}" target="_blank" style="color: #059669; font-weight: 600; text-decoration: none;">View →</a></td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #9ca3af; font-size: 12px;">{deal.discovered_at[:16] if deal.discovered_at else 'N/A'}</td>
        </tr>
        """

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mali Mali Treasure Hunter Admin</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 40px 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { background: rgba(255,255,255,0.95); padding: 30px; border-radius: 16px; margin-bottom: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
            .header-content { display: flex; align-items: center; gap: 16px; }
            .logo { width: 50px; height: 50px; background: linear-gradient(135deg, #dc2626 0%, #f59e0b 100%); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 28px; }
            h1 { color: #111827; font-size: 28px; font-weight: 800; }
            .subtitle { color: #6b7280; font-size: 14px; margin-top: 4px; }
            .card { background: rgba(255,255,255,0.95); padding: 30px; border-radius: 16px; margin-bottom: 30px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
            h2 { color: #111827; font-size: 20px; font-weight: 700; margin-bottom: 20px; }
            .form-container { background: #f9fafb; padding: 24px; border-radius: 12px; border: 2px solid #e5e7eb; }
            input { width: 100%; padding: 12px 16px; margin: 8px 0 16px 0; border: 2px solid #e5e7eb; border-radius: 8px; font-size: 14px; font-family: inherit; transition: border-color 0.2s; }
            input:focus { outline: none; border-color: #667eea; }
            label { font-size: 13px; font-weight: 600; color: #374151; }
            button { background: linear-gradient(135deg, #dc2626 0%, #f59e0b 100%); color: white; padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px; transition: transform 0.2s, box-shadow 0.2s; }
            button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3); }
            .refresh-all-btn { background: linear-gradient(135deg, #059669 0%, #10b981 100%); margin-bottom: 20px; padding: 14px 28px; font-size: 15px; }
            .refresh-all-btn:hover { box-shadow: 0 4px 12px rgba(5, 150, 105, 0.3); }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th { background: #f3f4f6; padding: 14px; text-align: left; font-weight: 600; color: #374151; font-size: 13px; text-transform: uppercase; }
            .action-btn { padding: 8px 12px; font-size: 14px; border-radius: 8px; cursor: pointer; border: none; transition: transform 0.2s, box-shadow 0.2s; min-width: 40px; }
            .action-btn:hover { transform: translateY(-2px); }
            .refresh-site-btn { background: linear-gradient(135deg, #059669 0%, #10b981 100%); color: white; }
            .refresh-site-btn:hover { box-shadow: 0 4px 12px rgba(5, 150, 105, 0.3); }
            .refresh-site-btn.spinning { animation: spin 1s linear infinite; }
            @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
            .edit-btn { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
            .edit-btn:hover { box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3); }
            .delete-btn { background: #ef4444; color: white; }
            .delete-btn:hover { box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3); }
            .stats { display: flex; gap: 20px; margin-bottom: 20px; }
            .stat-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px; flex: 1; text-align: center; }
            .stat-number { font-size: 32px; font-weight: 800; margin-bottom: 4px; }
            .stat-label { font-size: 13px; opacity: 0.9; }

            /* Modal Styles */
            .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: center; backdrop-filter: blur(4px); }
            .modal-overlay.active { display: flex; }
            .modal { background: white; border-radius: 16px; padding: 30px; width: 90%; max-width: 600px; max-height: 90vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
            .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
            .modal-header h2 { margin: 0; font-size: 22px; }
            .modal-close { background: #f3f4f6; color: #6b7280; border: none; width: 36px; height: 36px; border-radius: 50%; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0; }
            .modal-close:hover { background: #e5e7eb; color: #111827; transform: none; box-shadow: none; }
            .save-btn { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); width: 100%; padding: 14px; font-size: 16px; margin-top: 8px; }
            .save-btn:hover { box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3); }

            /* Toast Notification */
            .toast { position: fixed; bottom: 30px; right: 30px; background: #111827; color: white; padding: 16px 24px; border-radius: 12px; font-size: 14px; font-weight: 600; z-index: 2000; transform: translateY(100px); opacity: 0; transition: all 0.3s ease; box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
            .toast.show { transform: translateY(0); opacity: 1; }
            .toast.success { background: linear-gradient(135deg, #059669 0%, #10b981 100%); }
            .toast.error { background: linear-gradient(135deg, #dc2626 0%, #ef4444 100%); }
            .toast.info { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="header-content">
                    <div class="logo">💎</div>
                    <div>
                        <h1>🇰🇪 Mali Mali Treasure Hunter</h1>
                        <div class="subtitle">Smart Deal Management Dashboard</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <form method="POST" action="/admin/refresh">
                    <button type="submit" class="refresh-all-btn">🔄 Refresh All Sites Now</button>
                </form>

                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-number">""" + str(len(sites)) + """</div>
                        <div class="stat-label">Active Stores</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">""" + str(len(deals)) + """</div>
                        <div class="stat-label">Active Deals</div>
                    </div>
                </div>
            </div>

            <div class="card">
                <h2>➕ Add New Store</h2>
                <div class="form-container">
                    <form method="POST" action="/admin/add">
                        <label>Store Name</label>
                        <input type="text" name="name" placeholder="e.g., Jumia Kenya" required>
                        <label>Website URL</label>
                        <input type="text" name="url" placeholder="https://example.com/" required>
                        <label>Affiliate ID (optional)</label>
                        <input type="text" name="affiliate_id" placeholder="e.g., JN9rGFC">
                        <label>Product CSS Selector</label>
                        <input type="text" name="product_selector" placeholder="div.product-item" required>
                        <label>Title CSS Selector</label>
                        <input type="text" name="title_selector" placeholder="p.product-title" required>
                        <label>Price CSS Selector</label>
                        <input type="text" name="price_selector" placeholder="div.product-price" required>
                        <label>Link CSS Selector</label>
                        <input type="text" name="link_selector" placeholder="a[href]" required>
                        <button type="submit">➕ Add Store</button>
                    </form>
                </div>
            </div>

            <div class="card">
                <h2>📦 Active Stores</h2>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Store Name</th>
                                <th>Affiliate ID</th>
                                <th>Website URL</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>""" + sites_html + """</tbody>
                    </table>
                </div>
            </div>

            <div class="card">
                <h2>🛍️ Recent Deals</h2>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>Store</th>
                                <th>Product</th>
                                <th>Price</th>
                                <th>Link</th>
                                <th>Discovered</th>
                            </tr>
                        </thead>
                        <tbody>""" + deals_html + """</tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Edit Modal -->
        <div class="modal-overlay" id="editModal">
            <div class="modal">
                <div class="modal-header">
                    <h2>✏️ Edit Store</h2>
                    <button class="modal-close" onclick="closeEditModal()">✕</button>
                </div>
                <form method="POST" action="/admin/edit" id="editForm">
                    <input type="hidden" name="site_id" id="edit_site_id">
                    <label>Store Name</label>
                    <input type="text" name="name" id="edit_name" required>
                    <label>Website URL</label>
                    <input type="text" name="url" id="edit_url" required>
                    <label>Affiliate ID</label>
                    <input type="text" name="affiliate_id" id="edit_affiliate_id">
                    <label>Product CSS Selector</label>
                    <input type="text" name="product_selector" id="edit_product_selector" required>
                    <label>Title CSS Selector</label>
                    <input type="text" name="title_selector" id="edit_title_selector" required>
                    <label>Price CSS Selector</label>
                    <input type="text" name="price_selector" id="edit_price_selector" required>
                    <label>Link CSS Selector</label>
                    <input type="text" name="link_selector" id="edit_link_selector" required>
                    <button type="submit" class="save-btn">💾 Save Changes</button>
                </form>
            </div>
        </div>

        <!-- Toast Notification -->
        <div class="toast" id="toast"></div>

        <script>
            function showToast(message, type = 'info') {
                const toast = document.getElementById('toast');
                toast.textContent = message;
                toast.className = 'toast ' + type + ' show';
                setTimeout(() => { toast.className = 'toast'; }, 3000);
            }

            function openEditModal(id, name, url, affiliateId, productSelector, titleSelector, priceSelector, linkSelector) {
                document.getElementById('edit_site_id').value = id;
                document.getElementById('edit_name').value = name;
                document.getElementById('edit_url').value = url;
                document.getElementById('edit_affiliate_id').value = affiliateId;
                document.getElementById('edit_product_selector').value = productSelector;
                document.getElementById('edit_title_selector').value = titleSelector;
                document.getElementById('edit_price_selector').value = priceSelector;
                document.getElementById('edit_link_selector').value = linkSelector;
                document.getElementById('editModal').classList.add('active');
            }

            function closeEditModal() {
                document.getElementById('editModal').classList.remove('active');
            }

            // Close modal when clicking outside
            document.getElementById('editModal').addEventListener('click', function(e) {
                if (e.target === this) closeEditModal();
            });

            function refreshSite(siteId, siteName) {
                const btn = event.target;
                btn.classList.add('spinning');
                btn.disabled = true;
                showToast('🔄 Refreshing ' + siteName + '...', 'info');

                fetch('/admin/refresh/' + siteId, { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        btn.classList.remove('spinning');
                        btn.disabled = false;
                        if (data.status === 'success') {
                            showToast('✅ ' + siteName + ' refreshed! ' + data.new_deals + ' new deals, ' + data.price_drops + ' price changes.', 'success');
                            setTimeout(() => location.reload(), 2000);
                        } else {
                            showToast('⚠️ ' + data.message, 'error');
                        }
                    })
                    .catch(error => {
                        btn.classList.remove('spinning');
                        btn.disabled = false;
                        showToast('❌ Error refreshing ' + siteName, 'error');
                    });
            }
        </script>
    </body>
    </html>
    """
    return html


@app.post("/admin/add")
def add_site(
        name: str = Form(...), url: str = Form(...), affiliate_id: str = Form(""),
        product_selector: str = Form(...), title_selector: str = Form(...),
        price_selector: str = Form(...), link_selector: str = Form(...),
        db: Session = Depends(get_db)
):
    new_site = Site(
        name=name, url=url, affiliate_id=affiliate_id,
        product_selector=product_selector, title_selector=title_selector,
        price_selector=price_selector, link_selector=link_selector
    )
    db.add(new_site)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/edit")
def edit_site(
        site_id: int = Form(...), name: str = Form(...), url: str = Form(...),
        affiliate_id: str = Form(""), product_selector: str = Form(...),
        title_selector: str = Form(...), price_selector: str = Form(...),
        link_selector: str = Form(...), db: Session = Depends(get_db)
):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        old_name = site.name
        site.name = name
        site.url = url
        site.affiliate_id = affiliate_id if affiliate_id else None
        site.product_selector = product_selector
        site.title_selector = title_selector
        site.price_selector = price_selector
        site.link_selector = link_selector

        # If store name changed, update all deals with old name
        if old_name != name:
            db.query(Deal).filter(Deal.store == old_name).update({"store": name})
            db.query(PriceSnapshot).filter(PriceSnapshot.store == old_name).update({"store": name})

        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/delete/{site_id}")
def delete_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        db.query(Deal).filter(Deal.store == site.name).delete()
        db.query(PriceSnapshot).filter(PriceSnapshot.store == site.name).delete()
        db.delete(site)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/refresh")
def manual_refresh():
    scrape_in_background()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/refresh/{site_id}")
def refresh_single_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        return {"status": "error", "message": "Store not found"}

    # Run scrape in background for this single site
    def do_scrape():
        try:
            new_count, drop_count = scrape_single_site(
                site.name, site.url, site.product_selector,
                site.title_selector, site.price_selector, site.link_selector
            )
            print(f"✅ Single refresh complete for {site.name}: {new_count} new, {drop_count} drops")
        except Exception as e:
            print(f"❌ Single refresh error for {site.name}: {e}")

    thread = threading.Thread(target=do_scrape, daemon=True)
    thread.start()

    return {"status": "success", "message": f"Refreshing {site.name}...", "new_deals": 0, "price_drops": 0}


@app.get("/debug/telegram")
def debug_telegram():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    return {
        "token_set": bool(token),
        "token_length": len(token) if token else 0,
        "token_preview": token[:10] + "..." if token and len(token) > 10 else token,
        "chat_id_set": bool(chat_id),
        "chat_id_value": chat_id
    }


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "healthy"}


@app.api_route("/", methods=["GET", "HEAD"])
def home():
    return {"message": "Welcome to Mali Mali Treasure Hunter! Visit /deals for data, /admin for dashboard."}