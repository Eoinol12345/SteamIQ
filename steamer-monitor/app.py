"""
app.py — SteamIQ Full Flask Application
========================================
Routes:
  GET  /                  → dashboard
  GET  /api/races         → race + horse data
  GET  /api/radar         → 3-minute money radar
  GET  /api/heatmap       → steam heatmap
  GET  /api/profiles      → trainer & jockey profiles
  GET  /api/report        → daily steam report
  GET  /api/filters       → pro filters
  GET  /api/strategy      → strategy performance tracker
  GET  /api/backtest      → backtesting engine
  GET  /api/clusters      → steam clusters per race
  GET  /api/reversals     → drift reversal detections
  GET  /api/quality       → steam quality index summary
  GET  /api/timeline/<id> → price timeline for one horse
  POST /api/simulate      → force simulator tick
  POST /api/reset         → reseed database
"""

import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit

from models import db, Race, Horse, OddsHistory, DailySteamResult, StrategyResult

app = Flask(__name__)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"]        = f"sqlite:///{os.path.join(BASE_DIR, 'racing.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"]                     = os.environ.get("SECRET_KEY", "steamiq-dev-key")

db.init_app(app)

with app.app_context():
    db.create_all()


def scheduled_update():
    with app.app_context():
        try:
            from scraper import try_scrape
            success = try_scrape()
        except Exception as exc:
            print(f"[Scheduler] Scraper: {exc}")
            success = False
        if not success:
            try:
                from simulator import simulate_price_movement
                simulate_price_movement()
            except Exception as exc:
                print(f"[Scheduler] Simulator: {exc}")


scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scheduled_update, IntervalTrigger(seconds=60),
                  id="odds_update", replace_existing=True)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))


def get_races(limit=5):
    return Race.query.order_by(Race.race_time.asc()).limit(limit).all()


def summary(races):
    all_h   = [h for r in races for h in r.horses]
    return {
        "total_runners": len(all_h),
        "steamers":      sum(1 for h in all_h if h.status == "steam"),
        "drifters":      sum(1 for h in all_h if h.status == "drift"),
        "smart_money":   sum(1 for h in all_h if h.is_smart_money_alert),
        "volume_spikes": sum(1 for h in all_h if h.volume_spike),
        "top_edge":      round(max((h.edge_score for h in all_h), default=0)),
        "a_plus_count":  sum(1 for h in all_h if h.quality_index == "A+"),
        "reversals":     sum(1 for h in all_h if h.is_drift_reversal),
        "last_updated":  datetime.utcnow().strftime("%H:%M:%S"),
    }


# ── Core routes ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    races = get_races()
    return render_template("index.html", races=races, summary=summary(races))


@app.route("/api/races")
def api_races():
    races = get_races()
    return jsonify({"last_updated": datetime.utcnow().strftime("%H:%M:%S"),
                    "summary": summary(races),
                    "races":   [r.to_dict() for r in races]})


@app.route("/api/radar")
def api_radar():
    cutoff = datetime.utcnow() - timedelta(minutes=3)
    hot = (Horse.query.filter(Horse.last_updated_time >= cutoff,
                              Horse.edge_score >= 50)
           .order_by(Horse.edge_score.desc()).limit(10).all())
    return jsonify([{
        "name": h.name, "venue": h.race.venue,
        "race_time": h.race.race_time.strftime("%H:%M"),
        "opening_odds": h.opening_odds, "current_odds": round(h.current_odds, 2),
        "pct_drop": round(h.pct_drop, 1), "matched_volume": round(h.matched_volume or 0),
        "volume_5min": round(h.volume_5min or 0), "volume_spike": h.volume_spike,
        "edge_score": round(h.edge_score), "velocity": round(h.steam_velocity or 0, 2),
        "conf_score": round(h.conf_score or 0), "quality_index": h.quality_index,
        "is_fake_steam": h.is_fake_steam, "is_drift_reversal": h.is_drift_reversal,
        "minutes_to_off": h.race.minutes_to_off,
    } for h in hot])


