from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import uvicorn
import logging
import requests
from bs4 import BeautifulSoup

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


@app.post("/add_site")
def add_site(name: str = Form(...), url: str = Form(...), product_selector: str = Form(...),
             title_selector: str = Form(...), price_selector: str = Form(...), link_selector: str = Form(""),
             affiliate_link: str = Form(""), db: Session = Depends(get_db)):
    new_site = Site(name=name, url=url, product_selector=product_selector, title_selector=title_selector,
                    price_selector=price_selector, link_selector=link_selector if link_selector else None,
                    affiliate_link=affiliate_link if affiliate_link else None)
    db.add(new_site)
    db.commit()
    logger.info(f"✅ Added new site: {name}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/edit_site/{site_id}")
def edit_site(site_id: int, name: str = Form(...), url: str = Form(...), product_selector: str = Form(...),
              title_selector: str = Form(...), price_selector: str = Form(...), link_selector: str = Form(""),
              affiliate_link: str = Form(""), db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        site.name = name;
        site.url = url;
        site.product_selector = product_selector;
        site.title_selector = title_selector;
        site.price_selector = price_selector;
        site.link_selector = link_selector if link_selector else None;
        site.affiliate_link = affiliate_link if affiliate_link else None
        db.commit()
        logger.info(f"✏️ Updated site: {name}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete_site/{site_id}")
def delete_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        logger.info(f"🗑️ DELETING SITE: {site.name} (ID: {site_id})")
        db.delete(site);
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/refresh_site/{site_id}")
def refresh_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    logger.info(f"🔄 MANUAL SCRAPE TRIGGERED for: {site.name if site else 'Unknown'}")
    scrape_single_site(site_id, db)
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete_deal/{deal_id}")
def delete_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal:
        logger.info(f"️ Deleted deal: {deal.title}")
        db.delete(deal);
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/scan_website")
def scan_website(url: str = Form(...)):
    """Smart heuristic scanner to find CSS selectors."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.5"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"error": f"Failed to load page (Status: {response.status_code})"}

        soup = BeautifulSoup(response.text, 'lxml')

        # Find product containers
        product_suggestions = []
        for tag in soup.find_all(['div', 'li', 'article']):
            classes = tag.get('class', [])
            class_str = ' '.join(classes)
            if any(kw in class_str.lower() for kw in ['product', 'item', 'card', 'grid']):
                selector = f"{tag.name}.{class_str.replace(' ', '.')}"
                if len(soup.select(selector)) > 3:
                    product_suggestions.append(selector)
        product_suggestions = list(dict.fromkeys(product_suggestions))[:3]
        if not product_suggestions:
            product_suggestions = [".product-item", ".product-card", ".grid-item"]

        return {
            "product_selector": product_suggestions,
            "title_selector": ["h2.title", "h3.title", ".product-title", ".name", "h2", "h3"],
            "price_selector": [".price", ".product-price", "span.price", ".amount"]
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    sites = db.query(Site).all()
    deals = db.query(Deal).order_by(Deal.created_at.desc()).all()

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mali Mali Command Center</title>
        <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; background-color: #0a0a0a; color: #FFD700; padding: 20px; margin: 0; }
            h1, h2 { text-align: center; color: #FFD700; text-shadow: 1px 1px 2px #000; letter-spacing: 2px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .card { background-color: #141414; border: 1px solid #FFD700; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(255, 215, 0, 0.1); }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { border: 1px solid #333; padding: 10px; text-align: left; color: #FFF; vertical-align: top; }
            th { background-color: #000; color: #FFD700; text-transform: uppercase; font-size: 0.85em; }
            input[type="text"], input[type="url"] { background-color: #000; border: 1px solid #FFD700; color: #FFD700; padding: 8px; width: 95%; margin-bottom: 10px; font-size: 0.9em; }
            button, .btn { background-color: #FFD700; color: #000; border: none; padding: 8px 15px; cursor: pointer; font-weight: bold; text-decoration: none; display: inline-block; margin-right: 5px; margin-bottom: 5px; }
            button:hover, .btn:hover { background-color: #FFF; }
            .btn-scan { background-color: #0078D7; color: #FFF; }
            .btn-scan:hover { background-color: #005A9E; }
            .btn-danger { background-color: #8B0000; color: #FFF; }
            .btn-danger:hover { background-color: #FF4500; }
            .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
            .full-width { grid-column: 1 / -1; }
            details { display: inline-block; }
            summary { list-style: none; cursor: pointer; }
            summary::-webkit-details-marker { display: none; }
        </style>
        <script>
            function confirmDelete(siteName) { return confirm(`Are you sure you want to delete "${siteName}"?`); }
            document.addEventListener('DOMContentLoaded', function() {
                document.getElementById('scan-button').addEventListener('click', function() {
                    const url = document.getElementById('scan-url').value;
                    if (!url) { alert('Please enter a website URL first.'); return; }
                    const btn = document.getElementById('scan-button');
                    btn.textContent = 'Scanning...'; btn.disabled = true;
                    fetch('/scan_website', { method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: `url=${encodeURIComponent(url)}` })
                    .then(response => response.json())
                    .then(data => {
                        if (data.error) { alert('Scan failed: ' + data.error); return; }
                        if (data.product_selector && data.product_selector.length > 0) document.getElementById('product_selector').value = data.product_selector[0];
                        if (data.title_selector && data.title_selector.length > 0) document.getElementById('title_selector').value = data.title_selector[0];
                        if (data.price_selector && data.price_selector.length > 0) document.getElementById('price_selector').value = data.price_selector[0];
                        alert('Selectors auto-filled! Review and adjust if needed.');
                    })
                    .catch(error => alert('Scan failed. Check console.'))
                    .finally(() => { btn.textContent = ' Scan Website'; btn.disabled = false; });
                });
            });
        </script>
    </head>
    <body>
        <div class="container">
            <h1> MALI MALI COMMAND CENTER</h1>
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
                            <input type="url" name="url" id="scan-url" required placeholder="https://...">
                        </div>
                        <div class="full-width" style="display: flex; justify-content: flex-end;">
                            <button type="button" id="scan-button" class="btn btn-scan">🔍 Scan Website</button>
                        </div>
                        <div class="full-width">
                            <label style="color:#FFF;">Product Container Selector (CSS):</label>
                            <input type="text" id="product_selector" name="product_selector" required placeholder="Auto-filled by scanner">
                        </div>
                        <div>
                            <label style="color:#FFF;">Title Selector:</label>
                            <input type="text" id="title_selector" name="title_selector" required placeholder="Auto-filled by scanner">
                        </div>
                        <div>
                            <label style="color:#FFF;">Price Selector:</label>
                            <input type="text" id="price_selector" name="price_selector" required placeholder="Auto-filled by scanner">
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

            <div class="card">
                <h2>🛠️ Managed Websites</h2>
                <table>
                    <tr>
                        <th>Name</th>
                        <th>URL</th>
                        <th>Selectors</th>
                        <th>Affiliate</th>
                        <th>Actions</th>
                    </tr>
    """.format()

    for site in sites:
        selectors_info = """<small style="color:#AAA;">Product: {}<br>Title: {}<br>Price: {}</small>""".format(
            site.product_selector or 'N/A', site.title_selector or 'N/A', site.price_selector or 'N/A')
        affiliate_info = site.affiliate_link if site.affiliate_link else "None"
        html += """
                    <tr>
                        <td>{}</td>
                        <td><a href="{}" target="_blank" style="color:#FFD700;">{}...</a></td>
                        <td>{}</td>
                        <td><small style="color:#AAA;">{}</small></td>
                        <td>
                            <form action="/refresh_site/{}" method="POST" style="display:inline;"><button type="submit">🔄 Refresh</button></form>
                            <details style="display:inline;">
                                <summary class="btn" style="cursor:pointer;">️ Edit</summary>
                                <form action="/edit_site/{}" method="POST" style="margin-top:10px; padding: 10px; background: #000; border-radius: 5px;">
                                    <input type="text" name="name" value="{}" required>
                                    <input type="url" name="url" value="{}" required>
                                    <input type="text" name="product_selector" value="{}" required>
                                    <input type="text" name="title_selector" value="{}" required>
                                    <input type="text" name="price_selector" value="{}" required>
                                    <input type="text" name="link_selector" value="{}">
                                    <input type="text" name="affiliate_link" value="{}">
                                    <button type="submit">Save Changes</button>
                                </form>
                            </details>
                            <form action="/delete_site/{}" method="POST" style="display:inline;" onsubmit="return confirmDelete('{}');"><button type="submit" class="btn-danger">🗑️ Delete</button></form>
                        </td>
                    </tr>
        """.format(site.name, site.url, site.url[:40], selectors_info, affiliate_info, site.id, site.id, site.name,
                   site.url, site.product_selector or '', site.title_selector or '', site.price_selector or '',
                   site.link_selector or '', site.affiliate_link or '', site.id, site.name)

    html += """
