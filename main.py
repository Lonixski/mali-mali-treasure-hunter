from fastapi import FastAPI, Depends, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import Site, Deal, PriceSnapshot, get_db, engine, Base, SessionLocal
from scheduler import start_scheduler, scrape_in_background
import os
import threading

Base.metadata.create_all(bind=engine)


# One-time migration: Add missing columns if they don't exist
def migrate_database():
    try:
        with engine.connect() as conn:
            if "sqlite" in str(engine.url):
                # SQLite migration
                # Check deals table for image_url
                result = conn.execute(text("PRAGMA table_info(deals)"))
                deal_columns = [row[1] for row in result]
                if "image_url" not in deal_columns:
                    conn.execute(text("ALTER TABLE deals ADD COLUMN image_url VARCHAR"))
                    print("✅ Added image_url column to deals table (SQLite)")

                # Check sites table for affiliate_id
                result = conn.execute(text("PRAGMA table_info(sites)"))
                site_columns = [row[1] for row in result]
                if "affiliate_id" not in site_columns:
                    conn.execute(text("ALTER TABLE sites ADD COLUMN affiliate_id VARCHAR"))
                    print("✅ Added affiliate_id column to sites table (SQLite)")
            else:
                # PostgreSQL migration
                # Check deals table for image_url
                result = conn.execute(text("""
                                           SELECT column_name
                                           FROM information_schema.columns
                                           WHERE table_name = 'deals'
                                           """))
                deal_columns = [row[0] for row in result]
                if "image_url" not in deal_columns:
                    conn.execute(text("ALTER TABLE deals ADD COLUMN image_url VARCHAR"))
                    print("✅ Added image_url column to deals table (PostgreSQL)")

                # Check sites table for affiliate_id
                result = conn.execute(text("""
                                           SELECT column_name
                                           FROM information_schema.columns
                                           WHERE table_name = 'sites'
                                           """))
                site_columns = [row[0] for row in result]
                if "affiliate_id" not in site_columns:
                    conn.execute(text("ALTER TABLE sites ADD COLUMN affiliate_id VARCHAR"))
                    print("✅ Added affiliate_id column to sites table (PostgreSQL)")
    except Exception as e:
        print(f"⚠️ Migration error: {e}")


migrate_database()

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
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{site.name}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{site.affiliate_id or "Not Set"}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #6b7280;">{site.url}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                <form method="POST" action="/admin/delete/{site.id}" style="display:inline;">
                    <button type="submit" class="delete-btn">Delete</button>
                </form>
            </td>
        </tr>
        """

    deals_html = ""
    for deal in deals:
        deals_html += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{deal.store}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{deal.product}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #dc2626; font-weight: 600;">{deal.price}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;"><a href="{deal.link}" target="_blank" style="color: #059669;">View Deal →</a></td>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #9ca3af;">{deal.discovered_at[:16] if deal.discovered_at else 'N/A'}</td>
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
            input { width: 100%; padding: 12px 16px; margin: 8px 0 16px 0; border: 2px solid #e5e7eb; border-radius: 8px; font-size: 14px; font-family: inherit; }
            input:focus { outline: none; border-color: #dc2626; }
            button { background: linear-gradient(135deg, #dc2626 0%, #f59e0b 100%); color: white; padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px; }
            button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(220, 38, 38, 0.3); }
            .refresh-btn { background: linear-gradient(135deg, #059669 0%, #10b981 100%); margin-bottom: 20px; padding: 14px 28px; font-size: 15px; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th { background: #f3f4f6; padding: 14px; text-align: left; font-weight: 600; color: #374151; font-size: 13px; text-transform: uppercase; }
            .delete-btn { background: #ef4444; padding: 8px 16px; font-size: 12px; }
            .stats { display: flex; gap: 20px; margin-bottom: 20px; }
            .stat-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px; flex: 1; text-align: center; }
            .stat-number { font-size: 32px; font-weight: 800; margin-bottom: 4px; }
            .stat-label { font-size: 13px; opacity: 0.9; }
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
                    <button type="submit" class="refresh-btn">🔄 Refresh All Sites Now</button>
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
                <h2>Add New Store</h2>
                <div class="form-container">
                    <form method="POST" action="/admin/add">
                        <input type="text" name="name" placeholder="Store Name (e.g., Jumia Kenya)" required>
                        <input type="text" name="url" placeholder="Website URL" required>
                        <input type="text" name="affiliate_id" placeholder="Affiliate ID (optional)">
                        <input type="text" name="product_selector" placeholder="Product CSS Selector" required>
                        <input type="text" name="title_selector" placeholder="Title CSS Selector" required>
                        <input type="text" name="price_selector" placeholder="Price CSS Selector" required>
                        <input type="text" name="link_selector" placeholder="Link CSS Selector" required>
                        <button type="submit">➕ Add Store</button>
                    </form>
                </div>
            </div>

            <div class="card">
                <h2>📦 Active Stores</h2>
                <table>
                    <thead><tr><th>Store Name</th><th>Affiliate ID</th><th>Website URL</th><th>Actions</th></tr></thead>
                    <tbody>""" + sites_html + """</tbody>
                </table>
            </div>

            <div class="card">
                <h2>🛍️ Recent Deals</h2>
                <table>
                    <thead><tr><th>Store</th><th>Product</th><th>Price</th><th>Link</th><th>Discovered</th></tr></thead>
                    <tbody>""" + deals_html + """</tbody>
                </table>
            </div>
        </div>
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