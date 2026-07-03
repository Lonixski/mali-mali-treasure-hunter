from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import uvicorn
import logging

from database import get_db, Deal, Site, engine, Base
from scheduler import init_scheduler, scrape_specific_site

logging.basicConfig(level=logging.INFO)
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
def add_site(name: str = Form(...), url: str = Form(...), db: Session = Depends(get_db)):
    new_site = Site(name=name, url=url)
    db.add(new_site)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/edit_site/{site_id}")
def edit_site(site_id: int, name: str = Form(...), url: str = Form(...), db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if site:
        site.name = name
        site.url = url
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/refresh_site/{site_id}")
def refresh_site(site_id: int, db: Session = Depends(get_db)):
    """Triggers the scraper for this specific site immediately."""
    scrape_specific_site(site_id, db)
    return RedirectResponse(url="/", status_code=303)


@app.post("/delete_deal/{deal_id}")
def delete_deal(deal_id: int, db: Session = Depends(get_db)):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal:
        db.delete(deal)
        db.commit()
    return RedirectResponse(url="/", status_code=303)


# --- MAIN DASHBOARD UI ---

@app.get("/", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    sites = db.query(Site).all()
    deals = db.query(Deal).order_by(Deal.created_at.desc()).all()

    # STRICT BLACK AND GOLD DESIGN
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mali Mali Command Center</title>
        <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; background-color: #0a0a0a; color: #FFD700; padding: 20px; margin: 0; }
            h1, h2 { text-align: center; color: #FFD700; text-shadow: 1px 1px 2px #000; letter-spacing: 2px; }
            .container { max-width: 1000px; margin: 0 auto; }
            .card { background-color: #141414; border: 1px solid #FFD700; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(255, 215, 0, 0.1); }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { border: 1px solid #333; padding: 10px; text-align: left; color: #FFF; }
            th { background-color: #000; color: #FFD700; text-transform: uppercase; }
            input[type="text"], input[type="url"] { background-color: #000; border: 1px solid #FFD700; color: #FFD700; padding: 8px; width: 95%; margin-bottom: 10px; }
            button, .btn { background-color: #FFD700; color: #000; border: none; padding: 8px 15px; cursor: pointer; font-weight: bold; text-decoration: none; display: inline-block; margin-right: 5px; }
            button:hover, .btn:hover { background-color: #FFF; }
            .btn-danger { background-color: #8B0000; color: #FFF; }
            .btn-danger:hover { background-color: #FF4500; }
            .form-row { display: flex; gap: 10px; align-items: flex-end; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏆 MALI MALI COMMAND CENTER</h1>

            <!-- ADD WEBSITE SECTION -->
            <div class="card">
                <h2>➕ Add New Website</h2>
                <form action="/add_site" method="POST" class="form-row">
                    <div style="flex: 1;">
                        <label style="color:#FFF;">Site Name:</label>
                        <input type="text" name="name" required placeholder="e.g., Jumia">
                    </div>
                    <div style="flex: 2;">
                        <label style="color:#FFF;">Website URL:</label>
                        <input type="url" name="url" required placeholder="https://...">
                    </div>
                    <button type="submit">Add Site</button>
                </form>
            </div>

            <!-- MANAGE WEBSITES SECTION -->
            <div class="card">
                <h2> Managed Websites</h2>
                <table>
                    <tr>
                        <th>Name</th>
                        <th>URL</th>
                        <th>Actions</th>
                    </tr>
    """

    for site in sites:
        html += f"""
                    <tr>
                        <td>{site.name}</td>
                        <td><a href="{site.url}" target="_blank" style="color:#FFD700;">{site.url}</a></td>
                        <td>
                            <form action="/refresh_site/{site.id}" method="POST" style="display:inline;">
                                <button type="submit">🔄 Refresh & Scrape</button>
                            </form>
                            <details style="display:inline;">
                                <summary class="btn" style="cursor:pointer;">✏️ Edit</summary>
                                <form action="/edit_site/{site.id}" method="POST" style="margin-top:10px;">
                                    <input type="text" name="name" value="{site.name}" required>
                                    <input type="url" name="url" value="{site.url}" required>
                                    <button type="submit">Save Changes</button>
                                </form>
                            </details>
                        </td>
                    </tr>
        """

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
        html += f"""
                    <tr>
                        <td>{deal.title}</td>
                        <td>{deal.current_price:,.0f}</td>
                        <td>{deal.category or 'N/A'}</td>
                        <td>
                            <form action="/delete_deal/{deal.id}" method="POST" style="display:inline;">
                                <button type="submit" class="btn-danger">️ Delete</button>
                            </form>
                        </td>
                    </tr>
        """

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


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)