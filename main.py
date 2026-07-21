from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import uvicorn
import logging
import requests
import re
from bs4 import BeautifulSoup, NavigableString
from collections import Counter

from database import get_db, Deal, Site, engine, Base
from scheduler import init_scheduler, scrape_single_site

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Pre-loaded verified selectors for major Kenyan sites
KNOWN_SITES = {
    "kilimall.co.ke": {
        "product_selector": ".product-item",
        "title_selector": ".product-title",
        "price_selector": ".product-price",
        "link_selector": "a",
        "image_selector": "img"
    },
    "jumia.co.ke": {
        "product_selector": ".prd",
        "title_selector": ".title",
        "price_selector": ".prc",
        "link_selector": "a",
        "image_selector": "img"
    },
    "jiji.co.ke": {
        "product_selector": ".listing-card",
        "title_selector": ".listing-title",
        "price_selector": ".listing-price",
        "link_selector": "a",
        "image_selector": "img"
    }
}


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
             image_selector: str = Form(""), affiliate_link: str = Form(""), db: Session = Depends(get_db)):
    new_site = Site(name=name, url=url, product_selector=product_selector, title_selector=title_selector,
                    price_selector=price_selector, link_selector=link_selector if link_selector else None,
                    image_selector=image_selector if image_selector else None,
                    affiliate_link=affiliate_link if affiliate_link else None)
    db.add(new_site)
    db.commit()
    logger.info(f"✅ Added new site: {name}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/edit_site/{site_id}")
