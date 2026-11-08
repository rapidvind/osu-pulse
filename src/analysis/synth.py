"""Synthetic miss/play data - FOR TESTS ONLY.

Real osu!Pulse databases are small (one player's own history), which is
fine for the honest, caveated analysis this module produces but not great
for exercising edge cases (empty clusters, degenerate folds, etc.) in unit
tests without depending on whoever's local osu_analytics.db happens to
contain. Nothing in here is used by the dashboard or by README.md - numbers
from fake data have no place representing real play.
"""
import numpy as np
import pandas as pd

FINGERS = ["left_middle", "left_index", "right_index", "right_middle"]
PATTERNS = ["jack", "stream", "isolated"]


def generate_synthetic_misses(n=600, seed=0):
    """Fake miss-level rows shaped like features.load_miss_features()'s
    output, with a deliberate finger/pattern skew so clustering has
    something non-trivial to recover."""
    rng = np.random.default_rng(seed)
    finger = rng.choice(FINGERS, size=n, p=[0.35, 0.25, 0.25, 0.15])
    pattern = rng.choice(PATTERNS, size=n, p=[0.6, 0.3, 0.1])
    combo_before_miss = rng.integers(0, 400, size=n)
    position_frac = rng.uniform(0, 1, size=n)
    return pd.DataFrame({
        "miss_id": np.arange(n),
        "play_id": rng.integers(1, 30, size=n),
        "finger": finger,
        "pattern": pattern,
        "combo_before_miss": combo_before_miss,
        "song_time_ms": (position_frac * 180_000).astype(int),
        "position_frac": position_frac,
        "log_combo": np.log1p(combo_before_miss),
    })


def generate_synthetic_plays(n=40, seed=0, n_outliers=2):
    """Fake play-level rows shaped like features.load_play_features()'s
    output. The last n_outliers rows are deliberately extreme (very high
    miss_rate / very low accuracy) so anomaly-detection tests have a known
    positive to look for."""
    rng = np.random.default_rng(seed)
    judged_count = rng.integers(500, 4000, size=n)
    miss_rate = np.clip(rng.normal(0.02, 0.01, size=n), 0, None)
    miss_count = (miss_rate * judged_count).astype(int)
    accuracy = np.clip(100 - miss_rate * 300 + rng.normal(0, 1, size=n), 0, 100)
    max_combo = np.clip(judged_count - miss_count * rng.integers(1, 5, size=n), 0, None)

    if n_outliers:
        miss_rate[-n_outliers:] = 0.3
        miss_count[-n_outliers:] = (judged_count[-n_outliers:] * 0.3).astype(int)
        accuracy[-n_outliers:] = 40.0
        max_combo[-n_outliers:] = 5

    game_session_id = np.repeat(np.arange(1, n // 5 + 2), 5)[:n]
    session_play_index = pd.Series(game_session_id).groupby(game_session_id).cumcount().to_numpy() + 1

    return pd.DataFrame({
        "play_id": np.arange(1, n + 1),
        "game_session_id": game_session_id,
        "beatmap_id": rng.integers(1_000_000, 9_999_999, size=n),
        "accuracy": accuracy,
        "max_combo": max_combo,
        "failed": (accuracy < 60).astype(int),
        "prior_best_miss_count": np.where(rng.random(n) < 0.3, rng.integers(0, 50, size=n), np.nan),
        "miss_count": miss_count,
        "judged_count": judged_count,
        "session_play_index": session_play_index,
        "miss_rate": miss_rate,
    })
