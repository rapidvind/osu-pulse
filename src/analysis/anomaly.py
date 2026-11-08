"""Flags plays that look unusually bad or unusually good given the rest of
the player's history.

Two independent methods, reported side by side rather than picking one as
"correct":

  - IsolationForest over [miss_rate, accuracy, max_combo, failed] - can
    catch multivariate outliers (e.g. a play with ordinary accuracy but a
    bizarre combo/miss-rate combination) that a single-column check misses.
  - a robust z-score baseline on miss_rate and accuracy alone (median +
    MAD, not mean + stdev, so a couple of genuinely terrible plays don't
    drag the "normal" band wide enough to hide everything else) - the
    simplest thing that could possibly work, used here as a sanity check
    on the Isolation Forest rather than a competitor to beat.

N is small (double digits of plays per player), so neither method should be
read as a statistically confident anomaly detector - "flagged by both
methods" is a much stronger signal than "flagged by one."
"""
import numpy as np
from sklearn.ensemble import IsolationForest

FEATURE_COLS = ["miss_rate", "accuracy", "max_combo", "failed"]
ROBUST_Z_THRESHOLD = 3.0
# Scales a MAD to be comparable to a standard deviation under normality -
# the usual constant (1 / 0.6745 as Phi^-1(0.75)).
MAD_TO_STD = 1.4826


def _robust_z(series):
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0:
        return (series - median) * 0.0
    return (series - median) / (mad * MAD_TO_STD)


def robust_zscore_outliers(play_df, threshold=ROBUST_Z_THRESHOLD):
    """Baseline: flag plays whose miss_rate or accuracy robust z-score
    exceeds the threshold in magnitude. Returns the input columns plus
    z_miss_rate, z_accuracy, and is_outlier_baseline."""
    df = play_df.dropna(subset=["miss_rate", "accuracy"]).copy()
    df["z_miss_rate"] = _robust_z(df["miss_rate"])
    df["z_accuracy"] = _robust_z(df["accuracy"])
    df["is_outlier_baseline"] = (df["z_miss_rate"].abs() > threshold) | (df["z_accuracy"].abs() > threshold)
    return df


def isolation_forest_outliers(play_df, seed=42, contamination="auto"):
    """IsolationForest over the full feature set. Returns the input plus
    anomaly_score (lower = more anomalous, matching sklearn's
    decision_function convention) and is_outlier_iforest."""
    df = play_df.dropna(subset=FEATURE_COLS).copy()
    X = df[FEATURE_COLS].to_numpy(dtype=float)
    model = IsolationForest(random_state=seed, contamination=contamination, n_estimators=200)
    df["is_outlier_iforest"] = model.fit_predict(X) == -1
    df["anomaly_score"] = model.decision_function(X)
    return df


def run_anomaly_report(play_df, seed=42):
    """Runs both methods and merges them on play_id so each play's row shows
    whether each method flagged it, plus a plain-English direction (bad vs.
    good) based on whether it under- or over-performed its own miss_rate/
    accuracy median."""
    if len(play_df) < 10:
        return {"error": "not enough plays for anomaly detection", "n_plays": len(play_df)}

    baseline = robust_zscore_outliers(play_df)
    iforest = isolation_forest_outliers(play_df, seed=seed)

    merged = baseline.merge(
        iforest[["play_id", "is_outlier_iforest", "anomaly_score"]], on="play_id", how="inner"
    )
    merged["direction"] = np.where(
        merged["z_miss_rate"] > 0, "worse_than_usual", "better_than_usual"
    )

    flagged_either = merged[merged["is_outlier_baseline"] | merged["is_outlier_iforest"]].copy()
    flagged_either = flagged_either.sort_values("anomaly_score")

    both = int((merged["is_outlier_baseline"] & merged["is_outlier_iforest"]).sum())
    baseline_only = int((merged["is_outlier_baseline"] & ~merged["is_outlier_iforest"]).sum())
    iforest_only = int((~merged["is_outlier_baseline"] & merged["is_outlier_iforest"]).sum())

    cols = ["play_id", "beatmap_id", "miss_rate", "accuracy", "max_combo", "failed",
            "z_miss_rate", "z_accuracy", "is_outlier_baseline", "is_outlier_iforest",
            "anomaly_score", "direction"]

    return {
        "n_plays": len(merged),
        "agreement": {"both": both, "baseline_only": baseline_only, "iforest_only": iforest_only},
        "flagged": flagged_either[cols].to_dict(orient="records"),
    }
