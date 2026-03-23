"""
scraper.py
==========
Attempts to scrape live UK/Irish race odds from a public-facing source.
Currently targets Racing Post race cards — these pages are largely server-
rendered, though some sections are JS-hydrated.  The function returns True
if it successfully updates the DB, False on any failure, in which case the
calling code falls back to the simulator.

─────────────────────────────────────────────────────────────────────────────
NOTE FOR PRODUCTION:
  Racing Post (and most modern betting sites) require a real browser to
  render the odds table.  To get fully live data you have two options:

  Option A — Selenium headless (reliable, heavier):
      pip install selenium webdriver-manager
      Then replace the requests.get() block below with the Selenium version
      shown in the comments at the bottom of this file.

  Option B — Betfair API / Oddschecker API (recommended for production):
      Free tiers are available. Plug the data into the same DB write block.
─────────────────────────────────────────────────────────────────────────────
"""

import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from models import db, Horse

# ── Rotating User-Agents ──────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

TARGET_URL = "https://www.racingpost.com/racecards/"

REQUEST_TIMEOUT = 10   # seconds


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control":   "no-cache",
        "Referer":         "https://www.google.com/",
    }


def _parse_decimal_odds(text: str) -> float | None:
    """Convert a fractional string like '9/4' or decimal '3.25' to float."""
    text = text.strip().replace(",", ".")
    try:
        if "/" in text:
            num, den = text.split("/")
            return round(float(num) / float(den) + 1, 2)
        return round(float(text), 2)
    except (ValueError, ZeroDivisionError):
        return None


def try_scrape() -> bool:
    """
    Attempt a live scrape of Racing Post race cards.

    Returns True  → odds updated in DB from live data.
    Returns False → scrape failed; caller should use simulator instead.
    """
    try:
        resp = requests.get(TARGET_URL, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Scraper] Request failed: {exc}")
        return False

    soup = BeautifulSoup(resp.text, "html.parser")

    # Racing Post serves most race card data via React hydration —
    # the static HTML rarely contains individual odds cells.
    # We look for the data-horse elements; if absent we bail gracefully.
    horse_cards = soup.select("[data-test-id='RC-runnerName']")
    if not horse_cards:
        print("[Scraper] No horse data found in static HTML — site likely JS-rendered.")
        return False

    updated = 0
    now     = datetime.utcnow()

    for card in horse_cards:
        name_el = card.select_one("[data-test-id='RC-runnerName']")
        odds_el = card.select_one("[data-test-id='RC-oddsButton-price']")

        if not name_el or not odds_el:
            continue

        horse_name  = name_el.get_text(strip=True)
        odds_text   = odds_el.get_text(strip=True)
        live_odds   = _parse_decimal_odds(odds_text)

        if live_odds is None:
            continue

        # Match against DB by name (case-insensitive)
        horse = Horse.query.filter(
            db.func.lower(Horse.name) == horse_name.lower()
        ).first()

        if horse:
            horse.previous_odds     = horse.current_odds
            horse.current_odds      = live_odds
            horse.bookie_count      = random.randint(1, 5)   # ← replace with real multi-bookie data
            horse.last_updated_time = now
            updated += 1

    if updated:
        db.session.commit()
        print(f"[Scraper] Updated {updated} horses from live data.")
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
#  SELENIUM VERSION (drop-in replacement for the requests block above)
#  Uncomment and install: pip install selenium webdriver-manager
# ─────────────────────────────────────────────────────────────────────────────
#
# from selenium import webdriver
# from selenium.webdriver.chrome.options import Options
# from selenium.webdriver.chrome.service import Service
# from webdriver_manager.chrome import ChromeDriverManager
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
#
# def _get_selenium_driver():
#     opts = Options()
#     opts.add_argument("--headless")
#     opts.add_argument("--no-sandbox")
#     opts.add_argument("--disable-dev-shm-usage")
#     opts.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
#     return webdriver.Chrome(
#         service=Service(ChromeDriverManager().install()), options=opts
#     )
#
# def try_scrape_selenium() -> bool:
#     driver = _get_selenium_driver()
#     try:
#         driver.get(TARGET_URL)
#         WebDriverWait(driver, 15).until(
#             EC.presence_of_element_located((By.CSS_SELECTOR, "[data-test-id='RC-runnerName']"))
#         )
#         soup = BeautifulSoup(driver.page_source, "html.parser")
#         # ... rest of parse logic above ...
#     finally:
#         driver.quit()