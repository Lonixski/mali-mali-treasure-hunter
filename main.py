from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import uvicorn
import logging

from database import get_db, Deal, Site, engine, Base
from scheduler import init_scheduler, scrape_single_site

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_scheduler()
    yield


app = FastAPI(title="Mali Mali Admin", lifespan=lifespan)


@app.on_event("startup")
def startup_db():
    Base.metadata.create_all(bind=engine)


# --- ROUTES FOR ACTIONS ---

@app.post("/add_site")
def add_site(
        name: str = Form(...),
        url: str = Form(...),
        product_selector: str = Form(...),
        title_selector: str = Form(...),
        price_selector: str = Form(...),
        link_selector: str = Form(""),
        affiliate_link: str = Form(""),
        db: Session = Depends(get_db)
):
    new_site = Site(
        name=name,
        url=url,
        product_selector=product_selector,
        title_selector=title_selector,
        price_selector=price_selector,
        link_selector=link_selector if link_selector else None,
        affiliate_link=affiliate_link if affiliate_link else None
    )
    db.add(new_site)
    db.commit()
    logger.info(f"✅ Added new site: {name}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/edit_site/{site_id}")
def edit_site(
        site_id: int,
        name: str = Form(...),
        url: str = Form(...),
        product_selector: str = Form(...),
        title_selector: str = Form(...),
        price_selector: str = Form(...),
        link_selector: str = Form(""),
        affiliate_link: str = Form(""),
        db: Session = Depends(get_db)
):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        site.name = name
        site.url = url
        site.product_selector = product_selector
        site.title_selector = title_selector
        site.price_selector = price_selector
        site.link_selector = link_selector if link_selector else None
        site.affiliate_link = affiliate_link if affiliate_link else None
        db.commit()
        logger.info(f"✏️ Updated site: {name}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete_site/{site_id}")
def delete_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        logger.info(f"🗑️ DELETING SITE: {site.name} (ID: {site_id})")
        db.delete(site)
        db.commit()
        logger.info(f"✅ Site '{site.name}' and all its deals have been permanently deleted.")
    return RedirectResponse(url="/", status_code=303)


@app.post("/refresh_site/{site_id}")
def refresh_site(site_id: int, db: Session = Depends(get_db)):
    """Triggers the scraper for this specific site immediately."""
    site = db.query(Site).filter(Site.id == site_id).first()
    logger.info(f"🔄 MANUAL SCRAPE TRIGGERED for: {site.name if site else 'Unknown'}")
    scrape_single_site(site_id, db)
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete_deal/{deal_id}")
def delete_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal:
        logger.info(f"🗑️ Deleted deal: {deal.title}")
        db.delete(deal)
        db.commit()
    return RedirectResponse(url="/", status_code=303)


# --- MAIN DASHBOARD UI ---

