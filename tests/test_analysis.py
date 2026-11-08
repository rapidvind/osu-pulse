"""Tests for src/analysis/*, run entirely against synth.py's fake data -
never against a real osu_analytics.db, so these pass the same way on any
machine regardless of how much (or little) real play history exists."""
import numpy as np
import pytest

from analysis import anomaly, clustering, regression
from analysis.synth import generate_synthetic_misses, generate_synthetic_plays


# --- clustering --------------------------------------------------------

def test_build_feature_matrix_shape_and_scale():
    misses = generate_synthetic_misses(n=300, seed=1)
    X, names = clustering.build_feature_matrix(misses)

    assert X.shape[0] == len(misses)
    assert X.shape[1] == len(names)
    assert not np.isnan(X).any()
    # standardised: each column should be roughly mean 0 (loosely, for a
    # feature matrix this size - not asserting std since one-hot columns
    # with low prevalence can legitimately have an inflated std post-scale)
    assert np.all(np.abs(X.mean(axis=0)) < 0.5)


def test_sweep_k_returns_a_score_per_k():
    misses = generate_synthetic_misses(n=300, seed=1)
    X, _ = clustering.build_feature_matrix(misses)
    scores = clustering.sweep_k(X, k_range=range(3, 6), seed=0)

    assert set(scores) == {3, 4, 5}
    assert all(-1.0 <= v <= 1.0 for v in scores.values())


def test_stability_ari_is_bounded():
    misses = generate_synthetic_misses(n=300, seed=1)
    X, _ = clustering.build_feature_matrix(misses)
    mean_ari, std_ari = clustering.stability_ari(X, k=4, seeds=(0, 1, 2))

    assert -1.0 <= mean_ari <= 1.0
    assert std_ari >= 0.0


def test_run_clustering_report_shape():
    misses = generate_synthetic_misses(n=400, seed=2)
    report = clustering.run_clustering_report(misses, seed=0)

    assert "error" not in report
    assert report["k"] >= 3
    assert len(report["kmeans"]["clusters"]) == report["k"]
    assert sum(c["size"] for c in report["kmeans"]["clusters"]) == report["usable_misses"]
    assert -1.0 <= report["kmeans"]["silhouette"] <= 1.0
    assert -1.0 <= report["agglomerative"]["silhouette"] <= 1.0


def test_run_clustering_report_handles_too_few_rows():
    misses = generate_synthetic_misses(n=5, seed=0)
    report = clustering.run_clustering_report(misses)

    assert "error" in report


# --- anomaly -------------------------------------------------------------

def test_robust_zscore_flags_injected_outliers():
    plays = generate_synthetic_plays(n=40, seed=3, n_outliers=2)
    flagged = anomaly.robust_zscore_outliers(plays)

    outlier_ids = set(plays["play_id"].iloc[-2:])
    assert outlier_ids.issubset(set(flagged.loc[flagged["is_outlier_baseline"], "play_id"]))


def test_isolation_forest_flags_injected_outliers():
    plays = generate_synthetic_plays(n=40, seed=3, n_outliers=2)
    flagged = anomaly.isolation_forest_outliers(plays, seed=0)

    outlier_ids = set(plays["play_id"].iloc[-2:])
    assert outlier_ids.issubset(set(flagged.loc[flagged["is_outlier_iforest"], "play_id"]))


def test_run_anomaly_report_agreement_counts():
    plays = generate_synthetic_plays(n=40, seed=3, n_outliers=2)
    report = anomaly.run_anomaly_report(plays, seed=0)

    assert "error" not in report
    total_flagged_relationships = sum(report["agreement"].values())
    assert total_flagged_relationships >= 2  # at least the two injected outliers
    assert len(report["flagged"]) >= 2


def test_run_anomaly_report_handles_too_few_rows():
    plays = generate_synthetic_plays(n=5, seed=0, n_outliers=0)
    report = anomaly.run_anomaly_report(plays)

    assert "error" in report


# --- regression ------------------------------------------------------------

def test_build_regression_matrix_no_nans():
    plays = generate_synthetic_plays(n=40, seed=4)
    X, y, names, play_ids = regression.build_regression_matrix(plays)

    assert X.shape == (len(plays), len(names))
    assert not np.isnan(X).any()
    assert not np.isnan(y).any()
    assert len(play_ids) == len(plays)


def test_run_regression_report_cv_metrics_are_finite():
    plays = generate_synthetic_plays(n=50, seed=5)
    report = regression.run_regression_report(plays, seed=0)

    assert "error" not in report
    for metrics in (report["baseline_poisson"], report["random_forest"]):
        assert np.isfinite(metrics["r2_mean"])
        assert np.isfinite(metrics["mae_mean"])
        assert metrics["mae_mean"] >= 0

    assert report["primary_model"] in ("random_forest", "poisson_baseline")
    assert len(report["residuals"]) == report["n_plays"]
    # residuals should be sorted ascending (most "easier than expected" first)
    residual_values = [r["residual"] for r in report["residuals"]]
    assert residual_values == sorted(residual_values)


def test_run_regression_report_handles_too_few_rows():
    plays = generate_synthetic_plays(n=4, seed=0)
    report = regression.run_regression_report(plays)

    assert "error" in report
