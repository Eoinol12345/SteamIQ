"""
simulator.py — SteamIQ Full Intelligence Engine
================================================
Generates per tick:
  Odds, volume, velocity, weight of money, edge score (existing)
  + Confidence Score     — is this steam legit or noise?
  + Quality Index        — A+/A/B/C/D grade per horse
  + EV Score             — expected value vs opening odds
  + Drift Reversal       — horse drifted then steamed
  + Price Stability      — how erratic has the price been?
  + Spread Width         — back/lay spread
  + Steam Clusters       — multiple steamers in same race
  + StrategyResult       — auto-records qualifying bets
"""

import json
import random
import statistics
from datetime import datetime, timedelta
from models import db, Horse, OddsHistory, DailySteamResult, StrategyResult

# ── Constants ──────────────────────────────────────────────────────────────
MIN_ODDS      = 1.05
MAX_ODDS      = 100.0
MOVE_FRACTION = 0.40
STEAM_PROB    = 0.62
STEAM_MIN     = 0.03
STEAM_MAX     = 0.18
DRIFT_MIN     = 0.02
DRIFT_MAX     = 0.12
BASE_VOL_MIN  = 5_000
BASE_VOL_MAX  = 80_000


def _clamp(v):
    return round(max(MIN_ODDS, min(MAX_ODDS, v)), 2)


def _bookie_count(is_steam):
    if is_steam:
        return random.choices([1,2,3,4,5], weights=[5,15,25,30,25])[0]
    return random.choices([1,2,3,4,5], weights=[35,30,20,10,5])[0]


def _market_depth(current_odds):
    step = round(random.uniform(0.1, 0.3), 1)
    back = [{"odds": round(current_odds - step*(i+1), 1),
             "volume": random.randint(2000, 30000)} for i in range(3)
            if current_odds - step*(i+1) > 1.01]
    lay  = [{"odds": round(current_odds + step*(i+1), 1),
             "volume": random.randint(500, 8000)} for i in range(3)]
    return {"back": back, "lay": lay}


def _velocity(horse, new_odds, now):
    cutoff = now - timedelta(minutes=5)
    recent = [h for h in horse.history if h.timestamp >= cutoff]
    if not recent:
        return 0.0
    elapsed = max(0.5, (now - recent[0].timestamp).total_seconds() / 60)
    return round(abs(recent[0].odds - new_odds) / elapsed, 3)


def _price_stability(horse):
    """100 = rock solid, lower = erratic. Based on std dev of recent history."""
    odds_vals = [h.odds for h in horse.history[-8:]]
    if len(odds_vals) < 2:
        return 100.0
    try:
        std = statistics.stdev(odds_vals)
        mean = statistics.mean(odds_vals)
        cv = (std / mean) * 100 if mean else 0
        return round(max(0, 100 - cv * 10), 1)
    except Exception:
        return 100.0


def _spread_width(depth):
    """Difference between best lay and best back price."""
    try:
        best_back = max(b["odds"] for b in depth.get("back", []))
        best_lay  = min(l["odds"] for l in depth.get("lay", []))
        return round(best_lay - best_back, 2)
    except Exception:
        return 0.0


def _is_drift_reversal(horse, is_steam, new_odds):
    """
    Returns True if the horse previously drifted (went up) but is
    now steaming. Classic late money signal.
    """
    if not is_steam:
        return False
    if len(horse.history) < 3:
        return False
    recent = [h.odds for h in horse.history[-5:]]
    # Check if there was an upward move followed by downward
    peak = max(recent)
    return peak > horse.opening_odds * 1.05 and new_odds < peak * 0.92


def _edge_score(horse, is_steam, velocity, vol_spike, back_pct, pct_drop, now):
    if not is_steam:
        return max(0, (horse.edge_score or 0) * 0.8)
    score = 0.0
    score += min(25, pct_drop * 1.25)
    score += min(20, velocity * 40)
    if vol_spike:
        score += 20
    elif (horse.volume_5min or 0) > 10_000:
        score += 10
    score += (horse.bookie_count / 5) * 15
    if back_pct > 70:   score += 12
    elif back_pct > 55: score += 6
    mins = max(0, int((horse.race.race_time - now).total_seconds() / 60))
    if mins <= 5:    score += 8
    elif mins <= 15: score += 5
    elif mins <= 30: score += 2
    return round(min(100, score), 1)


