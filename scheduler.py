import os
import logging
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from bs4 import BeautifulSoup
from database import SessionLocal, Deal, PriceSnapshot, Site

# 1. Secure Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("FATAL: Telegram credentials missing in environment variables.")

# 2. Robust Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- TELEGRAM HELPER FUNCTIONS ---

def send_telegram_deal(db, deal):
    tags = f"#{deal.category.replace(' ', '')} #MaliMali" if deal.category else "#MaliMali"
    text = f"🔥 *{deal.title}*\n💰 Price: KES {deal.current_price:,.0f}\n{tags}\n{deal.url}"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            message_id = response.json()['result']['message_id']
            deal.telegram_message_id = message_id
            db.commit()
            logger.info(f"Sent deal: {deal.title} (Msg ID: {message_id})")
        else:
            logger.error(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        logger.error(f"Telegram send exception: {str(e)}")


def handle_expired_deal(db, deal):
    """Intelligently handles expired deals. Tries to delete, falls back to editing if >48h old."""
    if not deal.telegram_message_id:
        deal.is_expired = True
        db.commit()
        return

    # Strategy 1: Try to delete the message (Works if < 48 hours old)
    url_delete = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    payload_delete = {"chat_id": TELEGRAM_CHAT_ID, "message_id": deal.telegram_message_id}

    try:
        response = requests.post(url_delete, json=payload_delete, timeout=10)
        if response.status_code == 200:
            logger.info(f"Deleted expired deal post: {deal.title}")
            deal.telegram_message_id = None
            deal.is_expired = True
            db.commit()
            return
    except Exception as e:
        logger.error(f"Delete exception: {str(e)}")

    # Strategy 2: Fallback for messages > 48 hours old (Telegram API limitation)
    # We edit the message to show it is expired instead of deleting it.
    logger.info(f"Message >48h old or delete failed. Editing message to show EXPIRED for: {deal.title}")
    url_edit = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
    tags = f"#{deal.category.replace(' ', '')} #MaliMali" if deal.category else "#MaliMali"
    expired_text = f"❌ *DEAL EXPIRED / ENDED* ❌\n\n~{deal.title}~\n{tags}\n{deal.url}"

    payload_edit = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_id": deal.telegram_message_id,
        "text": expired_text,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url_edit, json=payload_edit, timeout=10)
        if response.status_code == 200:
            logger.info(f"Successfully edited expired post for: {deal.title}")
        else:
            logger.warning(f"Failed to edit expired post: {response.text}")
    except Exception as e:
        logger.error(f"Edit exception: {str(e)}")

    deal.telegram_message_id = None
    deal.is_expired = True
    db.commit()


# --- SCRAPER LOGIC ---

def check_and_expire_deals(db):
    """Checks all active deals to see if they are still valid."""
    active_deals = db.query(Deal).filter(Deal.is_expired == False).all()

    for deal in active_deals:
        try:
            # CTO NOTE: Replace this mock logic with your actual BeautifulSoup logic.
            # We check if the URL returns a 404 or if the price changed.
            headers = {'User-Agent': 'Mozilla/5.0 (MaliMaliBot/1.0)'}
            response = requests.get(deal.url, headers=headers, timeout=15)

            is_gone = False

            if response.status_code == 404:
                is_gone = True
            else:
                # TODO: Parse HTML to check if "Out of Stock" is present, or if price increased.
                soup = BeautifulSoup(response.text, 'html.parser')
                # Example logic:
                # out_of_stock_elem = soup.find(class_='out-of-stock')
                # if out_of_stock_elem: is_gone = True

            if is_gone:
                logger.info(f"Deal expired: {deal.title}")
                handle_expired_deal(db, deal)

        except Exception as e:
            logger.error(f"Error checking deal {deal.title}: {str(e)}")


def scrape_new_deals(db):
    """Scrapes sites for new deals."""
    sites = db.query(Site).all()
    for site in sites:
        logger.info(f"Scraping {site.name}...")
        # TODO: Implement your BeautifulSoup scraping logic here.
        # When a new deal is found:
        # new_deal = Deal(site_id=site.id, title="...", url="...", current_price=100.0, category="Electronics")
        # db.add(new_deal)
        # db.commit()
        # send_telegram_deal(db, new_deal)
        pass


def run_scrape_and_notify():
    """Master job function executed by APScheduler."""
    logger.info("Starting Mali Mali Master Scrape Cycle...")
    db = SessionLocal()
    try:
        # 1. Clean up dead links first
        check_and_expire_deals(db)
        # 2. Scrape for new deals
        scrape_new_deals(db)
    except Exception as e:
        logger.error(f"Master scrape cycle failed: {str(e)}")
    finally:
        db.close()
    logger.info("Mali Mali Master Scrape Cycle Complete.")


# --- SCHEDULER INITIALIZATION ---

def init_scheduler():
    scheduler = BackgroundScheduler()
    trigger = IntervalTrigger(minutes=30)

    scheduler.add_job(
        func=run_scrape_and_notify,
        trigger=trigger,
        id="mali_mali_master_scraper",
        max_instances=1,  # Prevents overlapping scrapes
        misfire_grace_time=60,  # Handles brief Render restarts gracefully
        replace_existing=True
    )

    scheduler.start()
    logger.info("Mali Mali Scheduler initialized with resilience protocols.")