"""
seed_db.py — SteamIQ Table Initialiser
========================================
Creates all database tables on startup.
Does NOT insert any fake data — all race and horse data
comes from the live Betfair API via scraper.py.

Called in the Render build command:
  pip install -r requirements.txt && python seed_db.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db


def seed():
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("✅ Tables ready. Betfair scraper will populate data on first run.")


if __name__ == "__main__":
    seed()
