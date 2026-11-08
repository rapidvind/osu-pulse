"""Models expected miss_count as a function of what we can actually measure
per play, then looks at the residual (actual - expected) as a rough "harder
than expected" / "easier than expected" signal.

IMPORTANT caveat, not just a comment: this is NOT a true difficulty
regression. A real one would need the map's note density / pattern mix /
star rating, and most historical plays in this database can't supply that -
see features.py's docstring and README.md. The covariates here are proxies:

  - judged_count: total notes judged in the play - a stand-in for map
    length (longer map, more chances to miss), not difficulty.
  - has_prior_best / prior_best_miss_count: whether/how well this map had
    already been played before (familiarity), from osu!'s own local
    leaderboard. Only populated for maps replayed through this app, so it's
    sparse.
  - session_play_index: which attempt this was within its game session - a
    fatigue proxy (tenth map of the session vs. the first).

Two models are compared with repeated k-fold cross-validation (5-fold x 5
repeats, since N is only in the double digits and a single train/test split
would be noise): a Poisson GLM baseline (miss_count is a non-negative count,
which a plain linear model doesn't respect) and a small RandomForestRegressor.
If the forest doesn't beat the baseline's mean CV R^2, that is reported
plainly rather than papered over - with N this small, a forest "winning" is
not a strong claim either way.
"""
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import RepeatedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURE_COLS = ["judged_count", "has_prior_best", "prior_best_miss_count_filled", "session_play_index"]
TARGET_COL = "miss_count"
N_SPLITS = 5
N_REPEATS = 5


def build_regression_matrix(play_df):
    """Returns (X, y, feature_names). Rows with a missing target or
    judged_count are dropped (both should always be present, but this keeps
    the function defensive against partially-recorded plays)."""
    df = play_df.dropna(subset=[TARGET_COL, "judged_count"]).copy()
    df["has_prior_best"] = df["prior_best_miss_count"].notna().astype(int)
    median_prior = df["prior_best_miss_count"].median()
    df["prior_best_miss_count_filled"] = df["prior_best_miss_count"].fillna(
        median_prior if not np.isnan(median_prior) else 0
    )
    X = df[FEATURE_COLS].to_numpy(dtype=float)
    y = df[TARGET_COL].to_numpy(dtype=float)
    return X, y, FEATURE_COLS, df["play_id"].to_numpy()


def run_regression_report(play_df, seed=42):
    """Cross-validates both models, picks the one with the higher mean CV
    R^2 as the "primary" model for residuals (ties/negative-R^2 default to
    the baseline, since a forest with N this small is prone to look better
    on paper from variance alone), and reports per-play residuals from a
    final fit of that model on the full dataset."""
    X, y, feature_names, play_ids = build_regression_matrix(play_df)
    if len(y) < N_SPLITS * 2:
        return {"error": "not enough plays for cross-validated regression", "n_plays": len(y)}

    n_splits = min(N_SPLITS, len(y) // 2) or 2

    def cv(model_factory):
        folds = RepeatedKFold(n_splits=n_splits, n_repeats=N_REPEATS, random_state=seed)
        r2_scores, mae_scores = [], []
        for train_idx, test_idx in folds.split(X):
            model = model_factory()
            model.fit(X[train_idx], y[train_idx])
            pred = model.predict(X[test_idx])
            r2_scores.append(r2_score(y[test_idx], pred))
            mae_scores.append(mean_absolute_error(y[test_idx], pred))
        return {
            "r2_mean": float(np.mean(r2_scores)), "r2_std": float(np.std(r2_scores)),
            "mae_mean": float(np.mean(mae_scores)), "mae_std": float(np.std(mae_scores)),
        }

    # The Poisson GLM's solver (IRLS-ish, via LBFGS) is sensitive to how
    # differently scaled the raw features are (judged_count ranges into the
    # thousands, session_play_index into the teens) and diverges to NaN
    # without it; scaling doesn't matter for the forest's splits, so it's
    # applied uniformly rather than special-cased per model.
    make_baseline = lambda: make_pipeline(StandardScaler(), PoissonRegressor(max_iter=1000))
    make_rf = lambda: RandomForestRegressor(n_estimators=200, max_depth=4, random_state=seed)

    baseline_metrics = cv(make_baseline)
    rf_metrics = cv(make_rf)

    rf_wins = rf_metrics["r2_mean"] > baseline_metrics["r2_mean"]
    primary_name = "random_forest" if rf_wins else "poisson_baseline"
    primary_model = make_rf() if rf_wins else make_baseline()
    primary_model.fit(X, y)
    predicted = primary_model.predict(X)

    feature_importances = None
    if rf_wins:
        feature_importances = dict(zip(feature_names, primary_model.feature_importances_.tolist()))

    residual_rows = [
        {
            "play_id": int(pid), "actual_misses": float(actual),
            "expected_misses": float(expected), "residual": float(actual - expected),
        }
        for pid, actual, expected in zip(play_ids, y, predicted)
    ]
    residual_rows.sort(key=lambda r: r["residual"])

    return {
        "n_plays": len(y),
        "cv_splits": n_splits,
        "cv_repeats": N_REPEATS,
        "feature_names": feature_names,
        "baseline_poisson": baseline_metrics,
        "random_forest": rf_metrics,
        "rf_beats_baseline": bool(rf_wins),
        "primary_model": primary_name,
        "feature_importances": feature_importances,
        "residuals": residual_rows,
    }