@app.route("/api/heatmap")
def api_heatmap():
    races = get_races()
    result = []
    for race in races:
        runners = []
        for h in sorted(race.horses, key=lambda x: x.pct_drop, reverse=True):
            pct = h.pct_drop
            tier = ("hot" if pct >= 20 else "warm" if pct >= 10 else
                    "mild" if pct >= 3 else "drift" if pct <= -5 else "flat")
            runners.append({"name": h.name, "pct_drop": round(pct, 1), "tier": tier,
                            "edge": round(h.edge_score), "conf": round(h.conf_score or 0),
                            "quality": h.quality_index, "odds": round(h.current_odds, 2),
                            "is_fake": h.is_fake_steam, "is_reversal": h.is_drift_reversal})
        result.append({"venue": race.venue, "race_time": race.race_time.strftime("%H:%M"),
                       "cluster_count": race.steam_cluster_count, "runners": runners})
    return jsonify(result)


@app.route("/api/profiles")
def api_profiles():
    horses = Horse.query.all()
    trainers, jockeys = {}, {}
    for h in horses:
        if h.pct_drop < 5:
            continue
        for d, key in [(trainers, h.trainer or "Unknown"), (jockeys, h.jockey or "Unknown")]:
            if key not in d:
                d[key] = {"count": 0, "total_drop": 0, "total_edge": 0,
                          "total_conf": 0, "spikes": 0, "a_plus": 0}
            d[key]["count"]       += 1
            d[key]["total_drop"]  += h.pct_drop
            d[key]["total_edge"]  += h.edge_score
            d[key]["total_conf"]  += (h.conf_score or 0)
            d[key]["spikes"]      += 1 if h.volume_spike else 0
            d[key]["a_plus"]      += 1 if h.quality_index == "A+" else 0

    def build(d, extra_keys=None):
        rows = []
        for name, v in d.items():
            if v["count"] < 1:
                continue
            row = {"name": name, "steam_count": v["count"],
                   "avg_drop": round(v["total_drop"] / v["count"], 1),
                   "avg_edge": round(v["total_edge"] / v["count"], 1),
                   "avg_conf": round(v["total_conf"] / v["count"], 1),
                   "spike_count": v["spikes"], "a_plus_count": v["a_plus"]}
            rows.append(row)
        return sorted(rows, key=lambda x: x["avg_edge"], reverse=True)[:10]

    return jsonify({"trainers": build(trainers), "jockeys": build(jockeys)})


@app.route("/api/report")
def api_report():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    results = (DailySteamResult.query.filter_by(date=today)
               .order_by(DailySteamResult.edge_score.desc()).all())
    won = sum(1 for r in results if r.result == "won")
    placed = sum(1 for r in results if r.result == "placed")
    lost = sum(1 for r in results if r.result == "lost")
    return jsonify({
        "date": today,
        "summary": {"total": len(results), "won": won, "placed": placed, "lost": lost},
        "results": [{"horse": r.horse_name, "venue": r.venue, "race_time": r.race_time,
                     "opening_odds": r.opening_odds, "flagged_odds": r.flagged_odds,
                     "pct_drop": round(r.pct_drop, 1), "edge_score": round(r.edge_score),
                     "result": r.result} for r in results],
    })


@app.route("/api/filters")
def api_filters():
    min_drop   = float(request.args.get("min_drop", 0))
    min_edge   = float(request.args.get("min_edge", 0))
    min_conf   = float(request.args.get("min_conf", 0))
    spike_only = request.args.get("volume_spike", "false").lower() == "true"
    late_only  = request.args.get("late_only", "false").lower() == "true"
    quality    = request.args.get("quality", "")
    country    = request.args.get("country", "").upper()

    filtered = []
    for h in Horse.query.join(Race).all():
        if h.pct_drop < min_drop:                    continue
        if h.edge_score < min_edge:                  continue
        if (h.conf_score or 0) < min_conf:           continue
        if spike_only and not h.volume_spike:        continue
        if late_only and h.race.minutes_to_off > 20: continue
        if quality and h.quality_index != quality:   continue
        if country and h.race.country != country:    continue
        filtered.append({
            "name": h.name, "venue": h.race.venue,
            "race_time": h.race.race_time.strftime("%H:%M"),
            "country": h.race.country, "odds": round(h.current_odds, 2),
            "pct_drop": round(h.pct_drop, 1), "edge_score": round(h.edge_score),
            "conf_score": round(h.conf_score or 0), "quality_index": h.quality_index,
            "ev_score": round(h.ev_score or 0, 1), "volume": round(h.volume_5min or 0),
            "spike": h.volume_spike, "mins_to_off": h.race.minutes_to_off,
            "is_fake": h.is_fake_steam, "is_reversal": h.is_drift_reversal,
        })

    filtered.sort(key=lambda x: x["edge_score"], reverse=True)
    return jsonify(filtered)


