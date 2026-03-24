import json
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

db = SQLAlchemy()


class Race(db.Model):
    __tablename__ = "races"

    id         = db.Column(db.Integer, primary_key=True)
    venue      = db.Column(db.String(100), nullable=False)
    race_name  = db.Column(db.String(200), nullable=False)
    race_time  = db.Column(db.DateTime,    nullable=False)
    distance   = db.Column(db.String(50))
    race_class = db.Column(db.String(50))
    going      = db.Column(db.String(50))
    country    = db.Column(db.String(10), default="GB")
    created_at = db.Column(db.DateTime,   default=datetime.utcnow)

    horses = db.relationship("Horse", backref="race", lazy=True, cascade="all, delete-orphan")

    @property
    def minutes_to_off(self):
        delta = self.race_time - datetime.utcnow()
        return max(0, int(delta.total_seconds() / 60))

    @property
    def status_label(self):
        mins = self.minutes_to_off
        if mins <= 5:   return "GOING OFF"
        if mins <= 15:  return "IMMINENT"
        return f"{mins}m"

    @property
    def sentiment(self):
        if not self.horses:
            return "neutral"
        bullish = sum(1 for h in self.horses if h.back_pct > 65)
        bearish = sum(1 for h in self.horses if h.back_pct < 35)
        if bullish > bearish:   return "bullish"
        if bearish > bullish:   return "bearish"
        return "neutral"

    @property
    def steam_cluster_count(self):
        return sum(1 for h in self.horses if h.pct_drop >= 8 and h.edge_score >= 40)

    def to_dict(self):
        horses_sorted = sorted(self.horses, key=lambda h: h.current_odds)
        return {
            "id":             self.id,
            "venue":          self.venue,
            "race_name":      self.race_name,
            "race_time":      self.race_time.strftime("%H:%M"),
            "distance":       self.distance,
            "race_class":     self.race_class,
            "going":          self.going,
            "country":        self.country,
            "minutes_to_off": self.minutes_to_off,
            "status_label":   self.status_label,
            "sentiment":      self.sentiment,
            "steam_cluster":  self.steam_cluster_count,
            "horses":         [h.to_dict() for h in horses_sorted],
        }


