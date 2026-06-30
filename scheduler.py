from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import threading
import time
from database import SessionLocal, Site, Deal, PriceSnapshot

TELEGRAM_BOT_TOKEN = "8336727259:AAFr9XngoYmy9RXXgXdsj101V2ubbj0j-0k"
TELEGRAM_CHAT_ID = "125601423"


def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram not configured.")
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
            print("📱 Telegram notification sent!")
        else:
            print(f"❌ Telegram error: {response.text}")
    except Exception as e:
        print(f"❌ Failed to send Telegram: {e}")


def extract_price_value(price_str: str) -> float:
    try:
        clean = price_str.replace('KSh', '').replace('KES', '').replace(',', '').strip()
        return float(clean)
    except:
        return 0.0


def scrape_single_site(site):
    print(f"  🔍 Visiting: {site.name}...")

    # More realistic browser headers to avoid blocking
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

    db = SessionLocal()

    # Try up to 3 times with increasing delays
    for attempt in range(3):
        try:
            response = requests.get(site.url, headers=headers, timeout=15)

            if response.status_code == 200:
                break
            elif response.status_code in [403, 429, 503]:
                print(f"    ⚠️ Attempt {attempt + 1}: Got {response.status_code}, waiting...")
                time.sleep(2 ** attempt)  # Wait 1s, 2s, 4s
                continue
            else:
                print(f"    ❌ Failed to connect to {site.name} (Status: {response.status_code})")
                return 0, 0
        except requests.exceptions.Timeout:
            print(f"    ⏱️ Attempt {attempt + 1}: Timeout, retrying...")
            time.sleep(2 ** attempt)
            continue
        except Exception as e:
            print(f"    ⚠️ Attempt {attempt + 1}: Error - {e}")
            time.sleep(2 ** attempt)
            continue
    else:
        print(f"    ❌ Failed after 3 attempts: {site.name}")
        return 0, 0

    try:
        soup = BeautifulSoup(response.text, 'html.parser')
        products = soup.select(site.product_selector)

        if not products:
            print(f"    ⚠️ No products found with selector: {site.product_selector}")
            return 0, 0

        for product in products[:10]:
            try:
                title_element = product.select_one(site.title_selector)
                title = title_element.text.strip() if title_element else "No Title"

                price_element = product.select_one(site.price_selector)
                price = price_element.text.strip() if price_element else "No Price"

                link_element = product.select_one(site.link_selector)
                raw_link = link_element['href'] if link_element else "#"

                if not raw_link.startswith('http'):
                    base_url = site.url.rstrip('/')
                    if raw_link.startswith('/'):
                        raw_link = raw_link[1:]
                    raw_link = f"{base_url}/{raw_link}"

                snapshot = PriceSnapshot(
                    store=site.name,
                    product=title,
                    price=price,
                    recorded_at=datetime.now().isoformat()
                )
                db.add(snapshot)

                existing_deal = db.query(Deal).filter(
                    Deal.store == site.name,
                    Deal.product == title
                ).first()

                if not existing_deal:
                    new_deal = Deal(
                        store=site.name,
                        product=title,
                        price=price,
                        link=raw_link,
                        discovered_at=datetime.now().isoformat(),
                        is_active=1
                    )
                    db.add(new_deal)
                    new_deals_count += 1

                    message = f"""🔥 <b>NEW DEAL on {site.name}!</b>

🛍️ {title}
💰 {price}
🔗 <a href="{raw_link}">View Deal</a>

⏰ {datetime.now().strftime('%H:%M')}"""
                    send_telegram_message(message)

                else:
                    old_price = existing_deal.price
                    if old_price != price:
                        old_value = extract_price_value(old_price)
                        new_value = extract_price_value(price)

                        existing_deal.price = price
                        existing_deal.is_active = 1
                        price_drops_count += 1

                        if new_value < old_value and old_value > 0:
                            message = f"""💸 <b>PRICE DROP on {site.name}!</b>

🛍️ {title}
📉 Was: {old_price}
✅ Now: {price}
🔗 <a href="{raw_link}">View Deal</a>

⏰ {datetime.now().strftime('%H:%M')}"""
                            send_telegram_message(message)
                        else:
                            print(f"    📈 Price increased: {old_price} → {price}")

            except Exception as e:
                print(f"    ⚠️ Error extracting product: {e}")
                continue

        db.commit()

    except Exception as e:
        print(f"    ⚠️ Error parsing {site.name}: {e}")
    finally:
        db.close()

    return new_deals_count, price_drops_count


def scrape_and_notify():
    print(f"\n⏰ [{datetime.now().strftime('%H:%M:%S')}] Running scheduled scrape...")

    db = SessionLocal()
    sites = db.query(Site).all()
    db.close()

    total_new = 0
    total_drops = 0

    for site in sites:
        try:
            new_count, drop_count = scrape_single_site(site)
            total_new += new_count
            total_drops += drop_count
        except Exception as e:
            print(f"    ❌ Critical error on {site.name}: {e}")
            continue

    print(f"✅ Scrape complete! {total_new} new deals, {total_drops} price changes.\n")


def scrape_in_background():
    thread = threading.Thread(target=scrape_and_notify, daemon=True)
    thread.start()
    return thread


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scrape_and_notify, 'date', run_date=datetime.now())
    scheduler.add_job(scrape_and_notify, 'interval', minutes=30, id='mali_scraper')
    scheduler.start()
    print("🚀 Mali Mali scheduler started! Scraping every 30 minutes.")