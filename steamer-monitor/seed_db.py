"""
seed_db.py — SteamIQ Full Seeder
==================================
Seeds races, runners, OddsHistory, DailySteamResult, and StrategyResult
so all tabs (including Strategy and Backtest) show real data on first load.
"""

import json
import random
import sys
import os
import statistics
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, Race, Horse, OddsHistory, DailySteamResult, StrategyResult

RACES = [
    {
        "venue": "Cheltenham", "race_name": "Neptune Novices' Hurdle (Grade 1)",
        "distance": "2m5f", "race_class": "Grade 1", "going": "Good to Soft",
        "country": "GB", "offset_mins": 12,
        "horses": [
            {"name": "Galopin Des Champs",  "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 2.50},
            {"name": "Facile Vega",         "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 4.00},
            {"name": "Sir Gerhard",         "jockey": "R. Walsh",        "trainer": "W.P. Mullins",  "opening_odds": 6.00},
            {"name": "Constitution Hill",   "jockey": "N. Henderson",    "trainer": "N. Henderson",  "opening_odds": 7.00},
            {"name": "Mighty Potter",       "jockey": "J. Kennedy",      "trainer": "G. Elliott",    "opening_odds": 10.00},
            {"name": "Kilcruit",            "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 12.00},
            {"name": "Dysart Dynamo",       "jockey": "M. Walsh",        "trainer": "W.P. Mullins",  "opening_odds": 20.00},
            {"name": "Three Stripe Life",   "jockey": "D. Russell",      "trainer": "G. Elliott",    "opening_odds": 25.00},
        ],
    },
    {
        "venue": "Leopardstown", "race_name": "Leopardstown Handicap Chase",
        "distance": "2m", "race_class": "Grade B Handicap", "going": "Yielding",
        "country": "IRE", "offset_mins": 34,
        "horses": [
            {"name": "Appreciate It",       "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 3.25},
            {"name": "Fils D'Oudairies",    "jockey": "M. Walsh",        "trainer": "J. Harrington", "opening_odds": 5.50},
            {"name": "Blue Lord",           "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 6.00},
            {"name": "Ferny Hollow",        "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 8.00},
            {"name": "Riviere D'Etel",      "jockey": "R. Cleary",       "trainer": "W.P. Mullins",  "opening_odds": 11.00},
            {"name": "Stattler",            "jockey": "D. Russell",      "trainer": "G. Elliott",    "opening_odds": 14.00},
            {"name": "Latest Exhibition",   "jockey": "R. Blackmore",    "trainer": "P. Nolan",      "opening_odds": 17.00},
        ],
    },
    {
        "venue": "Ascot", "race_name": "Clarence House Chase (Grade 1)",
        "distance": "1m7½f", "race_class": "Grade 1", "going": "Good",
        "country": "GB", "offset_mins": 55,
        "horses": [
            {"name": "Energumene",          "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 2.00},
            {"name": "Shishkin",            "jockey": "N. de Boinville", "trainer": "N. Henderson",  "opening_odds": 3.50},
            {"name": "Edwardstone",         "jockey": "T. Cannon",       "trainer": "A. King",       "opening_odds": 6.00},
            {"name": "Nube Negra",          "jockey": "S. Twiston-Davies","trainer": "D. Skelton",   "opening_odds": 8.00},
            {"name": "Put The Kettle On",   "jockey": "A.E. Lynch",      "trainer": "H. de Bromhead","opening_odds": 12.00},
            {"name": "Saint Calvados",      "jockey": "H. Cobden",       "trainer": "H. Whittington","opening_odds": 15.00},
        ],
    },
    {
        "venue": "Punchestown", "race_name": "Punchestown Gold Cup (Grade 1)",
        "distance": "3m1f", "race_class": "Grade 1", "going": "Good to Yielding",
        "country": "IRE", "offset_mins": 78,
        "horses": [
            {"name": "A Plus Tard",         "jockey": "R. Blackmore",    "trainer": "H. de Bromhead","opening_odds": 2.25},
            {"name": "Minella Indo",        "jockey": "J.J. Slevin",     "trainer": "H. de Bromhead","opening_odds": 5.00},
            {"name": "Galvin",              "jockey": "D. Russell",      "trainer": "G. Elliott",    "opening_odds": 6.00},
            {"name": "Al Boum Photo",       "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 7.00},
            {"name": "Tornado Flyer",       "jockey": "P. Townend",      "trainer": "W.P. Mullins",  "opening_odds": 9.00},
            {"name": "Clan Des Obeaux",     "jockey": "H. Cobden",       "trainer": "P. Nicholls",   "opening_odds": 10.00},
            {"name": "Protektorat",         "jockey": "T. Scudamore",    "trainer": "D. Skelton",    "opening_odds": 20.00},
        ],
    },
    {
        "venue": "Newbury", "race_name": "Betfair Hurdle (Handicap)",
        "distance": "2m½f", "race_class": "Grade 3 Handicap", "going": "Soft",
        "country": "GB", "offset_mins": 102,
        "horses": [
            {"name": "Goshen",              "jockey": "J. Moore",        "trainer": "G. Moore",      "opening_odds": 4.50},
            {"name": "Angels Breath",       "jockey": "N. de Boinville", "trainer": "N. Henderson",  "opening_odds": 6.00},
            {"name": "McFabulous",          "jockey": "H. Cobden",       "trainer": "P. Nicholls",   "opening_odds": 7.00},
            {"name": "Langer Dan",          "jockey": "C. Deutsch",      "trainer": "D. Skelton",    "opening_odds": 8.00},
            {"name": "Indefatigable",       "jockey": "R. Johnson",      "trainer": "P. Hobbs",      "opening_odds": 10.00},
            {"name": "Irish Prophecy",      "jockey": "D. Crosse",       "trainer": "W. Kennedy",    "opening_odds": 14.00},
            {"name": "Pentland Hills",      "jockey": "R. Thornton",     "trainer": "N. Henderson",  "opening_odds": 16.00},
            {"name": "Solo",                "jockey": "H. Skelton",      "trainer": "D. Skelton",    "opening_odds": 22.00},
        ],
    },
]


def _history(horse_id, opening, current, now, n=12):
    for i in range(n):
        frac = i / max(1, n - 1)
        noise = random.uniform(-0.15, 0.15)
        odds = max(1.05, round(opening + (current - opening) * frac + noise, 2))
        ts = now - timedelta(minutes=(n - i) * 5)
        db.session.add(OddsHistory(
            horse_id=horse_id, odds=odds,
            volume=random.randint(1000, 15000), timestamp=ts))


def _daily_report(now):
    today = now.strftime("%Y-%m-%d")
    rows = [
        ("Thunder Road",  "Cheltenham",   "14:20", 8.5,  5.2,  38.8, 81, "won"),
        ("Silver Crest",  "Ascot",        "15:05", 12.0, 7.5,  37.5, 74, "placed"),
        ("Royal Fury",    "Leopardstown", "13:45", 9.0,  6.8,  24.4, 68, "won"),
        ("Dark Alliance", "Newbury",      "16:30", 15.0, 9.5,  36.7, 62, "lost"),
        ("Morning Dew",   "Punchestown",  "14:55", 6.0,  4.2,  30.0, 58, "placed"),
        ("Stellar Run",   "Cheltenham",   "13:10", 20.0, 11.0, 45.0, 88, "won"),
    ]
    for nm, venue, rt, op, fl, pct, edge, result in rows:
        db.session.add(DailySteamResult(
            date=today, horse_name=nm, venue=venue, race_time=rt,
            opening_odds=op, flagged_odds=fl, pct_drop=pct,
            edge_score=edge, result=result,
            created_at=now - timedelta(hours=random.randint(1, 5))))


def _strategy_results(now):
    """
    Seed ~80 historical strategy results across multiple tags so the
    Strategy and Backtest tabs are populated immediately.
    """
    horses_pool = [
        ("Thunder Road", "Cheltenham", "14:20"),
        ("Silver Crest", "Ascot", "15:05"),
        ("Royal Fury", "Leopardstown", "13:45"),
        ("Dark Alliance", "Newbury", "16:30"),
        ("Morning Dew", "Punchestown", "14:55"),
        ("Stellar Run", "Cheltenham", "13:10"),
        ("Bright Star", "Ascot", "16:00"),
        ("Iron Duke", "Newbury", "14:45"),
        ("Night Watch", "Cheltenham", "15:30"),
        ("True Grit", "Leopardstown", "14:10"),
    ]
    tags = ["all_bets", "edge_70", "quality_A_plus", "volume_spike", "drift_reversal"]
    quality_pool = ["A+", "A+", "A", "A", "B"]

    for i in range(80):
        horse_name, venue, rt = random.choice(horses_pool)
        tag = random.choice(tags)
        quality = random.choice(quality_pool)
        odds = round(random.uniform(2.5, 12.0), 2)

        # Win probability by quality
        win_prob = {"A+": 0.38, "A": 0.30, "B": 0.22}.get(quality, 0.18)
        outcome = "win" if random.random() < win_prob else "loss"
        profit  = round(odds - 1, 2) if outcome == "win" else -1.0
        edge    = random.uniform(55, 95) if quality in ("A+", "A") else random.uniform(30, 65)

        db.session.add(StrategyResult(
            horse_name    = horse_name,
            venue         = venue,
            race_time     = rt,
            bet_type      = "back",
            odds_taken    = odds,
            stake         = 1.0,
            result        = outcome,
            profit        = profit,
            strategy_tag  = tag,
            edge_score    = round(edge, 1),
            quality_index = quality,
            timestamp     = now - timedelta(hours=random.randint(0, 72)),
        ))


def seed():
    now = datetime.utcnow()

    with app.app_context():
        print("Dropping existing data…")
        db.drop_all()
        db.create_all()

        for race_data in RACES:
            race = Race(
                venue=race_data["venue"], race_name=race_data["race_name"],
                race_time=now + timedelta(minutes=race_data["offset_mins"]),
                distance=race_data["distance"], race_class=race_data["race_class"],
                going=race_data["going"], country=race_data["country"],
            )
            db.session.add(race)
            db.session.flush()

            for h in race_data["horses"]:
                opening  = h["opening_odds"]
                is_steam = random.random() < 0.65
                pct      = random.uniform(0.02, 0.25)
                current  = round(opening * (1 - pct) if is_steam
                                 else opening * (1 + pct * 0.5), 2)
                current  = max(1.05, min(100.0, current))
                previous = round(current * (1 + 0.03 if is_steam else 1 - 0.02), 2)
                back_pct = random.uniform(58, 85) if is_steam else random.uniform(28, 48)
                vol      = random.randint(8000, 120000)
                vol5     = random.randint(2000, 20000)
                spike    = random.random() < 0.15
                bookie   = random.randint(1, 5)
                velocity = random.uniform(0.05, 0.8) if is_steam else 0.0
                pct_drop = max(0, (opening - current) / opening * 100)
                stability = random.uniform(60, 100)
                spread    = random.uniform(0.1, 0.6)
                reversal  = random.random() < 0.12 and is_steam

                edge = min(100, (
                    min(25, pct_drop * 1.25) + min(20, velocity * 40) +
                    (20 if spike else 0) + (bookie / 5) * 15 +
                    (12 if back_pct > 70 else 6 if back_pct > 55 else 0) +
                    random.uniform(0, 8)
                )) if is_steam else random.uniform(0, 30)

                conf = min(100, (
                    (stability / 100) * 20 +
                    (20 if spike else 12 if vol5 > 20000 else 6 if vol5 > 8000 else 0) +
                    (15 if spread < 0.2 else 10 if spread < 0.4 else 5) +
                    (bookie / 5) * 15 +
                    min(15, velocity * 30) +
                    random.uniform(0, 10)
                )) if is_steam else random.uniform(0, 25)

                fake = is_steam and vol5 < 2000 and bookie <= 1

                def quality_from(e, c, sp, fk, rv):
                    if fk: return "D"
                    tot = e * 0.55 + c * 0.45 + (8 if sp else 0) + (5 if rv else 0)
                    if tot >= 85: return "A+"
                    if tot >= 70: return "A"
                    if tot >= 55: return "B"
                    if tot >= 35: return "C"
                    return "D"

                quality = quality_from(edge, conf, spike, fake, reversal)
                ev = round(((current / opening) - 1) * 100, 1)
                sent = ("bullish" if is_steam and back_pct > 65
                        else "bearish" if not is_steam and back_pct < 40
                        else "neutral")

                depth = {
                    "back": [{"odds": round(current - 0.2*(i+1), 1),
                               "volume": random.randint(2000, 25000)} for i in range(3)],
                    "lay":  [{"odds": round(current + 0.2*(i+1), 1),
                               "volume": random.randint(500, 8000)} for i in range(3)]
                }

                horse = Horse(
                    race_id=race.id, name=h["name"],
                    jockey=h["jockey"], trainer=h["trainer"],
                    opening_odds=opening, previous_odds=previous, current_odds=current,
                    matched_volume=vol, volume_5min=vol5, volume_spike=spike,
                    back_pct=round(back_pct, 1), steam_velocity=round(velocity, 3),
                    bookie_count=bookie, edge_score=round(edge, 1),
                    is_fake_steam=fake, sentiment=sent,
                    market_depth_json=json.dumps(depth),
                    conf_score=round(conf, 1), quality_index=quality,
                    ev_score=ev, is_drift_reversal=reversal,
                    price_stability=round(stability, 1), spread_width=round(spread, 2),
                    last_updated_time=now - timedelta(seconds=random.randint(0, 300)),
                )
                db.session.add(horse)
                db.session.flush()
                _history(horse.id, opening, current, now)

            print(f"  ✓ {race_data['venue']} — {len(race_data['horses'])} runners")

        _daily_report(now)
        _strategy_results(now)
        db.session.commit()
        print("\n✅ SteamIQ database seeded. Run `python app.py` to start.")


if __name__ == "__main__":
    seed()
