"""
app.py
======
Main Flask application for the Late Steamer Monitor.

Architecture:
  • APScheduler fires every 60 seconds on a background thread.
  • Each tick: try a live scrape → if it fails, run the price simulator.
  • GET /          → server-rendered dashboard (Jinja2, initial data)
  • GET /api/races → JSON endpoint polled by the frontend every 30 s
  • POST /api/simulate → force a simulator tick (dev tool, no auth needed
                         in dev; remove or protect in production)
"""

import os
from datetime import datetime

from flask import Flask, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit

from models import db, Race, Horse

# ── App factory ───────────────────────────────────────────────────────────

app = Flask(__name__)

# SQLite stored in instance/ folder (Render-safe, persists across restarts
# on a persistent disk; for truly ephemeral deployments swap for Postgres)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"]        = f"sqlite:///{os.path.join(BASE_DIR, 'racing.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"]                     = os.environ.get("SECRET_KEY", "dev-secret-change-me")

db.init_app(app)

with app.app_context():
    db.create_all()


# ── Background scheduler ──────────────────────────────────────────────────

def scheduled_update():
    """
    Runs every 60 seconds.  Tries the live scraper first; falls back to
    the price movement simulator if scraping fails (e.g. JS-rendered page,
    bot block, network error).
    """
    with app.app_context():
        try:
            from scraper import try_scrape
            success = try_scrape()
        except Exception as exc:
            print(f"[Scheduler] Scraper raised: {exc}")
            success = False

        if not success:
            try:
                from simulator import simulate_price_movement
                simulate_price_movement()
            except Exception as exc:
                print(f"[Scheduler] Simulator raised: {exc}")


scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    func     = scheduled_update,
    trigger  = IntervalTrigger(seconds=60),
    id       = "odds_update",
    name     = "Update odds every 60 seconds",
    replace_existing=True,
)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))


# ── Helpers ───────────────────────────────────────────────────────────────

def get_upcoming_races(limit: int = 5):
    """Return races ordered by race_time, nearest first."""
    return (
        Race.query
        .order_by(Race.race_time.asc())
        .limit(limit)
        .all()
    )

def dashboard_summary(races):
    """Aggregate numbers for the top stats bar."""
    all_horses   = [h for r in races for h in r.horses]
    steamers     = [h for h in all_horses if h.status == "steam"]
    drifters     = [h for h in all_horses if h.status == "drift"]
    smart_money  = [h for h in all_horses if h.is_smart_money_alert]
    return {
        "total_runners":   len(all_horses),
        "steamers":        len(steamers),
        "drifters":        len(drifters),
        "smart_money":     len(smart_money),
        "last_updated":    datetime.utcnow().strftime("%H:%M:%S"),
    }


# ── Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    races   = get_upcoming_races()
    summary = dashboard_summary(races)
    return render_template("index.html", races=races, summary=summary)


@app.route("/api/races")
def api_races():
    """
    JSON endpoint — polled by the frontend JS every 30 seconds.
    Returns full race + horse data including all calculated fields.
    """
    races   = get_upcoming_races()
    summary = dashboard_summary(races)
    return jsonify({
        "last_updated": datetime.utcnow().strftime("%H:%M:%S"),
        "summary":      summary,
        "races":        [r.to_dict() for r in races],
    })


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    """
    Force a simulator tick immediately (dev/demo tool).
    Hit this from the dashboard 'Force Update' button to see the traffic
    lights change without waiting 60 seconds.
    """
    from simulator import simulate_price_movement
    simulate_price_movement()
    races   = get_upcoming_races()
    summary = dashboard_summary(races)
    return jsonify({
        "status":       "ok",
        "message":      "Simulator tick complete.",
        "last_updated": datetime.utcnow().strftime("%H:%M:%S"),
        "summary":      summary,
        "races":        [r.to_dict() for r in races],
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Re-seed the database (dev tool — wipe and repopulate)."""
    from seed_db import seed
    seed()
    return jsonify({"status": "ok", "message": "Database re-seeded."})


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Run with debug=False in production (gunicorn handles this)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
    # use_reloader=False prevents APScheduler from starting twice in debug mode