# ── New routes ────────────────────────────────────────────────────────────

@app.route("/api/strategy")
def api_strategy():
    """
    Strategy Performance Tracker.
    Returns ROI, strike rate, profit, avg odds, max drawdown per tag.
    Optional ?tag= filter.
    """
    tag_filter = request.args.get("tag", "")
    query = StrategyResult.query
    if tag_filter:
        query = query.filter_by(strategy_tag=tag_filter)

    all_results = query.order_by(StrategyResult.timestamp.desc()).all()

    # Group by strategy tag
    tags = {}
    for r in all_results:
        t = r.strategy_tag
        if t not in tags:
            tags[t] = []
        tags[t].append(r)

    strategy_stats = []
    for tag, bets in tags.items():
        wins      = [b for b in bets if b.result == "win"]
        total     = len(bets)
        n_wins    = len(wins)
        profits   = [b.profit for b in bets]
        total_profit = round(sum(profits), 2)
        roi       = round((total_profit / total) * 100, 1) if total else 0
        strike    = round((n_wins / total) * 100, 1) if total else 0
        avg_odds  = round(sum(b.odds_taken for b in bets) / total, 2) if total else 0

        # Max drawdown — biggest losing streak in pts
        running = 0
        peak    = 0
        max_dd  = 0
        for p in profits:
            running += p
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd
        max_dd = round(max_dd, 2)

        strategy_stats.append({
            "tag":          tag,
            "bets":         total,
            "wins":         n_wins,
            "strike_rate":  strike,
            "roi":          roi,
            "total_profit": total_profit,
            "avg_odds":     avg_odds,
            "max_drawdown": max_dd,
        })

    strategy_stats.sort(key=lambda x: x["roi"], reverse=True)

    # Recent bets (last 20)
    recent = [{
        "horse": r.horse_name, "venue": r.venue, "race_time": r.race_time,
        "bet_type": r.bet_type, "odds": r.odds_taken, "result": r.result,
        "profit": r.profit, "tag": r.strategy_tag, "quality": r.quality_index,
        "time": r.timestamp.strftime("%H:%M"),
    } for r in all_results[:20]]

    return jsonify({"strategies": strategy_stats, "recent_bets": recent})


@app.route("/api/backtest")
def api_backtest():
    """
    Backtesting Engine.
    Query params:
      min_edge    (default 0)
      min_conf    (default 0)
      quality     (A+/A/B/C/D)
      volume_spike (bool)
      late_only   (bool)
      bet_type    (back/lay, default back)
    Simulates 1pt bets on all StrategyResults matching the rules.
    """
    min_edge   = float(request.args.get("min_edge", 0))
    min_conf   = float(request.args.get("min_conf", 0))
    quality    = request.args.get("quality", "")
    spike_only = request.args.get("volume_spike", "false").lower() == "true"
    bet_type   = request.args.get("bet_type", "back")

    results = StrategyResult.query.all()

    matched = []
    for r in results:
        if r.edge_score < min_edge:                  continue
        if quality and r.quality_index != quality:   continue
        matched.append(r)

    if not matched:
        return jsonify({
            "bets": 0, "wins": 0, "strike_rate": 0,
            "roi": 0, "total_profit": 0, "avg_odds": 0,
            "max_drawdown": 0, "profit_curve": [],
        })

    profits = [r.profit for r in matched]
    wins    = sum(1 for r in matched if r.result == "win")
    total   = len(matched)
    total_p = round(sum(profits), 2)
    roi     = round((total_p / total) * 100, 1) if total else 0
    strike  = round((wins / total) * 100, 1) if total else 0
    avg_o   = round(sum(r.odds_taken for r in matched) / total, 2) if total else 0

    # Profit curve (cumulative)
    curve   = []
    running = 0
    for r in matched:
        running += r.profit
        curve.append(round(running, 2))

    # Max drawdown
    peak = max_dd = running_peak = 0
    for p in profits:
        running_peak += p
        if running_peak > peak:
            peak = running_peak
        dd = peak - running_peak
        if dd > max_dd:
            max_dd = dd

    return jsonify({
        "bets":          total,
        "wins":          wins,
        "strike_rate":   strike,
        "roi":           roi,
        "total_profit":  total_p,
        "avg_odds":      avg_o,
        "max_drawdown":  round(max_dd, 2),
        "profit_curve":  curve,
        "rules_applied": {
            "min_edge": min_edge, "min_conf": min_conf,
            "quality": quality or "any", "volume_spike": spike_only,
        }
    })


