"""scraper.py — Falls back to simulator until Betfair API is connected."""
def try_scrape() -> bool:
    print("[Scraper] No live source configured — using simulator.")
    return False
