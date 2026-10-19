"""Synthetic transfer events for the anomaly-detection experiments (no real data).

Features (same order as the engine): hour, sensitivity, size_mb, dest_risk, count_1h.
Label 1 = exfiltration, generated in three equal patterns.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_sentinel import config  # noqa: E402

FEATURES = config.FEATURES
NIGHT_HOURS = [0, 1, 2, 3, 4, 5, 21, 22, 23]


def _normal(rng, n):
    return np.column_stack([
        np.clip(rng.normal(13, 2.5, n), 0, 23.99),                                 # hour
        rng.choice([0, 1, 2, 3], size=n, p=[.45, .40, .12, .03]),                 # sensitivity
        rng.lognormal(-0.5, 1.0, n),                                              # size (MB)
        rng.choice([0, .3, .6, .7, .8], size=n, p=[.40, .25, .20, .10, .05]),     # destination risk
        rng.poisson(1.5, n),                                                      # transfers in last hour
    ])


def _night_bulk(rng, n):
    return np.column_stack([
        rng.choice(NIGHT_HOURS, size=n) + rng.uniform(0, 1, n),
        rng.integers(1, 4, n),
        rng.lognormal(0.5, 1.0, n),
        rng.choice([.7, .8], size=n),
        rng.integers(8, 40, n),
    ])


def _large_file(rng, n):
    return np.column_stack([
        np.clip(rng.normal(14, 3, n), 0, 23.99),
        rng.integers(2, 4, n),
        rng.uniform(60, 900, n),
        rng.choice([.6, .7, .8], size=n),
        rng.poisson(1, n),
    ])


def _burst(rng, n):
    return np.column_stack([
        np.clip(rng.normal(15, 3, n), 0, 23.99),
        rng.integers(1, 4, n),
        rng.lognormal(-1, 0.8, n),
        rng.choice([.6, .7, .8], size=n),
        rng.integers(12, 60, n),
    ])


def generate(n=5000, exfil_rate=0.05, seed=42):
    """Return X (n x 5), y (0/1) and pattern names, shuffled."""
    rng = np.random.default_rng(seed)
    n_bad = int(round(n * exfil_rate))
    thirds = [n_bad // 3, n_bad // 3, n_bad - 2 * (n_bad // 3)]
    parts = [_normal(rng, n - n_bad), _night_bulk(rng, thirds[0]), _large_file(rng, thirds[1]), _burst(rng, thirds[2])]
    X = np.vstack(parts)
    y = np.concatenate([np.zeros(n - n_bad, int), np.ones(n_bad, int)])
    pattern = np.array(["normal"] * (n - n_bad) + ["night bulk copy"] * thirds[0]
                       + ["large sensitive file"] * thirds[1] + ["burst of small files"] * thirds[2])
    order = rng.permutation(n)
    return X[order], y[order], pattern[order]


def heuristic(X):
    return np.minimum(1.0, X[:, 4] / config.HEURISTIC_DIVISOR)


def iforest_unit(model, X):
    return np.clip((-model.score_samples(X) - 0.5) / 0.2, 0, 1)
