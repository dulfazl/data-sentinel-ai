"""Anomaly detection: Isolation Forest (the AI part) combined with a frequency heuristic.

Order of preference for the ML model:
  1. models/anomaly_iforest.joblib (trained by ml/train_eval.py), if present
  2. a model trained on this database once it holds 50+ events
  3. none - the heuristic alone is used
The final anomaly signal is max(ML unit score, heuristic).
"""
import json
import threading
from pathlib import Path

import numpy as np

from . import config


def heuristic_score(count_1h):
    return min(1.0, count_1h / config.HEURISTIC_DIVISOR)


def unit_score(raw):
    """Map -score_samples (about 0.5 = normal, > 0.6 = unusual) onto 0..1."""
    return float(np.clip((raw - 0.5) / 0.2, 0.0, 1.0))


def new_model(seed=42):
    from sklearn.ensemble import IsolationForest
    return IsolationForest(n_estimators=200, contamination=0.05, random_state=seed)


def feature_vector(feats):
    return np.array([[float(feats[k]) for k in config.FEATURES]])


class AnomalyDetector:
    def __init__(self, db, model_path=None, use_saved_model=True):
        self.db = db
        self.model = None
        self.source = "heuristic only"
        self._trained_rows = 0
        self._lock = threading.Lock()
        path = Path(model_path or config.MODEL_PATH)
        if use_saved_model and path.exists():
            try:
                import joblib
                self.model = joblib.load(path)
                self.source = "Isolation Forest, saved model"
            except Exception as exc:         # unreadable model: fall back gracefully
                print(f"  [anomaly] could not load {path.name}: {exc}; using heuristic")
                self.model = None

    @property
    def saved(self):
        return self.source.endswith("saved model")

    def maybe_train(self):
        """Train on the database once it has MIN_TRAIN_ROWS events (re-train every +50)."""
        if self.saved:
            return
        with self._lock:
            n = self.db.scalar("SELECT COUNT(*) AS n FROM risk_assessments WHERE features IS NOT NULL") or 0
            if n < config.MIN_TRAIN_ROWS or n < self._trained_rows + config.MIN_TRAIN_ROWS:
                return
            rows = self.db.query("SELECT features FROM risk_assessments WHERE features IS NOT NULL")
            n = len(rows)
            X = np.array([[float(json.loads(r["features"])[k]) for k in config.FEATURES] for r in rows])
            self.model = new_model().fit(X)
            self._trained_rows = n
            self.source = f"Isolation Forest, trained on {n} database events"

    def score(self, feats):
        """Return (anomaly, ml_score or None, heuristic)."""
        self.maybe_train()
        heur = heuristic_score(feats["count_1h"])
        ml = None
        if self.model is not None:
            raw = -self.model.score_samples(feature_vector(feats))[0]
            ml = unit_score(raw)
        anomaly = heur if ml is None else max(heur, ml)
        return anomaly, ml, heur