def edit_site(site_id: int, name: str = Form(...), url: str = Form(...), product_selector: str = Form(...),
              title_selector: str = Form(...), price_selector: str = Form(...), link_selector: str = Form(""),
              image_selector: str = Form(""), affiliate_link: str = Form(""), db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        site.name = name;
        site.url = url;
        site.product_selector = product_selector;
        site.title_selector = title_selector;
        site.price_selector = price_selector;
        site.link_selector = link_selector if link_selector else None;
        site.image_selector = image_selector if image_selector else None;
        site.affiliate_link = affiliate_link if affiliate_link else None
        db.commit()
        logger.info(f"️ Updated site: {name}")
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
        logger.info(f"🗑️ Deleted deal: {deal.title}")
        db.delete(deal);
        db.commit()
    return RedirectResponse(url="/", status_code=303)


def get_best_selector(candidates, fallback):
    if not candidates: return fallback
    counter = Counter(candidates)
    return counter.most_common(1)[0][0]


@app.post("/scan_website")
def scan_website(url: str = Form(...)):
    try:
        # 1. Check Known Sites first
        for domain, selectors in KNOWN_SITES.items():
            if domain in url:
                return selectors

        # 2. Structural Analyzer
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
            if any(kw in class_str.lower() for kw in ['product', 'item', 'card', 'grid', 'listing']):
                selector = f"{tag.name}.{class_str.replace(' ', '.')}"
                if len(soup.select(selector)) > 3:
                    product_suggestions.append(selector)
        product_suggestions = list(dict.fromkeys(product_suggestions))[:3]
        if not product_suggestions:
            return {"error": "Could not find product containers. Try a different URL."}

        containers = soup.select(product_suggestions[0])[:5]

        # Smart Price Finder (Looks for currency symbols)
        price_candidates = []
        currency_pattern = re.compile(r'(KES|KSh|\$|£|€|USD)\s*[\d,]+\.?\d*', re.IGNORECASE)
        for container in containers:
            for tag in container.find_all(['span', 'div', 'p', 'strong', 'b']):
                text = tag.get_text(strip=True)
                if currency_pattern.search(text):
                    classes = tag.get('class', [])
                    if classes:
                        price_candidates.append(f"{tag.name}.{'.'.join(classes)}")
                    else:
                        # If no class, look at parent
                        if tag.parent and tag.parent.get('class'):
                            price_candidates.append(f"{tag.parent.name}.{'.'.join(tag.parent.get('class'))}")

        # Smart Title Finder (Looks for the longest text block)
        title_candidates = []
        for container in containers:
            texts = []
            for tag in container.find_all(['h1', 'h2', 'h3', 'h4', 'a', 'div', 'p']):
                text = tag.get_text(strip=True)
                if 10 < len(text) < 150:  # Reasonable title length
                    texts.append((len(text), tag))
            if texts:
                longest_text_tag = max(texts, key=lambda x: x[0])[1]
                classes = longest_text_tag.get('class', [])
                if classes:
                    title_candidates.append(f"{longest_text_tag.name}.{'.'.join(classes)}")
                elif longest_text_tag.parent and longest_text_tag.parent.get('class'):
                    title_candidates.append(
                        f"{longest_text_tag.parent.name}.{'.'.join(longest_text_tag.parent.get('class'))}")

        # Smart Image Finder (Looks for largest image or specific attributes)
        img_candidates = []
        for container in containers:
            imgs = container.find_all('img')
            if imgs:
                # Prefer images with 'src' over 'data-src' if possible, or largest
                best_img = max(imgs, key=lambda x: x.get('width', 0) or 0)
                classes = best_img.get('class', [])
                if classes:
                    img_candidates.append(f"img.{'.'.join(classes)}")
                else:
                    img_candidates.append("img")

        # Smart Link Finder
        link_candidates = []
        for container in containers:
            links = container.find_all('a', href=True)
            if links:
                # Usually the first link or the one wrapping the title
                best_link = links[0]
                classes = best_link.get('class', [])
                if classes:
                    link_candidates.append(f"a.{'.'.join(classes)}")
                else:
                    link_candidates.append("a")

        return {
            "product_selector": product_suggestions,
            "title_selector": [get_best_selector(title_candidates, "h3")],
            "price_selector": [get_best_selector(price_candidates, ".price")],
            "link_selector": [get_best_selector(link_candidates, "a")],
            "image_selector": [get_best_selector(img_candidates, "img")]
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    sites = db.query(Site).all()
    deals = db.query(Deal).order_by(Deal.created_at.desc()).all()

    html = []
    html.append("<!DOCTYPE html>")
    html.append("<html>")
    html.append("<head>")
    html.append("<title>Mali Mali Command Center</title>")
    html.append("<style>")
    html.append(
        "body { font-family: 'Segoe UI', Arial, sans-serif; background-color: #0a0a0a; color: #FFD700; padding: 20px; margin: 0; }")
    html.append("h1, h2 { text-align: center; color: #FFD700; text-shadow: 1px 1px 2px #000; letter-spacing: 2px; }")
    html.append(".container { max-width: 1200px; margin: 0 auto; }")
    html.append(
        ".card { background-color: #141414; border: 1px solid #FFD700; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(255, 215, 0, 0.1); }")
    html.append("table { width: 100%; border-collapse: collapse; margin-top: 10px; }")
    html.append("th, td { border: 1px solid #333; padding: 10px; text-align: left; color: #FFF; vertical-align: top; }")
    html.append("th { background-color: #000; color: #FFD700; text-transform: uppercase; font-size: 0.85em; }")
    html.append(
        "input[type='text'], input[type='url'] { background-color: #000; border: 1px solid #FFD700; color: #FFD700; padding: 8px; width: 95%; margin-bottom: 10px; font-size: 0.9em; }")
    html.append(
        "button, .btn { background-color: #FFD700; color: #000; border: none; padding: 8px 15px; cursor: pointer; font-weight: bold; text-decoration: none; display: inline-block; margin-right: 5px; margin-bottom: 5px; }")
    html.append("button:hover, .btn:hover { background-color: #FFF; }")
    html.append(".btn-scan { background-color: #0078D7; color: #FFF; }")
    html.append(".btn-scan:hover { background-color: #005A9E; }")
    html.append(".btn-danger { background-color: #8B0000; color: #FFF; }")
    html.append(".btn-danger:hover { background-color: #FF4500; }")
    html.append(".form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }")
    html.append(".full-width { grid-column: 1 / -1; }")
    html.append("details { display: inline-block; }")
    html.append("summary { list-style: none; cursor: pointer; }")
    html.append("summary::-webkit-details-marker { display: none; }")
    html.append("</style>")
    html.append("<script>")
    html.append(
        "function confirmDelete(siteName) { return confirm('Are you sure you want to delete ' + siteName + '?'); }")
    html.append("document.addEventListener('DOMContentLoaded', function() {")
    html.append("  document.getElementById('scan-button').addEventListener('click', function() {")
    html.append("    const url = document.getElementById('scan-url').value;")
    html.append("    if (!url) { alert('Please enter a website URL first.'); return; }")
    html.append("    const btn = document.getElementById('scan-button');")
    html.append("    btn.textContent = 'Scanning...'; btn.disabled = true;")
    html.append(
        "    fetch('/scan_website', { method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: 'url=' + encodeURIComponent(url) })")
    html.append("    .then(response => response.json())")
    html.append("    .then(data => {")
    html.append("      if (data.error) { alert('Scan failed: ' + data.error); return; }")
    html.append(
        "      if (data.product_selector && data.product_selector.length > 0) document.getElementById('product_selector').value = data.product_selector[0];")
    html.append(
        "      if (data.title_selector && data.title_selector.length > 0) document.getElementById('title_selector').value = data.title_selector[0];")
    html.append(
        "      if (data.price_selector && data.price_selector.length > 0) document.getElementById('price_selector').value = data.price_selector[0];")
    html.append(
        "      if (data.link_selector && data.link_selector.length > 0) document.getElementById('link_selector').value = data.link_selector[0];")
    html.append(
        "      if (data.image_selector && data.image_selector.length > 0) document.getElementById('image_selector').value = data.image_selector[0];")
    html.append("      alert('Selectors auto-filled! Review and adjust if needed.');")
    html.append("    })")
    html.append("    .catch(error => alert('Scan failed. Check console.'))")
    html.append("    .finally(() => { btn.textContent = '🔍 Scan Website'; btn.disabled = false; });")
    html.append("  });")
    html.append("});")
    html.append("</script>")
    html.append("</head>")
    html.append("<body>")
    html.append("<div class='container'>")
    html.append("<h1>🏆 MALI MALI COMMAND CENTER</h1>")

    html.append("<div class='card'>")
    html.append("<h2>➕ Add New Website</h2>")
    html.append("<form action='/add_site' method='POST'>")
    html.append("<div class='form-grid'>")
    html.append(
        "<div><label style='color:#FFF;'>Site Name:</label><input type='text' name='name' required placeholder='e.g., Jumia'></div>")
    html.append(
        "<div><label style='color:#FFF;'>Website URL:</label><input type='url' name='url' id='scan-url' required placeholder='https://...'></div>")
    html.append(
        "<div class='full-width' style='display: flex; justify-content: flex-end;'><button type='button' id='scan-button' class='btn btn-scan'>🔍 Scan Website</button></div>")
    html.append(
        "<div class='full-width'><label style='color:#FFF;'>Product Container Selector (CSS):</label><input type='text' id='product_selector' name='product_selector' required placeholder='Auto-filled by scanner'></div>")
    html.append(
        "<div><label style='color:#FFF;'>Title Selector:</label><input type='text' id='title_selector' name='title_selector' required placeholder='Auto-filled by scanner'></div>")
    html.append(
        "<div><label style='color:#FFF;'>Price Selector:</label><input type='text' id='price_selector' name='price_selector' required placeholder='Auto-filled by scanner'></div>")
    html.append(
        "<div><label style='color:#FFF;'>Link Selector (optional):</label><input type='text' id='link_selector' name='link_selector' placeholder='Auto-filled by scanner'></div>")
    html.append(
        "<div><label style='color:#FFF;'>Image Selector (optional):</label><input type='text' id='image_selector' name='image_selector' placeholder='Auto-filled by scanner'></div>")
    html.append(
        "<div><label style='color:#FFF;'>Affiliate Link (optional):</label><input type='text' name='affiliate_link' placeholder='e.g., https://your-affiliate-link.com'></div>")
    html.append("</div>")
    html.append("<button type='submit' style='margin-top: 10px;'>Add Site</button>")
    html.append("</form>")
    html.append("</div>")

    html.append("<div class='card'>")
    html.append("<h2>🛠️ Managed Websites</h2>")
    html.append("<table><tr><th>Name</th><th>URL</th><th>Selectors</th><th>Affiliate</th><th>Actions</th></tr>")

    for site in sites:
        sel_info = f"Product: {site.product_selector or 'N/A'}<br>Title: {site.title_selector or 'N/A'}<br>Price: {site.price_selector or 'N/A'}<br>Image: {site.image_selector or 'N/A'}"
        aff_info = site.affiliate_link if site.affiliate_link else "None"
        url_short = site.url[:40] + "..." if len(site.url) > 40 else site.url

        html.append("<tr>")
        html.append(f"<td>{site.name}</td>")
        html.append(f"<td><a href='{site.url}' target='_blank' style='color:#FFD700;'>{url_short}</a></td>")
        html.append(f"<td><small style='color:#AAA;'>{sel_info}</small></td>")
        html.append(f"<td><small style='color:#AAA;'>{aff_info}</small></td>")
        html.append("<td>")
        html.append(
            f"<form action='/refresh_site/{site.id}' method='POST' style='display:inline;'><button type='submit'>🔄 Refresh</button></form>")
        html.append("<details style='display:inline;'>")
        html.append("<summary class='btn' style='cursor:pointer;'>✏️ Edit</summary>")
        html.append(
            f"<form action='/edit_site/{site.id}' method='POST' style='margin-top:10px; padding: 10px; background: #000; border-radius: 5px;'>")
        html.append(f"<input type='text' name='name' value='{site.name}' required>")
        html.append(f"<input type='url' name='url' value='{site.url}' required>")
        html.append(f"<input type='text' name='product_selector' value='{site.product_selector or ''}' required>")
        html.append(f"<input type='text' name='title_selector' value='{site.title_selector or ''}' required>")
        html.append(f"<input type='text' name='price_selector' value='{site.price_selector or ''}' required>")
        html.append(f"<input type='text' name='link_selector' value='{site.link_selector or ''}'>")
        html.append(f"<input type='text' name='image_selector' value='{site.image_selector or ''}'>")
        html.append(f"<input type='text' name='affiliate_link' value='{site.affiliate_link or ''}'>")
        html.append("<button type='submit'>Save Changes</button>")
        html.append("</form>")
        html.append("</details>")
        html.append(
            f"<form action='/delete_site/{site.id}' method='POST' style='display:inline;' onsubmit=\"return confirmDelete('{site.name}');\"><button type='submit' class='btn-danger'>🗑️ Delete</button></form>")
        html.append("</td>")
        html.append("</tr>")

    html.append("</table>")
    html.append("</div>")

    html.append("<div class='card'>")
    html.append("<h2> Active Deals</h2>")
    html.append("<table><tr><th>Title</th><th>Price (KES)</th><th>Category</th><th>Actions</th></tr>")

    for deal in deals:
        price_fmt = f"{deal.current_price:,.0f}"
        cat = deal.category or 'N/A'
        html.append("<tr>")
        html.append(f"<td>{deal.title}</td>")
        html.append(f"<td>{price_fmt}</td>")
        html.append(f"<td>{cat}</td>")
        html.append(
            f"<td><form action='/delete_deal/{deal.id}' method='POST' style='display:inline;'><button type='submit' class='btn-danger'>🗑️ Delete</button></form></td>")
        html.append("</tr>")

    html.append("</table>")
    html.append("</div>")

    html.append("</div>")
    html.append("</body>")
    html.append("</html>")

    return HTMLResponse(content="\n".join(html))


@app.get("/deals")
def get_active_deals(db: Session = Depends(get_db)):
    deals = db.query(Deal).filter(Deal.is_expired == False).order_by(Deal.created_at.desc()).all()
    return [{"id": d.id, "title": d.title, "url": d.url, "price": d.current_price, "original_price": d.original_price,
             "category": d.category, "image_url": d.image_url} for d in deals]


@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)