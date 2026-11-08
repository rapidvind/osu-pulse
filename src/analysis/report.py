"""Glue between features.py's DataFrames and the three analysis methods -
what app.py's /api/analysis route actually calls. Kept separate from
clustering.py/anomaly.py/regression.py so each of those stays unit-testable
against synth.py's data without needing a live database."""
from analysis.anomaly import run_anomaly_report
from analysis.clustering import run_clustering_report
from analysis.features import load_miss_features, load_play_features
from analysis.regression import run_regression_report


def build_full_report():
    miss_df = load_miss_features()
    play_df = load_play_features()

    return {
        "miss_exclusions": miss_df.attrs.get("excluded", {}),
        "play_count": len(play_df),
        "clustering": run_clustering_report(miss_df),
        "anomaly": run_anomaly_report(play_df),
        "regression": run_regression_report(play_df),
    }