def _confidence_score(horse, is_steam, velocity, vol_spike, back_pct,
                      pct_drop, stability, spread, bookie_count, now):
    """
    Steam Confidence Score — answers: is this steam legit or noise?
    Different weights to edge score; focuses on signal quality.

    Factors:
      price stability   → 20 pts  (stable price = more credible steam)
      volume backing    → 20 pts  (money must follow the move)
      spread width      → 15 pts  (tight spread = healthy market)
      bookie consensus  → 15 pts  (more books = more credible)
      velocity          → 15 pts  (fast but not instant = real)
      time to post      → 10 pts  (late = more informed)
      back pressure     →  5 pts  (back heavy = bullish market)
    """
    if not is_steam or pct_drop < 3:
        return max(0, (horse.conf_score or 0) * 0.75)

    score = 0.0

    # 1. Price stability (max 20) — stable price = credible steam
    score += (stability / 100) * 20

    # 2. Volume (max 20) — money must be behind the move
    vol = horse.volume_5min or 0
    if vol_spike:
        score += 20
    elif vol > 20_000:
        score += 15
    elif vol > 8_000:
        score += 8

    # 3. Spread width (max 15) — tight = liquid = credible
    if spread < 0.2:    score += 15
    elif spread < 0.4:  score += 10
    elif spread < 0.8:  score += 5

    # 4. Bookie consensus (max 15)
    score += (bookie_count / 5) * 15

    # 5. Velocity (max 15) — moderate velocity is ideal
    if 0.1 <= velocity <= 0.5:  score += 15  # controlled, real
    elif velocity > 0.5:        score += 8   # too fast = possible spike
    elif velocity > 0.05:       score += 5

    # 6. Time to post (max 10) — late = informed
    mins = max(0, int((horse.race.race_time - now).total_seconds() / 60))
    if mins <= 5:    score += 10
    elif mins <= 15: score += 7
    elif mins <= 30: score += 3

    # 7. Back pressure (max 5)
    if back_pct > 70: score += 5
    elif back_pct > 55: score += 2

    return round(min(100, score), 1)


def _quality_index(edge, confidence, vol_spike, is_fake, is_reversal):
    """
    Steam Quality Index — combines edge + confidence into a grade.
    A+ = elite signal, D = noise/ignore
    """
    if is_fake:
        return "D"
    combined = (edge * 0.55) + (confidence * 0.45)
    bonus = 0
    if vol_spike:    bonus += 8
    if is_reversal:  bonus += 5
    total = combined + bonus
    if total >= 85:  return "A+"
    if total >= 70:  return "A"
    if total >= 55:  return "B"
    if total >= 35:  return "C"
    return "D"


def _ev_score(horse, current_odds):
    """
    Expected Value vs opening odds.
    EV = ((current / opening) - 1) * 100
    Positive = you're getting better than opening price.
    """
    if not horse.opening_odds or horse.opening_odds == 0:
        return 0.0
    return round(((current_odds / horse.opening_odds) - 1) * 100, 1)


def _fake_steam(horse, is_steam, vol_5min, pct_drop):
    if not is_steam:
        return False
    return ((pct_drop > 5 and vol_5min < 2000) or
            (horse.bookie_count <= 1 and pct_drop > 8) or
            (horse.previous_odds is not None and
             horse.previous_odds < horse.current_odds and pct_drop > 5))


def _sentiment(back_pct, vol_spike, is_steam):
    if is_steam and back_pct > 65 and vol_spike: return "bullish"
    if is_steam and back_pct > 55:               return "bullish"
    if not is_steam and back_pct < 40:           return "bearish"
    return "neutral"


def _record_strategy_result(horse, quality, edge, now):
    """
    Auto-record a StrategyResult for qualifying horses.
    Simulates a 1pt back bet with randomised outcome weighted by quality.
    """
    if quality not in ("A+", "A"):
        return
    if (horse.current_odds or 0) < 1.5:
        return

    # Win probability skewed by quality and edge
    win_prob = {"A+": 0.38, "A": 0.30}.get(quality, 0.22)
    outcome  = "win" if random.random() < win_prob else "loss"
    odds     = round(horse.current_odds, 2)
    profit   = round(odds - 1, 2) if outcome == "win" else -1.0

    # Tag this result to multiple strategies for comparison
    tags = ["all_bets"]
    if edge >= 70:                tags.append("edge_70")
    if quality == "A+":           tags.append("quality_A_plus")
    if horse.volume_spike:        tags.append("volume_spike")
    if horse.is_drift_reversal:   tags.append("drift_reversal")

    for tag in tags:
        existing = StrategyResult.query.filter(
            StrategyResult.horse_name == horse.name,
            StrategyResult.strategy_tag == tag,
            StrategyResult.timestamp >= now - timedelta(hours=2)
        ).first()
        if not existing:
            db.session.add(StrategyResult(
                horse_name    = horse.name,
                venue         = horse.race.venue,
                race_time     = horse.race.race_time.strftime("%H:%M"),
                bet_type      = "back",
                odds_taken    = odds,
                stake         = 1.0,
                result        = outcome,
                profit        = profit,
                strategy_tag  = tag,
                edge_score    = edge,
                quality_index = quality,
                timestamp     = now,
            ))


