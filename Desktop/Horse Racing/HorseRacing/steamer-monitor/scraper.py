"""
scraper.py — Betfair Exchange Live Scraper
==========================================
Uses direct HTTP requests to the Betfair API.
No SSL certificates required. Works on Mac, Linux, and Render.

Set these in your .env file or Render environment variables:
  BETFAIR_APP_KEY  = VzkuojquWnflpREV
  BETFAIR_USERNAME = your Betfair email
  BETFAIR_PASSWORD = your Betfair password
"""

import os
import json
import requests
import statistics
from datetime import datetime, timedelta
from models import db, Race, Horse, OddsHistory, DailySteamResult, StrategyResult

APP_KEY  = os.environ.get("BETFAIR_APP_KEY",  "VzkuojquWnflpREV")
USERNAME = os.environ.get("BETFAIR_USERNAME", "")
PASSWORD = os.environ.get("BETFAIR_PASSWORD", "")

BETTING_URL = "https://api.betfair.com/exchange/betting/rest/v1.0/"
HORSE_RACING_EVENT_TYPE = "7"

_session_token = None
_token_expiry  = None


# ── Auth ──────────────────────────────────────────────────────────────────

def _login():
    """
    Login using Betfair's non-certificate endpoint.
    Works without SSL client certificates.
    """
    global _session_token, _token_expiry

    if _session_token and _token_expiry and datetime.utcnow() < _token_expiry:
        return _session_token

    if not USERNAME or not PASSWORD:
        print("[Scraper] BETFAIR_USERNAME / BETFAIR_PASSWORD not set in environment.")
        return None

    # Try the standard non-certificate endpoint first
    endpoints = [
        "https://identitysso.betfair.com/api/login",
        "https://identitysso-cert.betfair.com/api/login",
    ]

    for url in endpoints:
        try:
            resp = requests.post(
                url,
                data={"username": USERNAME, "password": PASSWORD},
                headers={
                    "X-Application":  APP_KEY,
                    "Content-Type":   "application/x-www-form-urlencoded",
                    "Accept":         "application/json",
                },
                timeout=15,
            )

            # Check we got JSON back
            if not resp.text or resp.text.strip().startswith("<"):
                print(f"[Scraper] {url} returned HTML — trying next endpoint.")
                continue

            data = resp.json()

            if data.get("status") == "SUCCESS" and data.get("token"):
                _session_token = data["token"]
                _token_expiry  = datetime.utcnow() + timedelta(hours=3, minutes=30)
                print(f"[Scraper] Betfair login OK via {url}")
                return _session_token

            error = data.get("error", "unknown")
            print(f"[Scraper] Login failed at {url}: {error}")

        except requests.exceptions.RequestException as e:
            print(f"[Scraper] Request error at {url}: {e}")
        except Exception as e:
            print(f"[Scraper] Error at {url}: {e}")

    print("[Scraper] All login endpoints failed.")
    return None


