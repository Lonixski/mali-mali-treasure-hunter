import os
import logging
from dotenv import load_dotenv

load_dotenv()

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from bs4 import BeautifulSoup
from database import SessionLocal, Deal, PriceSnapshot, Site

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- TELEGRAM FUNCTIONS ---
def send_telegram_deal(db, deal):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials missing. Skipping notification.")
        return

    tags = f"#{deal.category.replace(' ', '')} #MaliMali" if deal.category else "#MaliMali"
    text = f" *{deal.title}*\n💰 Price: KES {deal.current_price:,.0f}\n{tags}\n{deal.url}"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            deal.telegram_message_id = response.json()['result']['message_id']
            db.commit()
    except Exception as e:
        logger.error(f"Telegram send error: {str(e)}")


# --- SCRAPER LOGIC ---

def scrape_specific_site(site_id: int, db):
    """Scrapes a single site when the 'Refresh' button is clicked."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        logger.error(f"Site ID {site_id} not found.")
        return

    logger.info(f"🚀 Manual scrape triggered for: {site.name} ({site.url})")

    # CTO NOTE: This is where your BeautifulSoup logic will go.
    # For now, it safely runs without crashing so you can test the UI.
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (MaliMaliBot/1.0)'}
        response = requests.get(site.url, headers=headers, timeout=15)
        logger.info(f"Successfully fetched {site.name}. Status: {response.status_code}")

        # TODO: Add BeautifulSoup parsing here to find deals and call send_telegram_deal()

    except Exception as e:
        logger.error(f"Failed to scrape {site.name}: {str(e)}")


def run_scrape_and_notify():
    """Master job for the 30-minute scheduler."""
    logger.info("Starting scheduled scrape cycle...")
    db = SessionLocal()
    try:
        sites = db.query(Site).all()
        for site in sites:
            scrape_specific_site(site.id, db)
    except Exception as e:
        logger.error(f"Scheduled cycle failed: {str(e)}")
    finally:
        db.close()


def init_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=run_scrape_and_notify,
        trigger=IntervalTrigger(minutes=30),
        id="mali_mali_master_scraper",
        max_instances=1,
        misfire_grace_time=60,
        replace_existing=True
    )
    scheduler.start()
    logger.info("Scheduler initialized.")