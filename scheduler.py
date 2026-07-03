import os
import logging
from dotenv import load_dotenv

load_dotenv()

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from database import SessionLocal, Deal, PriceSnapshot, Site

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- TELEGRAM FUNCTIONS ---

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Telegram not configured.")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            message_id = response.json()['result']['message_id']
            logger.info("📱 Telegram notification sent!")
            return message_id
        else:
            logger.error(f"❌ Telegram error: {response.text}")
    except Exception as e:
        logger.error(f"❌ Failed to send Telegram: {e}")
    return None


def extract_price_value(price_str: str) -> float:
    try:
        clean = price_str.replace('KSh', '').replace('KES', '').replace(',', '').strip()
        return float(clean)
    except:
        return 0.0


# --- SCRAPER LOGIC ---

def scrape_single_site(site_id: int, db):
    """Scrapes a single site using its CSS selectors."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        logger.error(f"Site ID {site_id} not found.")
        return 0, 0

    if not site.product_selector or not site.title_selector or not site.price_selector:
        logger.warning(f"⚠️ {site.name} is missing CSS selectors. Skipping.")
        return 0, 0

    logger.info(f"  🔍 Visiting: {site.name}...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    new_deals_count = 0
    price_drops_count = 0

    try:
        response = requests.get(site.url, headers=headers, timeout=15)

        if response.status_code != 200:
            logger.error(f"    ❌ Failed to connect to {site.name} (Status: {response.status_code})")
            return 0, 0

        soup = BeautifulSoup(response.text, 'html.parser')
        products = soup.select(site.product_selector)

        if not products:
            logger.warning(f"    ⚠️ No products found with selector: {site.product_selector}")
            return 0, 0

        for product in products[:10]:
            try:
                title_element = product.select_one(site.title_selector)
                title = title_element.text.strip() if title_element else "No Title"

                price_element = product.select_one(site.price_selector)
                price_str = price_element.text.strip() if price_element else "0"
                price_value = extract_price_value(price_str)

                link_element = product.select_one(site.link_selector) if site.link_selector else None
                raw_link = link_element['href'] if link_element else "#"

                if not raw_link.startswith('http'):
                    base_url = site.url.rstrip('/')
                    if raw_link.startswith('/'):
                        raw_link = raw_link[1:]
                    raw_link = f"{base_url}/{raw_link}"

                # Check if deal already exists
                existing_deal = db.query(Deal).filter(
                    Deal.site_id == site.id,
                    Deal.title == title
                ).first()

                if not existing_deal:
                    # NEW DEAL
                    new_deal = Deal(
                        site_id=site.id,
                        title=title,
                        url=raw_link,
                        current_price=price_value,
                        is_expired=False
                    )
                    db.add(new_deal)
                    db.commit()

                    # Send Telegram notification
                    message = f"""🔥 <b>NEW DEAL on {site.name}!</b>

🛍️ {title}
💰 KES {price_value:,.0f}
🔗 <a href="{raw_link}">View Deal</a>

⏰ {datetime.now().strftime('%H:%M')}"""

                    message_id = send_telegram_message(message)
                    if message_id:
                        new_deal.telegram_message_id = message_id
                        db.commit()

                    new_deals_count += 1

                else:
                    # EXISTING DEAL - Check for price changes
                    old_price = existing_deal.current_price

                    if old_price != price_value:
                        existing_deal.current_price = price_value
                        existing_deal.is_expired = False
                        existing_deal.updated_at = datetime.utcnow()

                        # Add price snapshot
                        snapshot = PriceSnapshot(deal_id=existing_deal.id, price=price_value)
                        db.add(snapshot)

                        price_drops_count += 1

                        if price_value < old_price and old_price > 0:
                            message = f"""💸 <b>PRICE DROP on {site.name}!</b>

🛍️ {title}
📉 Was: KES {old_price:,.0f}
✅ Now: KES {price_value:,.0f}
🔗 <a href="{raw_link}">View Deal</a>

⏰ {datetime.now().strftime('%H:%M')}"""
                            send_telegram_message(message)
                        else:
                            logger.info(f"    📈 Price increased: {old_price} → {price_value}")

                        db.commit()

            except Exception as e:
                logger.error(f"    ⚠️ Error extracting product: {e}")
                db.rollback()
                continue

    except Exception as e:
        logger.error(f"    ⚠️ Error scraping {site.name}: {e}")
        db.rollback()

    return new_deals_count, price_drops_count


def scrape_and_notify():
    """Master job for the scheduler."""
    logger.info(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] Running scheduled scrape...")

    db = SessionLocal()
    try:
        sites = db.query(Site).all()

        total_new = 0
        total_drops = 0

        for site in sites:
            try:
                new_count, drop_count = scrape_single_site(site.id, db)
                total_new += new_count
                total_drops += drop_count
            except Exception as e:
                logger.error(f"    ❌ Critical error on {site.name}: {e}")
                continue

        logger.info(f"✅ Scrape complete! {total_new} new deals, {total_drops} price changes.\n")

    except Exception as e:
        logger.error(f"❌ Error in scrape cycle: {e}")
    finally:
        db.close()


def init_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=scrape_and_notify,
        trigger=IntervalTrigger(minutes=30),
        id="mali_mali_master_scraper",
        max_instances=1,
        misfire_grace_time=60,
        replace_existing=True
    )
    scheduler.start()
    logger.info("🚀 Mali Mali scheduler started! Scraping every 30 minutes.")