@app.route("/api/clusters")
def api_clusters():
    """
    Steam Clusters — races where multiple horses are steaming simultaneously.
    Signals: wrong opening market, information leak, syndicate action.
    """
    races = get_races()
    clusters = []
    for race in races:
        steamers = [h for h in race.horses
                    if h.pct_drop >= 8 and h.edge_score >= 40 and not h.is_fake_steam]
        if len(steamers) < 2:
            continue
        clusters.append({
            "venue":       race.venue,
            "race_time":   race.race_time.strftime("%H:%M"),
            "country":     race.country,
            "minutes_to_off": race.minutes_to_off,
            "cluster_size": len(steamers),
            "signal":      ("🚨 SYNDICATE?" if len(steamers) >= 4 else
                            "⚠ INFO LEAK?" if len(steamers) == 3 else
                            "Wrong market"),
            "steamers": [{
                "name":       h.name,
                "pct_drop":   round(h.pct_drop, 1),
                "edge_score": round(h.edge_score),
                "conf":       round(h.conf_score or 0),
                "quality":    h.quality_index,
                "velocity":   round(h.steam_velocity or 0, 2),
            } for h in sorted(steamers, key=lambda x: x.edge_score, reverse=True)],
        })

    clusters.sort(key=lambda x: x["cluster_size"], reverse=True)
    return jsonify(clusters)


@app.route("/api/reversals")
def api_reversals():
    """
    Drift Reversal Detector — horses that first drifted, then steamed.
    Often real late money arriving after initial false market.
    """
    horses = Horse.query.filter_by(is_drift_reversal=True).all()
    return jsonify([{
        "name":        h.name,
        "venue":       h.race.venue,
        "race_time":   h.race.race_time.strftime("%H:%M"),
        "opening_odds": h.opening_odds,
        "current_odds": round(h.current_odds, 2),
        "pct_drop":    round(h.pct_drop, 1),
        "edge_score":  round(h.edge_score),
        "conf_score":  round(h.conf_score or 0),
        "quality":     h.quality_index,
        "velocity":    round(h.steam_velocity or 0, 2),
        "volume_spike": h.volume_spike,
        "minutes_to_off": h.race.minutes_to_off,
    } for h in sorted(horses, key=lambda x: x.edge_score, reverse=True)])


@app.route("/api/quality")
def api_quality():
    """Steam Quality Index summary — breakdown of grades across all horses."""
    horses = Horse.query.all()
    grades = {"A+": [], "A": [], "B": [], "C": [], "D": []}
    for h in horses:
        q = h.quality_index or "D"
        if q in grades:
            grades[q].append(h)

    result = {}
    for grade, hs in grades.items():
        if not hs:
            result[grade] = {"count": 0, "avg_edge": 0, "avg_conf": 0, "horses": []}
            continue
        result[grade] = {
            "count":    len(hs),
            "avg_edge": round(sum(h.edge_score for h in hs) / len(hs), 1),
            "avg_conf": round(sum(h.conf_score or 0 for h in hs) / len(hs), 1),
            "horses": [{
                "name":    h.name,
                "venue":   h.race.venue,
                "odds":    round(h.current_odds, 2),
                "pct_drop": round(h.pct_drop, 1),
                "edge":    round(h.edge_score),
                "conf":    round(h.conf_score or 0),
                "ev":      round(h.ev_score or 0, 1),
                "reversal": h.is_drift_reversal,
            } for h in sorted(hs, key=lambda x: x.edge_score, reverse=True)[:6]],
        }

    return jsonify(result)


@app.route("/api/timeline/<int:horse_id>")
def api_timeline(horse_id):
    """Full price timeline for a single horse."""
    horse = Horse.query.get_or_404(horse_id)
    return jsonify({
        "name":         horse.name,
        "opening_odds": horse.opening_odds,
        "current_odds": round(horse.current_odds, 2),
        "timeline":     horse.steam_timeline(),
    })


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    from simulator import simulate_price_movement
    simulate_price_movement()
    races = get_races()
    s     = summary(races)
    return jsonify({"status": "ok", "message": "Simulator tick complete.",
                    "summary": s, "races": [r.to_dict() for r in races]})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    from seed_db import seed
    seed()
    return jsonify({"status": "ok", "message": "Database re-seeded."})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