class Horse(db.Model):
    __tablename__ = "horses"

    id                = db.Column(db.Integer, primary_key=True)
    race_id           = db.Column(db.Integer, db.ForeignKey("races.id"), nullable=False)
    name              = db.Column(db.String(100), nullable=False)
    jockey            = db.Column(db.String(100))
    trainer           = db.Column(db.String(100))

    opening_odds      = db.Column(db.Float, nullable=False)
    previous_odds     = db.Column(db.Float)
    current_odds      = db.Column(db.Float, nullable=False)

    matched_volume    = db.Column(db.Float, default=0)
    volume_5min       = db.Column(db.Float, default=0)
    volume_spike      = db.Column(db.Boolean, default=False)
    back_pct          = db.Column(db.Float, default=50.0)

    steam_velocity    = db.Column(db.Float, default=0.0)
    bookie_count      = db.Column(db.Integer, default=0)
    edge_score        = db.Column(db.Float, default=0.0)
    is_fake_steam     = db.Column(db.Boolean, default=False)
    sentiment         = db.Column(db.String(20), default="neutral")
    market_depth_json = db.Column(db.Text, default="{}")

    # ── New fields ─────────────────────────────────────────────────────
    conf_score        = db.Column(db.Float, default=0.0)    # 0-100 confidence
    quality_index     = db.Column(db.String(5), default="D") # A+/A/B/C/D
    ev_score          = db.Column(db.Float, default=0.0)    # EV vs opening
    is_drift_reversal = db.Column(db.Boolean, default=False)
    price_stability   = db.Column(db.Float, default=100.0)  # 100=stable, lower=erratic
    spread_width      = db.Column(db.Float, default=0.0)

    last_updated_time = db.Column(db.DateTime, default=datetime.utcnow)

    history = db.relationship("OddsHistory", backref="horse", lazy=True,
                               cascade="all, delete-orphan",
                               order_by="OddsHistory.timestamp")

    # ── Properties ────────────────────────────────────────────────────

    @property
    def pct_drop(self):
        if not self.opening_odds or self.opening_odds == 0:
            return 0.0
        return ((self.opening_odds - self.current_odds) / self.opening_odds) * 100

    @property
    def pct_change_last_tick(self):
        if not self.previous_odds or self.previous_odds == 0:
            return 0.0
        return ((self.previous_odds - self.current_odds) / self.previous_odds) * 100

    @property
    def status(self):
        if self.previous_odds is None:
            return "neutral"
        c = self.pct_change_last_tick
        if c >= 3:   return "steam"
        if c <= -3:  return "drift"
        return "neutral"

    @property
    def is_smart_money_alert(self):
        if self.pct_drop <= 15:
            return False
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        return self.last_updated_time is not None and self.last_updated_time >= cutoff

    @property
    def market_depth(self):
        try:
            return json.loads(self.market_depth_json or "{}")
        except Exception:
            return {}

    @staticmethod
    def decimal_to_fractional(decimal_odds):
        if decimal_odds is None:
            return "N/A"
        n = decimal_odds - 1
        for d in [1, 2, 4, 5, 8, 10]:
            num = round(n * d)
            if abs((num / d) - n) < 0.05:
                return f"{num}/{d}"
        return f"{n:.1f}/1"

    def sparkline_data(self):
        return [(h.timestamp.strftime("%H:%M:%S"), round(h.odds, 2))
                for h in self.history[-10:]]

    def steam_timeline(self):
        return [{"time": h.timestamp.strftime("%H:%M"), "odds": round(h.odds, 2),
                 "volume": round(h.volume or 0)} for h in self.history]

    def to_dict(self):
        return {
            "id":               self.id,
            "name":             self.name,
            "jockey":           self.jockey,
            "trainer":          self.trainer,
            "opening_odds":     round(self.opening_odds, 2),
            "previous_odds":    round(self.previous_odds, 2) if self.previous_odds else None,
            "current_odds":     round(self.current_odds, 2),
            "fractional_odds":  self.decimal_to_fractional(self.current_odds),
            "pct_drop":         round(self.pct_drop, 1),
            "pct_change_tick":  round(self.pct_change_last_tick, 1),
            "status":           self.status,
            "bookie_count":     self.bookie_count,
            "is_smart_money":   self.is_smart_money_alert,
            "matched_volume":   round(self.matched_volume or 0),
            "volume_5min":      round(self.volume_5min or 0),
            "volume_spike":     self.volume_spike,
            "back_pct":         round(self.back_pct or 50, 1),
            "steam_velocity":   round(self.steam_velocity or 0, 2),
            "edge_score":       round(self.edge_score or 0),
            "is_fake_steam":    self.is_fake_steam,
            "sentiment":        self.sentiment,
            "market_depth":     self.market_depth,
            "conf_score":       round(self.conf_score or 0),
            "quality_index":    self.quality_index or "D",
            "ev_score":         round(self.ev_score or 0, 1),
            "is_drift_reversal": self.is_drift_reversal,
            "price_stability":  round(self.price_stability or 100, 1),
            "spread_width":     round(self.spread_width or 0, 2),
            "sparkline":        self.sparkline_data(),
            "last_updated":     self.last_updated_time.strftime("%H:%M:%S")
                                if self.last_updated_time else None,
        }


class OddsHistory(db.Model):
    __tablename__ = "odds_history"

    id        = db.Column(db.Integer, primary_key=True)
    horse_id  = db.Column(db.Integer, db.ForeignKey("horses.id"), nullable=False)
    odds      = db.Column(db.Float,   nullable=False)
    volume    = db.Column(db.Float,   default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class DailySteamResult(db.Model):
    __tablename__ = "daily_steam_results"

    id            = db.Column(db.Integer, primary_key=True)
    date          = db.Column(db.String(20))
    horse_name    = db.Column(db.String(100))
    venue         = db.Column(db.String(100))
    race_time     = db.Column(db.String(10))
    opening_odds  = db.Column(db.Float)
    flagged_odds  = db.Column(db.Float)
    pct_drop      = db.Column(db.Float)
    edge_score    = db.Column(db.Float)
    result        = db.Column(db.String(20), default="pending")
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)


class StrategyResult(db.Model):
    """
    Records every simulated bet for full performance tracking.
    Multiple strategy tags allow side-by-side ROI comparison.
    """
    __tablename__ = "strategy_results"

    id            = db.Column(db.Integer, primary_key=True)
    horse_name    = db.Column(db.String(100))
    venue         = db.Column(db.String(100))
    race_time     = db.Column(db.String(10))
    bet_type      = db.Column(db.String(10), default="back")   # back / lay
    odds_taken    = db.Column(db.Float)
    stake         = db.Column(db.Float, default=1.0)
    result        = db.Column(db.String(20))   # win / loss / place
    profit        = db.Column(db.Float, default=0.0)
    strategy_tag  = db.Column(db.String(50))   # "edge_70", "volume_spike", "quality_A"
    edge_score    = db.Column(db.Float, default=0.0)
    quality_index = db.Column(db.String(5), default="B")
    timestamp     = db.Column(db.DateTime, default=datetime.utcnow)
