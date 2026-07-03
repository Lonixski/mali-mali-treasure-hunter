from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import uvicorn

from database import get_db, Deal, engine, Base
from scheduler import init_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize the background scheduler
    init_scheduler()
    yield


app = FastAPI(title="Mali Mali Treasure Hunter API", lifespan=lifespan)


@app.on_event("startup")
def startup_db():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)


@app.get("/")
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    active_deals = db.query(Deal).filter(Deal.is_expired == False).all()

    # STRICT MANADATE: Black and Gold Color Scheme
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mali Mali Admin</title>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #0a0a0a; color: #FFD700; padding: 20px; margin: 0; }}
            h1 {{ text-align: center; color: #FFD700; text-shadow: 1px 1px 2px #000; letter-spacing: 2px; }}
            .stats {{ text-align: center; font-size: 1.2em; margin-bottom: 20px; color: #FFF; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; box-shadow: 0 0 10px rgba(255, 215, 0, 0.2); }}
            th, td {{ border: 1px solid #FFD700; padding: 12px; text-align: left; }}
            th {{ background-color: #000000; color: #FFD700; text-transform: uppercase; font-size: 0.9em; }}
            tr:nth-child(even) {{ background-color: #141414; }}
            tr:nth-child(odd) {{ background-color: #0d0d0d; }}
            a {{ color: #FFD700; text-decoration: none; font-weight: bold; }}
            a:hover {{ text-decoration: underline; color: #FFF; }}
        </style>
    </head>
    <body>
        <h1>🏆 MALI MALI TREASURE HUNTER</h1>
        <p class="stats">Active Deals Tracked: <strong style="color: #FFD700;">{len(active_deals)}</strong></p>
        <table>
            <tr>
                <th>Title</th>
                <th>Price (KES)</th>
                <th>Category</th>
                <th>Telegram Status</th>
                <th>Link</th>
            </tr>
    """
    for deal in active_deals:
        status = f"ID: {deal.telegram_message_id}" if deal.telegram_message_id else "Not Sent"
        html += f"""
            <tr>
                <td>{deal.title}</td>
                <td>{deal.current_price:,.0f}</td>
                <td>{deal.category or 'N/A'}</td>
                <td>{status}</td>
                <td><a href="{deal.url}" target="_blank">Visit Store</a></td>
            </tr>
        """
    html += """
        </table>
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)