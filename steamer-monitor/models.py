from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

db = SQLAlchemy()


class Race(db.Model):
    """Represents a single horse race."""

    __tablename__ = "races"

    id         = db.Column(db.Integer, primary_key=True)
    venue      = db.Column(db.String(100), nullable=False)   # e.g. "Cheltenham"
    race_name  = db.Column(db.String(200), nullable=False)   # e.g. "Neptune Novices' Hurdle"
    race_time  = db.Column(db.DateTime,    nullable=False)   # scheduled off-time
    distance   = db.Column(db.String(50))                    # e.g. "2m4f"
    race_class = db.Column(db.String(50))                    # e.g. "Grade 1"
    going      = db.Column(db.String(50))                    # e.g. "Good to Soft"
    country    = db.Column(db.String(10), default="GB")      # "GB" or "IRE"
    created_at = db.Column(db.DateTime,   default=datetime.utcnow)

    horses = db.relationship("Horse", backref="race", lazy=True, cascade="all, delete-orphan")

    @property
    def minutes_to_off(self):
        delta = self.race_time - datetime.utcnow()
        return max(0, int(delta.total_seconds() / 60))

    @property
    def status_label(self):
        mins = self.minutes_to_off
        if mins <= 5:
            return "GOING OFF"
        elif mins <= 15:
            return "IMMINENT"
        return f"{mins}m"

    def to_dict(self):
        horses_sorted = sorted(self.horses, key=lambda h: h.current_odds)
        return {
            "id":           self.id,
            "venue":        self.venue,
            "race_name":    self.race_name,
            "race_time":    self.race_time.strftime("%H:%M"),
            "distance":     self.distance,
            "race_class":   self.race_class,
            "going":        self.going,
            "country":      self.country,
            "minutes_to_off": self.minutes_to_off,
            "status_label": self.status_label,
            "horses":       [h.to_dict() for h in horses_sorted],
        }


class Horse(db.Model):
    """Represents a runner in a race, tracking odds movement over time."""

    __tablename__ = "horses"

    id                = db.Column(db.Integer, primary_key=True)
    race_id           = db.Column(db.Integer, db.ForeignKey("races.id"), nullable=False)
    name              = db.Column(db.String(100), nullable=False)
    jockey            = db.Column(db.String(100))
    trainer           = db.Column(db.String(100))

    # Core odds fields — all stored as decimal odds (e.g. 4.0 = 3/1)
    opening_odds      = db.Column(db.Float, nullable=False)
    previous_odds     = db.Column(db.Float)
    current_odds      = db.Column(db.Float, nullable=False)

    # How many of our simulated bookmakers are cutting the price simultaneously
    bookie_count      = db.Column(db.Integer, default=0)

    last_updated_time = db.Column(db.DateTime, default=datetime.utcnow)

    # ------------------------------------------------------------------ #
    #  Calculated properties                                               #
    # ------------------------------------------------------------------ #

    @property
    def pct_drop(self):
        """((opening - current) / opening) * 100  — positive = steaming."""
        if not self.opening_odds or self.opening_odds == 0:
            return 0.0
        return ((self.opening_odds - self.current_odds) / self.opening_odds) * 100

    @property
    def pct_change_last_tick(self):
        """Percentage change vs the previous scrape tick."""
        if not self.previous_odds or self.previous_odds == 0:
            return 0.0
        return ((self.previous_odds - self.current_odds) / self.previous_odds) * 100

    @property
    def confidence_score(self):
        """0-100 score based on how many bookies are simultaneously cutting."""
        return round(min(100, (self.bookie_count / 5) * 100))

    @property
    def status(self):
        """Traffic-light status based on odds movement this tick."""
        if self.previous_odds is None:
            return "neutral"
        change_pct = self.pct_change_last_tick
        if change_pct >= 3:        # price shortened by ≥3%  → green
            return "steam"
        elif change_pct <= -3:     # price drifted  by ≥3%  → red
            return "drift"
        return "neutral"

    @property
    def is_smart_money_alert(self):
        """
        Smart Money Alert: odds have dropped >15% from opening AND the
        move happened in the last 10 minutes.
        """
        if self.pct_drop <= 15:
            return False
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        return self.last_updated_time is not None and self.last_updated_time >= cutoff

    @staticmethod
    def decimal_to_fractional(decimal_odds):
        """Convert decimal odds to a tidy fractional string for display."""
        if decimal_odds is None:
            return "N/A"
        numerator = decimal_odds - 1
        # Find a clean fraction (approximate)
        for denom in [1, 2, 4, 5, 8, 10]:
            num = round(numerator * denom)
            if abs((num / denom) - numerator) < 0.05:
                return f"{num}/{denom}"
        return f"{numerator:.1f}/1"

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
            "confidence_score": self.confidence_score,
            "bookie_count":     self.bookie_count,
            "is_smart_money":   self.is_smart_money_alert,
            "last_updated":     self.last_updated_time.strftime("%H:%M:%S")
                                if self.last_updated_time else None,
        }