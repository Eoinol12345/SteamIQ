"""
simulator.py
============
Randomises price movements on all horses in the database.
Called by the APScheduler background job every 60 seconds when the live
scraper is unavailable (i.e. in demo / development mode).

Design goals:
  - Roughly 60% of moves are steams (price shortens) to keep the
    dashboard interesting and generate Smart Money alerts over time.
  - A small number of horses are designated "movers" per tick; the rest
    stay flat so the dashboard doesn't update everything at once.
  - Bookie count is updated to reflect how many of our five simulated
    bookmakers are following the move.
"""

import random
from datetime import datetime
from models import db, Horse


# Realistic decimal odds boundaries
MIN_ODDS = 1.10
MAX_ODDS = 100.0

# Fraction of the field that actually moves each tick
MOVE_FRACTION = 0.40   # ~40% of runners get an update each tick

# Bias: 60% of moves are steamers (shortening), 40% drifts
STEAM_PROBABILITY = 0.62

# How big can a single tick move be (as a fraction of current odds)?
STEAM_MOVE_MIN   = 0.03   # 3%
STEAM_MOVE_MAX   = 0.18   # 18%
DRIFT_MOVE_MIN   = 0.02
DRIFT_MOVE_MAX   = 0.12


def _new_bookie_count(is_steam: bool) -> int:
    """
    Simulate how many bookmakers have made the same move.
    Steamers tend to be followed by more books simultaneously.
    """
    if is_steam:
        return random.choices([1, 2, 3, 4, 5], weights=[5, 15, 25, 30, 25])[0]
    else:
        return random.choices([1, 2, 3, 4, 5], weights=[35, 30, 20, 10, 5])[0]


def _clamp(value: float) -> float:
    return round(max(MIN_ODDS, min(MAX_ODDS, value)), 2)


def simulate_price_movement():
    """
    Main entry point — called by the scheduler.
    Selects a random subset of horses and moves their odds.
    """
    horses = Horse.query.all()
    if not horses:
        return

    # Decide which horses will move this tick
    n_movers = max(1, int(len(horses) * MOVE_FRACTION))
    movers = random.sample(horses, min(n_movers, len(horses)))

    now = datetime.utcnow()

    for horse in movers:
        is_steam = random.random() < STEAM_PROBABILITY

        if is_steam:
            pct = random.uniform(STEAM_MOVE_MIN, STEAM_MOVE_MAX)
            new_odds = horse.current_odds * (1 - pct)
        else:
            pct = random.uniform(DRIFT_MOVE_MIN, DRIFT_MOVE_MAX)
            new_odds = horse.current_odds * (1 + pct)

        new_odds = _clamp(new_odds)

        # Prevent odds going lower than 1.05 (near-certainty floor)
        new_odds = max(1.05, new_odds)

        horse.previous_odds = horse.current_odds
        horse.current_odds  = new_odds
        horse.bookie_count  = _new_bookie_count(is_steam)
        horse.last_updated_time = now

    db.session.commit()
    print(f"[Simulator] {now.strftime('%H:%M:%S')} — moved {len(movers)} horses.")