@app.get("/", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    sites = db.query(Site).all()
    deals = db.query(Deal).order_by(Deal.created_at.desc()).all()

    # Build HTML using .format() to avoid f-string backslash issues
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mali Mali Command Center</title>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #0a0a0a; color: #FFD700; padding: 20px; margin: 0; }}
            h1, h2 {{ text-align: center; color: #FFD700; text-shadow: 1px 1px 2px #000; letter-spacing: 2px; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .card {{ background-color: #141414; border: 1px solid #FFD700; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(255, 215, 0, 0.1); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th, td {{ border: 1px solid #333; padding: 10px; text-align: left; color: #FFF; vertical-align: top; }}
            th {{ background-color: #000; color: #FFD700; text-transform: uppercase; font-size: 0.85em; }}
            input[type="text"], input[type="url"] {{ background-color: #000; border: 1px solid #FFD700; color: #FFD700; padding: 8px; width: 95%; margin-bottom: 10px; font-size: 0.9em; }}
            button, .btn {{ background-color: #FFD700; color: #000; border: none; padding: 8px 15px; cursor: pointer; font-weight: bold; text-decoration: none; display: inline-block; margin-right: 5px; margin-bottom: 5px; }}
            button:hover, .btn:hover {{ background-color: #FFF; }}
            .btn-danger {{ background-color: #8B0000; color: #FFF; }}
            .btn-danger:hover {{ background-color: #FF4500; }}
            .form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
            .full-width {{ grid-column: 1 / -1; }}
            details {{ display: inline-block; }}
            summary {{ list-style: none; cursor: pointer; }}
            summary::-webkit-details-marker {{ display: none; }}
        </style>
        <script>
            function confirmDelete(siteName) {{
                return confirm(`Are you sure you want to delete "${{siteName}}" and all its deals? This cannot be undone.`);
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <h1>🏆 MALI MALI COMMAND CENTER</h1>

            <!-- ADD WEBSITE SECTION -->
            <div class="card">
                <h2>➕ Add New Website</h2>
                <form action="/add_site" method="POST">
                    <div class="form-grid">
                        <div>
                            <label style="color:#FFF;">Site Name:</label>
                            <input type="text" name="name" required placeholder="e.g., Jumia">
                        </div>
                        <div>
                            <label style="color:#FFF;">Website URL:</label>
                            <input type="url" name="url" required placeholder="https://...">
                        </div>
                        <div class="full-width">
                            <label style="color:#FFF;">Product Container Selector (CSS):</label>
                            <input type="text" name="product_selector" required placeholder="e.g., .product-card">
                        </div>
                        <div>
                            <label style="color:#FFF;">Title Selector:</label>
                            <input type="text" name="title_selector" required placeholder="e.g., h2.title">
                        </div>
                        <div>
                            <label style="color:#FFF;">Price Selector:</label>
                            <input type="text" name="price_selector" required placeholder="e.g., span.price">
                        </div>
                        <div>
                            <label style="color:#FFF;">Link Selector (optional):</label>
                            <input type="text" name="link_selector" placeholder="e.g., a.product-link">
                        </div>
                        <div>
                            <label style="color:#FFF;">Affiliate Link (optional):</label>
                            <input type="text" name="affiliate_link" placeholder="e.g., https://your-affiliate-link.com">
                        </div>
                    </div>
                    <button type="submit" style="margin-top: 10px;">Add Site</button>
                </form>
            </div>

            <!-- MANAGE WEBSITES SECTION -->
            <div class="card">
                <h2>️ Managed Websites</h2>
                <table>
                    <tr>
                        <th>Name</th>
                        <th>URL</th>
                        <th>Selectors</th>
                        <th>Affiliate</th>
                        <th>Actions</th>
                    </tr>
    """.format()

    # Add sites to the table
    for site in sites:
        selectors_info = """
            <small style="color:#AAA;">
                Product: {}<br>
                Title: {}<br>
                Price: {}
            </small>
        """.format(
            site.product_selector or 'N/A',
            site.title_selector or 'N/A',
            site.price_selector or 'N/A'
        )

        affiliate_info = site.affiliate_link if site.affiliate_link else "None"

        html += """
                    <tr>
                        <td>{}</td>
                        <td><a href="{}" target="_blank" style="color:#FFD700;">{}...</a></td>
                        <td>{}</td>
                        <td><small style="color:#AAA;">{}</small></td>
                        <td>
                            <form action="/refresh_site/{}" method="POST" style="display:inline;">
                                <button type="submit">🔄 Refresh</button>
                            </form>
                            <details style="display:inline;">
                                <summary class="btn" style="cursor:pointer;">✏️ Edit</summary>
                                <form action="/edit_site/{}" method="POST" style="margin-top:10px; padding: 10px; background: #000; border-radius: 5px;">
                                    <input type="text" name="name" value="{}" required placeholder="Site Name">
                                    <input type="url" name="url" value="{}" required placeholder="URL">
                                    <input type="text" name="product_selector" value="{}" required placeholder="Product Selector">
                                    <input type="text" name="title_selector" value="{}" required placeholder="Title Selector">
                                    <input type="text" name="price_selector" value="{}" required placeholder="Price Selector">
                                    <input type="text" name="link_selector" value="{}" placeholder="Link Selector (optional)">
                                    <input type="text" name="affiliate_link" value="{}" placeholder="Affiliate Link (optional)">
                                    <button type="submit">Save Changes</button>
                                </form>
                            </details>
                            <form action="/delete_site/{}" method="POST" style="display:inline;" onsubmit="return confirmDelete('{}');">
                                <button type="submit" class="btn-danger">🗑️ Delete</button>
                            </form>
                        </td>
                    </tr>
        """.format(
            site.name,
            site.url,
            site.url[:40],
            selectors_info,
            affiliate_info,
            site.id,
            site.id,
            site.name,
            site.url,
            site.product_selector or '',
            site.title_selector or '',
            site.price_selector or '',
            site.link_selector or '',
            site.affiliate_link or '',
            site.id,
            site.name
        )

    html += """
                </table>
            </div>

            <!-- DEALS SECTION -->
            <div class="card">
                <h2>🔥 Active Deals</h2>
                <table>
                    <tr>
                        <th>Title</th>
                        <th>Price (KES)</th>
                        <th>Category</th>
                        <th>Actions</th>
                    </tr>
    """

    for deal in deals:
        html += """
                    <tr>
                        <td>{}</td>
                        <td>{}</td>
                        <td>{}</td>
                        <td>
                            <form action="/delete_deal/{}" method="POST" style="display:inline;">
                                <button type="submit" class="btn-danger">🗑️ Delete</button>
                            </form>
                        </td>
                    </tr>
        """.format(
            deal.title,
            "{:,.0f}".format(deal.current_price),
            deal.category or 'N/A',
            deal.id
        )

    html += """
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/deals")
def get_active_deals(db: Session = Depends(get_db)):
    """Endpoint for the Chrome Extension."""
    deals = db.query(Deal).filter(Deal.is_expired == False).order_by(Deal.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "title": d.title,
            "url": d.url,
            "price": d.current_price,
            "original_price": d.original_price,
            "category": d.category,
            "image_url": d.image_url
        } for d in deals
    ]


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)