def _api(token, method, params):
    """Make a Betfair Exchange API call."""
    try:
        resp = requests.post(
            BETTING_URL + method + "/",
            headers={
                "X-Application":    APP_KEY,
                "X-Authentication": token,
                "Content-Type":     "application/json",
                "Accept":           "application/json",
            },
            json=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[Scraper] API error ({method}): {e}")
        return None


# ── Market fetching ───────────────────────────────────────────────────────

def _get_markets(token):
    now    = datetime.utcnow()
    cutoff = now + timedelta(hours=5)
    return _api(token, "listMarketCatalogue", {
        "filter": {
            "eventTypeIds":    ["7"],
            "marketCountries": ["GB", "IE"],
            "marketTypeCodes": ["WIN"],
            "marketStartTime": {
                "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to":   cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        },
        "marketProjection": [
            "MARKET_START_TIME",
            "RUNNER_DESCRIPTION",
            "EVENT",
            "RUNNER_METADATA",
            "MARKET_DESCRIPTION",
        ],
        "maxResults": "5",
        "sort": "FIRST_TO_START",
        "locale": "en"
    }) or []

def _get_books(token, market_ids):
    if not market_ids:
        return []
    return _api(token, "listMarketBook", {
        "marketIds": market_ids,
        "priceProjection": {
            "priceData": ["EX_BEST_OFFERS", "EX_TRADED"],
            "virtualise": False,
        },
    }) or []


# ── Intelligence calculations ─────────────────────────────────────────────

def _velocity(horse, new_odds, now):
    cutoff = now - timedelta(minutes=5)
    recent = [h for h in horse.history if h.timestamp >= cutoff]
    if not recent:
        return 0.0
    elapsed = max(0.5, (now - recent[0].timestamp).total_seconds() / 60)
    return round(abs(recent[0].odds - new_odds) / elapsed, 3)


def _stability(horse):
    vals = [h.odds for h in horse.history[-8:]]
    if len(vals) < 2:
        return 100.0
    try:
        cv = (statistics.stdev(vals) / statistics.mean(vals)) * 100
        return round(max(0, 100 - cv * 10), 1)
    except Exception:
        return 100.0


def _edge(horse, is_steam, vel, spike, back_pct, pct_drop, now):
    if not is_steam:
        return max(0, (horse.edge_score or 0) * 0.8)
    s  = min(25, pct_drop * 1.25) + min(20, vel * 40)
    s += 20 if spike else (10 if (horse.volume_5min or 0) > 10_000 else 0)
    s += ((horse.bookie_count or 1) / 5) * 15
    s += 12 if back_pct > 70 else (6 if back_pct > 55 else 0)
    mins = max(0, int((horse.race.race_time - now).total_seconds() / 60))
    s += 8 if mins <= 5 else (5 if mins <= 15 else (2 if mins <= 30 else 0))
    return round(min(100, s), 1)


def _confidence(horse, is_steam, vel, spike, back_pct, pct_drop,
                stab, spread, bookie_ct, now):
    if not is_steam or pct_drop < 3:
        return max(0, (horse.conf_score or 0) * 0.75)
    s  = (stab / 100) * 20
    vol = horse.volume_5min or 0
    s += 20 if spike else (15 if vol > 20_000 else (8 if vol > 8_000 else 0))
    s += 15 if spread < 0.2 else (10 if spread < 0.4 else (5 if spread < 0.8 else 0))
    s += (bookie_ct / 5) * 15
    s += 15 if 0.1 <= vel <= 0.5 else (8 if vel > 0.5 else (5 if vel > 0.05 else 0))
    mins = max(0, int((horse.race.race_time - now).total_seconds() / 60))
    s += 10 if mins <= 5 else (7 if mins <= 15 else (3 if mins <= 30 else 0))
    s += 5 if back_pct > 70 else (2 if back_pct > 55 else 0)
    return round(min(100, s), 1)


def _quality(edge_s, conf_s, spike, fake, reversal):
    if fake:
        return "D"
    t = edge_s * 0.55 + conf_s * 0.45 + (8 if spike else 0) + (5 if reversal else 0)
    return "A+" if t >= 85 else "A" if t >= 70 else "B" if t >= 55 else "C" if t >= 35 else "D"


def _ev(horse, current_odds):
    if not horse.opening_odds:
        return 0.0
    return round(((current_odds / horse.opening_odds) - 1) * 100, 1)


def _drift_reversal(horse, is_steam, new_odds):
    if not is_steam or len(horse.history) < 3:
        return False
    recent = [h.odds for h in horse.history[-5:]]
    peak   = max(recent)
    return peak > horse.opening_odds * 1.05 and new_odds < peak * 0.92


def _fake_steam(horse, is_steam, vol_5min, pct_drop):
    if not is_steam:
        return False
    return ((pct_drop > 5 and vol_5min < 2000) or
            ((horse.bookie_count or 1) <= 1 and pct_drop > 8) or
            (horse.previous_odds is not None and
             horse.previous_odds < horse.current_odds and pct_drop > 5))


def _record_strategy(horse, quality, edge_s, now):
    """
    Record a flagged horse in StrategyResult with result='pending'.
    The settler will update this to 'win' or 'loss' once the race finishes.
    Only records A+ and A grade horses — the ones worth tracking.
    """
    if quality not in ("A+", "A") or (horse.current_odds or 0) < 1.5:
        return
    odds = round(horse.current_odds, 2)
    tags = ["all_bets"]
    if edge_s >= 70:             tags.append("edge_70")
    if quality == "A+":          tags.append("quality_A_plus")
    if horse.volume_spike:       tags.append("volume_spike")
    if horse.is_drift_reversal:  tags.append("drift_reversal")
    for tag in tags:
        if not StrategyResult.query.filter(
            StrategyResult.horse_name == horse.name,
            StrategyResult.strategy_tag == tag,
            StrategyResult.timestamp >= now - timedelta(hours=2)
        ).first():
            db.session.add(StrategyResult(
                horse_name    = horse.name,
                venue         = horse.race.venue,
                race_time     = horse.race.race_time.strftime("%H:%M"),
                bet_type      = "back",
                odds_taken    = odds,
                stake         = 1.0,
                result        = "pending",   # settler updates this to win/loss
                profit        = 0.0,         # settler updates this too
                strategy_tag  = tag,
                edge_score    = edge_s,
                quality_index = quality,
                timestamp     = now,
            ))


def _record_alert(horse, now):
    if (horse.edge_score or 0) >= 60 and horse.is_smart_money_alert:
        today = now.strftime("%Y-%m-%d")
        if not DailySteamResult.query.filter_by(horse_name=horse.name, date=today).first():
            db.session.add(DailySteamResult(
                date=today, horse_name=horse.name, venue=horse.race.venue,
                race_time=horse.race.race_time.strftime("%H:%M"),
                opening_odds=horse.opening_odds, flagged_odds=horse.current_odds,
                pct_drop=horse.pct_drop, edge_score=horse.edge_score,
                result="pending"))


# ── Upsert helpers ────────────────────────────────────────────────────────

def _upsert_race(cat):
    """Create or update a Race from a Betfair market catalogue dict."""
    try:
        market_id  = cat.get("marketId")
        event      = cat.get("event", {})
        desc       = cat.get("description", {})
        start_str  = cat.get("marketStartTime")

        if not market_id or not start_str:
            return None

        # Parse ISO 8601 start time
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                rt = datetime.strptime(start_str, fmt)
                break
            except ValueError:
                continue
        else:
            return None

        # Skip finished races
        if rt < datetime.utcnow() - timedelta(minutes=5):
            return None

        country_code = event.get("countryCode", "GB")
        country      = "IRE" if country_code == "IE" else "GB"
        venue        = event.get("venue") or event.get("name", "Unknown")

        race = Race.query.filter_by(betfair_market_id=market_id).first()
        if race is None:
            race = Race(
                betfair_market_id = market_id,
                venue             = venue,
                race_name         = cat.get("marketName", "Race"),
                race_time         = rt,
                distance          = desc.get("distance", "") if desc else "",
                race_class        = desc.get("raceClass", "") if desc else "",
                going             = desc.get("going", "") if desc else "",
                country           = country,
            )
            db.session.add(race)
            db.session.flush()
            print(f"[Scraper] New race: {venue} {rt.strftime('%H:%M')}")
        else:
            if desc:
                race.going = desc.get("going", race.going or "")
            race.race_time = rt

        return race

    except Exception as e:
        print(f"[Scraper] _upsert_race error: {e}")
        return None


def _upsert_horse(race, runner, book_runner, now):
    """Create or update a Horse from Betfair runner dicts."""
    try:
        sel_id = runner.get("selectionId")
        name   = runner.get("runnerName", "Unknown")
        meta   = runner.get("metadata", {}) or {}

        if not sel_id:
            return None

        best_back = best_lay = None
        vol_total = back_size = lay_size = 0.0

        if book_runner:
            ex    = book_runner.get("ex", {})
            backs = ex.get("availableToBack", [])
            lays  = ex.get("availableToLay",  [])
            if backs:
                best_back = float(backs[0].get("price", 0))
                back_size = float(backs[0].get("size",  0))
            if lays:
                best_lay  = float(lays[0].get("price", 0))
                lay_size  = float(lays[0].get("size",  0))
            vol_total = float(book_runner.get("totalMatched", 0) or 0)

        if not best_back or best_back <= 1.0:
            return None

        current_odds = round(best_back, 2)
        total_wom    = (back_size + lay_size) or 1
        back_pct     = round((back_size / total_wom) * 100, 1)
        spread       = round(best_lay - best_back, 2) if best_lay else 0.0

        # Market depth
        ex_data = (book_runner or {}).get("ex", {})
        backs_d = ex_data.get("availableToBack", [])[:3]
        lays_d  = ex_data.get("availableToLay",  [])[:3]
        depth   = {
            "back": [{"odds": b.get("price", 0), "volume": b.get("size", 0)} for b in backs_d],
            "lay":  [{"odds": l.get("price", 0), "volume": l.get("size", 0)} for l in lays_d],
        }

        jockey  = meta.get("JOCKEY_NAME",  "") if isinstance(meta, dict) else ""
        trainer = meta.get("TRAINER_NAME", "") if isinstance(meta, dict) else ""

        horse = Horse.query.filter_by(
            race_id=race.id, betfair_selection_id=sel_id).first()

        if horse is None:
            horse = Horse(
                race_id              = race.id,
                betfair_selection_id = sel_id,
                name                 = name,
                jockey               = jockey,
                trainer              = trainer,
                opening_odds         = current_odds,
                previous_odds        = current_odds,
                current_odds         = current_odds,
                matched_volume       = vol_total,
                volume_5min          = 0.0,
                back_pct             = back_pct,
                spread_width         = spread,
                market_depth_json    = json.dumps(depth),
                last_updated_time    = now,
            )
            db.session.add(horse)
            db.session.flush()
            db.session.add(OddsHistory(
                horse_id=horse.id, odds=current_odds, volume=0, timestamp=now))
            return horse

        # Update existing horse
        prev_vol = horse.matched_volume or 0
        vol_5min = max(0.0, vol_total - prev_vol)
        is_spike = vol_5min > 50_000
        is_steam = current_odds < (horse.current_odds or current_odds) - 0.01
        pct_drop = max(0, (horse.opening_odds - current_odds) / horse.opening_odds * 100
                       if horse.opening_odds else 0)

        vel    = _velocity(horse, current_odds, now)
        stab   = _stability(horse)
        rev    = _drift_reversal(horse, is_steam, current_odds)
        fake   = _fake_steam(horse, is_steam, vol_5min, pct_drop)
        bk_ct  = min(5, len(backs_d) + 1)
        edge_s = _edge(horse, is_steam, vel, is_spike, back_pct, pct_drop, now)
        conf_s = _confidence(horse, is_steam, vel, is_spike, back_pct,
                             pct_drop, stab, spread, bk_ct, now)
        qual   = _quality(edge_s, conf_s, is_spike, fake, rev)
        ev_s   = _ev(horse, current_odds)
        sent   = ("bullish" if is_steam and back_pct > 65
                  else "bearish" if not is_steam and back_pct < 40
                  else "neutral")

        horse.previous_odds      = horse.current_odds
        horse.current_odds       = current_odds
        horse.matched_volume     = vol_total
        horse.volume_5min        = vol_5min
        horse.volume_spike       = is_spike
        horse.back_pct           = back_pct
        horse.steam_velocity     = vel
        horse.bookie_count       = bk_ct
        horse.edge_score         = edge_s
        horse.conf_score         = conf_s
        horse.quality_index      = qual
        horse.ev_score           = ev_s
        horse.is_fake_steam      = fake
        horse.is_drift_reversal  = rev
        horse.price_stability    = stab
        horse.spread_width       = spread
        horse.sentiment          = sent
        horse.market_depth_json  = json.dumps(depth)
        horse.exchange_price     = current_odds
        horse.exchange_lead_score = min(100, edge_s * 0.6 + conf_s * 0.4)
        horse.exchange_behavior  = ("LEADING"   if edge_s >= 70
                                    else "DIVERGING" if fake
                                    else "FOLLOWING")
        horse.price_divergence   = spread
        horse.last_updated_time  = now
        if jockey  and not horse.jockey:  horse.jockey  = jockey
        if trainer and not horse.trainer: horse.trainer = trainer

        db.session.add(OddsHistory(
            horse_id=horse.id, odds=current_odds, volume=vol_5min, timestamp=now))
        _record_alert(horse, now)
        _record_strategy(horse, qual, edge_s, now)
        return horse

    except Exception as e:
        print(f"[Scraper] _upsert_horse error: {e}")
        return None


# ── Cleanup ───────────────────────────────────────────────────────────────

def _get_settled_book(token, market_id):
    """Fetch the final market book for a finished race to find the winner."""
    return _api(token, "listMarketBook", {
        "marketIds": [market_id],
        "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
        "orderProjection": "ALL",
        "matchProjection": "NO_ROLLUP",
    }) or []


def _settle_race(token, race):
    """
    Check if a race has finished on Betfair and update results.
    Called for races that have passed their start time but haven't been settled yet.
    Returns True if successfully settled.
    """
    try:
        if not race.betfair_market_id:
            return False

        books = _get_settled_book(token, race.betfair_market_id)
        if not books:
            return False

        book       = books[0]
        status     = book.get("status", "")
        runners    = book.get("runners", [])

        # Market must be CLOSED to have a result
        if status not in ("CLOSED", "SETTLED"):
            return False

        # Find the winner — Betfair marks them with status WINNER
        winner_ids = {
            r["selectionId"]
            for r in runners
            if r.get("status") == "WINNER"
        }

        if not winner_ids:
            return False

        now   = datetime.utcnow()
        today = now.strftime("%Y-%m-%d")

        print(f"[Settler] Settling {race.venue} {race.race_time.strftime('%H:%M')} "
              f"— {len(winner_ids)} winner(s) found.")

        # ── Update DailySteamResult records ──────────────────────────────
        flagged = DailySteamResult.query.filter_by(
            date=today, venue=race.venue,
            race_time=race.race_time.strftime("%H:%M")
        ).all()

        for alert in flagged:
            if alert.result != "pending":
                continue  # already settled
            # Find the matching horse in this race
            horse = next(
                (h for h in race.horses if h.name == alert.horse_name),
                None
            )
            if horse and horse.betfair_selection_id in winner_ids:
                alert.result = "won"
                print(f"[Settler] ✅ WON  — {alert.horse_name} "
                      f"(Edge {alert.edge_score:.0f})")
            elif horse:
                alert.result = "lost"
                print(f"[Settler] ❌ LOST — {alert.horse_name} "
                      f"(Edge {alert.edge_score:.0f})")
            else:
                alert.result = "lost"

        # ── Update StrategyResult records ─────────────────────────────────
        strategy_rows = StrategyResult.query.filter(
            StrategyResult.venue     == race.venue,
            StrategyResult.race_time == race.race_time.strftime("%H:%M"),
            StrategyResult.result    == "pending",
        ).all()

        for row in strategy_rows:
            horse = next(
                (h for h in race.horses if h.name == row.horse_name),
                None
            )
            if horse and horse.betfair_selection_id in winner_ids:
                row.result = "win"
                row.profit = round(row.odds_taken - 1, 2)
            else:
                row.result = "loss"
                row.profit = -1.0

        return True

    except Exception as e:
        print(f"[Settler] Error settling {race.venue}: {e}")
        return False


def _settle_finished_races(token):
    """
    Find all races that have passed their start time, fetch results from
    Betfair, and update every flagged horse with the real outcome.
    Runs as part of every scrape cycle.
    """
    now     = datetime.utcnow()
    # Races that started in the last 60 minutes but haven't been deleted yet
    cutoff_start = now - timedelta(minutes=60)
    cutoff_end   = now - timedelta(minutes=2)  # give 2 mins after off time

    finished = Race.query.filter(
        Race.race_time >= cutoff_start,
        Race.race_time <= cutoff_end,
        Race.betfair_market_id.isnot(None),
    ).all()

    if not finished:
        return

    settled_count = 0
    for race in finished:
        if _settle_race(token, race):
            settled_count += 1

    if settled_count:
        print(f"[Settler] {settled_count} race(s) settled with real results.")


def _clear_past_races():
    """Remove races that finished more than 60 minutes ago."""
    cutoff = datetime.utcnow() - timedelta(minutes=60)
    old    = Race.query.filter(Race.race_time < cutoff).all()
    for r in old:
        db.session.delete(r)
    if old:
        print(f"[Scraper] Removed {len(old)} finished race(s).")


# ── Main ──────────────────────────────────────────────────────────────────

def try_scrape() -> bool:
    """
    Attempt a live Betfair scrape using direct HTTP requests.
    Returns True  → success (even if no races right now).
    Returns False → login failed.

    Each cycle:
      1. Settle any races that finished in the last 60 mins (real results)
      2. Fetch upcoming markets and update live odds
      3. Clean up old races from the DB
    """
    token = _login()
    if not token:
        return False

    # ── Step 1: Settle finished races first ───────────────────────────────
    _settle_finished_races(token)

    # ── Step 2: Fetch upcoming markets ───────────────────────────────────
    catalogues = _get_markets(token)

    if not catalogues:
        print("[Scraper] No upcoming UK/IE races in the next 5 hours.")
        _clear_past_races()
        db.session.commit()
        return True

    market_ids = [c["marketId"] for c in catalogues]
    books      = _get_books(token, market_ids)
    book_map   = {b["marketId"]: b for b in (books or [])}

    now     = datetime.utcnow()
    updated = 0

    for cat in catalogues:
        race = _upsert_race(cat)
        if not race:
            continue
        book_runners = {
            r["selectionId"]: r
            for r in book_map.get(cat["marketId"], {}).get("runners", [])
        }
        for runner in cat.get("runners", []):
            h = _upsert_horse(
                race, runner,
                book_runners.get(runner.get("selectionId")),
                now)
            if h:
                updated += 1

    # ── Step 3: Clean up old races ────────────────────────────────────────
    _clear_past_races()
    db.session.commit()
    print(f"[Scraper] {now.strftime('%H:%M:%S')} — {updated} runners "
          f"across {len(catalogues)} markets.")
    return True