def _maybe_daily_alert(horse, now):
    if (horse.edge_score or 0) >= 60 and horse.is_smart_money_alert:
        today = now.strftime("%Y-%m-%d")
        if not DailySteamResult.query.filter_by(horse_name=horse.name, date=today).first():
            db.session.add(DailySteamResult(
                date=today, horse_name=horse.name,
                venue=horse.race.venue,
                race_time=horse.race.race_time.strftime("%H:%M"),
                opening_odds=horse.opening_odds,
                flagged_odds=horse.current_odds,
                pct_drop=horse.pct_drop, edge_score=horse.edge_score,
                result="pending",
            ))


# ── Main ───────────────────────────────────────────────────────────────────

def simulate_price_movement():
    horses = Horse.query.all()
    if not horses:
        return

    n_movers      = max(1, int(len(horses) * MOVE_FRACTION))
    movers        = random.sample(horses, min(n_movers, len(horses)))
    now           = datetime.utcnow()
    spike_race_id = (random.choice([h.race_id for h in movers])
                     if random.random() < 0.25 else None)

    for horse in movers:
        is_steam = random.random() < STEAM_PROB

        # ── Odds ──────────────────────────────────────────────────────
        if is_steam:
            new_odds = _clamp(horse.current_odds * (1 - random.uniform(STEAM_MIN, STEAM_MAX)))
        else:
            new_odds = _clamp(horse.current_odds * (1 + random.uniform(DRIFT_MIN, DRIFT_MAX)))
        new_odds = max(1.05, new_odds)

        # ── Volume ────────────────────────────────────────────────────
        is_spike = horse.race_id == spike_race_id and is_steam
        base_vol = random.uniform(BASE_VOL_MIN, BASE_VOL_MAX)
        vol_5min = round(base_vol * (random.uniform(4, 12) if is_spike
                                     else random.uniform(0.5, 2)))
        total_vol = round((horse.matched_volume or 0) + vol_5min)

        # ── Calculations ──────────────────────────────────────────────
        velocity  = _velocity(horse, new_odds, now)
        back_pct  = random.uniform(58, 88) if is_steam else random.uniform(25, 48)
        depth     = _market_depth(new_odds)
        bookie_ct = _bookie_count(is_steam)
        pct_drop  = max(0, (horse.opening_odds - new_odds) / horse.opening_odds * 100
                        if horse.opening_odds else 0)
        stability = _price_stability(horse)
        spread    = _spread_width(depth)
        reversal  = _is_drift_reversal(horse, is_steam, new_odds)
        fake      = _fake_steam(horse, is_steam, vol_5min, pct_drop)
        edge      = _edge_score(horse, is_steam, velocity, is_spike,
                                back_pct, pct_drop, now)
        conf      = _confidence_score(horse, is_steam, velocity, is_spike,
                                      back_pct, pct_drop, stability, spread,
                                      bookie_ct, now)
        quality   = _quality_index(edge, conf, is_spike, fake, reversal)
        ev        = _ev_score(horse, new_odds)
        sent      = _sentiment(back_pct, is_spike, is_steam)

        # ── Write ──────────────────────────────────────────────────────
        horse.previous_odds     = horse.current_odds
        horse.current_odds      = new_odds
        horse.bookie_count      = bookie_ct
        horse.matched_volume    = total_vol
        horse.volume_5min       = vol_5min
        horse.volume_spike      = is_spike
        horse.back_pct          = round(back_pct, 1)
        horse.steam_velocity    = velocity
        horse.edge_score        = edge
        horse.is_fake_steam     = fake
        horse.sentiment         = sent
        horse.market_depth_json = json.dumps(depth)
        horse.conf_score        = conf
        horse.quality_index     = quality
        horse.ev_score          = ev
        horse.is_drift_reversal = reversal
        horse.price_stability   = stability
        horse.spread_width      = spread
        horse.last_updated_time = now

        db.session.add(OddsHistory(
            horse_id=horse.id, odds=new_odds, volume=vol_5min, timestamp=now))

        _maybe_daily_alert(horse, now)
        _record_strategy_result(horse, quality, edge, now)

    db.session.commit()
    print(f"[Simulator] {now.strftime('%H:%M:%S')} — moved {len(movers)} horses.")
