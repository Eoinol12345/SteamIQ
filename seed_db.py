"""
seed_db.py
==========
Populates the SQLite database with 5 realistic UK/Irish race meetings
and a full field of runners per race, with randomised opening odds.

Run once before starting the app:
    python seed_db.py

Re-running drops all existing data and re-seeds (useful for UI testing).
"""

import random
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Race, Horse

# ── Seed data ─────────────────────────────────────────────────────────────

RACES = [
    {
        "venue":      "Cheltenham",
        "race_name":  "Neptune Novices' Hurdle (Grade 1)",
        "distance":   "2m5f",
        "race_class": "Grade 1",
        "going":      "Good to Soft",
        "country":    "GB",
        "offset_mins": 12,     # how many minutes from now the race goes off
        "horses": [
            {"name": "Galopin Des Champs",  "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 2.50},
            {"name": "Facile Vega",         "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 4.00},
            {"name": "Sir Gerhard",         "jockey": "R. Walsh",       "trainer": "W.P. Mullins",   "opening_odds": 6.00},
            {"name": "Constitution Hill",   "jockey": "N. Henderson",   "trainer": "N. Henderson",   "opening_odds": 7.00},
            {"name": "Mighty Potter",       "jockey": "J. Kennedy",     "trainer": "G. Elliott",     "opening_odds": 10.00},
            {"name": "Kilcruit",            "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 12.00},
            {"name": "Dysart Dynamo",       "jockey": "M. Walsh",       "trainer": "W.P. Mullins",   "opening_odds": 20.00},
            {"name": "Three Stripe Life",   "jockey": "D. Russell",     "trainer": "G. Elliott",     "opening_odds": 25.00},
        ],
    },
    {
        "venue":      "Leopardstown",
        "race_name":  "Leopardstown Handicap Chase",
        "distance":   "2m",
        "race_class": "Grade B Handicap",
        "going":      "Yielding",
        "country":    "IRE",
        "offset_mins": 34,
        "horses": [
            {"name": "Appreciate It",       "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 3.25},
            {"name": "Fils D'Oudairies",    "jockey": "M. Walsh",       "trainer": "J. Harrington",  "opening_odds": 5.50},
            {"name": "Blue Lord",           "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 6.00},
            {"name": "Ferny Hollow",        "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 8.00},
            {"name": "Riviere D'Etel",      "jockey": "R. Cleary",      "trainer": "W.P. Mullins",   "opening_odds": 11.00},
            {"name": "Stattler",            "jockey": "D. Russell",     "trainer": "G. Elliott",     "opening_odds": 14.00},
            {"name": "Latest Exhibition",   "jockey": "R. Blackmore",   "trainer": "P. Nolan",       "opening_odds": 17.00},
        ],
    },
    {
        "venue":      "Ascot",
        "race_name":  "Clarence House Chase (Grade 1)",
        "distance":   "1m7½f",
        "race_class": "Grade 1",
        "going":      "Good",
        "country":    "GB",
        "offset_mins": 55,
        "horses": [
            {"name": "Energumene",          "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 2.00},
            {"name": "Shishkin",            "jockey": "N. de Boinville","trainer": "N. Henderson",   "opening_odds": 3.50},
            {"name": "Edwardstone",         "jockey": "T. Cannon",      "trainer": "A. King",        "opening_odds": 6.00},
            {"name": "Nube Negra",          "jockey": "S. Twiston-Davies","trainer":"D. Skelton",    "opening_odds": 8.00},
            {"name": "Put The Kettle On",   "jockey": "A.E. Lynch",     "trainer": "H. de Bromhead", "opening_odds": 12.00},
            {"name": "Saint Calvados",      "jockey": "H. Cobden",      "trainer": "H. Whittington", "opening_odds": 15.00},
        ],
    },
    {
        "venue":      "Punchestown",
        "race_name":  "Punchestown Gold Cup (Grade 1)",
        "distance":   "3m1f",
        "race_class": "Grade 1",
        "going":      "Good to Yielding",
        "country":    "IRE",
        "offset_mins": 78,
        "horses": [
            {"name": "A Plus Tard",         "jockey": "R. Blackmore",   "trainer": "H. de Bromhead", "opening_odds": 2.25},
            {"name": "Minella Indo",        "jockey": "J.J. Slevin",    "trainer": "H. de Bromhead", "opening_odds": 5.00},
            {"name": "Galvin",              "jockey": "D. Russell",     "trainer": "G. Elliott",     "opening_odds": 6.00},
            {"name": "Al Boum Photo",       "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 7.00},
            {"name": "Tornado Flyer",       "jockey": "P. Townend",     "trainer": "W.P. Mullins",   "opening_odds": 9.00},
            {"name": "Clan Des Obeaux",     "jockey": "H. Cobden",      "trainer": "P. Nicholls",    "opening_odds": 10.00},
            {"name": "Protektorat",         "jockey": "T. Scudamore",   "trainer": "D. Skelton",     "opening_odds": 20.00},
        ],
    },
    {
        "venue":      "Newbury",
        "race_name":  "Betfair Hurdle (Handicap)",
        "distance":   "2m½f",
        "race_class": "Grade 3 Handicap",
        "going":      "Soft",
        "country":    "GB",
        "offset_mins": 102,
        "horses": [
            {"name": "Goshen",              "jockey": "J. Moore",       "trainer": "G. Moore",       "opening_odds": 4.50},
            {"name": "Angels Breath",       "jockey": "N. de Boinville","trainer": "N. Henderson",   "opening_odds": 6.00},
            {"name": "McFabulous",          "jockey": "H. Cobden",      "trainer": "P. Nicholls",    "opening_odds": 7.00},
            {"name": "Langer Dan",          "jockey": "C. Deutsch",     "trainer": "D. Skelton",     "opening_odds": 8.00},
            {"name": "Indefatigable",       "jockey": "R. Johnson",     "trainer": "P. Hobbs",       "opening_odds": 10.00},
            {"name": "Irish Prophecy",      "jockey": "D. Crosse",      "trainer": "W. Kennedy",     "opening_odds": 14.00},
            {"name": "Pentland Hills",      "jockey": "R. Thornton",    "trainer": "N. Henderson",   "opening_odds": 16.00},
            {"name": "Solo",                "jockey": "H. Skelton",     "trainer": "D. Skelton",     "opening_odds": 22.00},
        ],
    },
]


def _randomise_current_odds(opening: float) -> tuple[float, float]:
    """
    Return (previous_odds, current_odds) with some initial movement
    applied to make the dashboard immediately interesting on first load.
    """
    # 65% chance this horse has already been on the move
    if random.random() < 0.65:
        is_steam = random.random() < 0.60
        pct      = random.uniform(0.02, 0.20)
        if is_steam:
            current = round(opening * (1 - pct), 2)
        else:
            current = round(opening * (1 + pct), 2)
        current = max(1.05, min(100.0, current))
    else:
        current = opening

    # Derive a plausible previous value
    prev_pct = random.uniform(0.01, 0.05)
    previous = round(current * (1 + prev_pct if current < opening else 1 - prev_pct), 2)
    previous = max(1.05, min(100.0, previous))

    return previous, current


def seed():
    now = datetime.utcnow()

    with app.app_context():
        print("Dropping existing data…")
        db.drop_all()
        db.create_all()

        for race_data in RACES:
            race = Race(
                venue      = race_data["venue"],
                race_name  = race_data["race_name"],
                race_time  = now + timedelta(minutes=race_data["offset_mins"]),
                distance   = race_data["distance"],
                race_class = race_data["race_class"],
                going      = race_data["going"],
                country    = race_data["country"],
            )
            db.session.add(race)
            db.session.flush()   # get race.id before committing

            for h in race_data["horses"]:
                prev_odds, curr_odds = _randomise_current_odds(h["opening_odds"])
                horse = Horse(
                    race_id           = race.id,
                    name              = h["name"],
                    jockey            = h["jockey"],
                    trainer           = h["trainer"],
                    opening_odds      = h["opening_odds"],
                    previous_odds     = prev_odds,
                    current_odds      = curr_odds,
                    bookie_count      = random.randint(0, 5),
                    last_updated_time = now - timedelta(seconds=random.randint(0, 300)),
                )
                db.session.add(horse)

            print(f"  ✓ {race_data['venue']} — {len(race_data['horses'])} runners seeded")

        db.session.commit()
        print("\n✅ Database seeded successfully. Run `python app.py` to start.")


if __name__ == "__main__":
    seed()