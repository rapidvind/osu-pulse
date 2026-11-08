"""Clusters misses into recurring failure types.

Method: standardise [finger one-hot, pattern one-hot, log_combo,
position_frac], then KMeans. k is picked by sweeping silhouette score, not
guessed. Stability is checked by re-fitting with several seeds and comparing
labels pairwise with Adjusted Rand Index (ARI near 1.0 = the same clusters
keep reappearing regardless of starting point; near 0 = the solution is
mostly noise).

Known limitation (surfaced in the README, not hidden here): KMeans assumes
Euclidean distance, which is a poor fit for one-hot categorical columns -
the "distance" between two different fingers is a modelling choice (here,
equal to being 1 unit apart in scaled space), not a measured quantity.
Agglomerative clustering is fit alongside KMeans as a sanity check using a
different mechanism (no centroid assumption), not because it's expected to
"win" - see run_clustering_report()'s docstring for how to read the two
side by side.
"""
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

NUMERIC_COLS = ["log_combo", "position_frac"]
CATEGORICAL_COLS = ["finger", "pattern"]
STABILITY_SEEDS = (0, 1, 2, 3, 4)
K_RANGE = range(3, 9)


def build_feature_matrix(miss_df):
    """Returns (X, feature_names) - a standardised numpy array ready for
    clustering, and the column name each position in X came from."""
    dummies = pd.get_dummies(miss_df[CATEGORICAL_COLS], prefix=CATEGORICAL_COLS)
    raw = pd.concat([miss_df[NUMERIC_COLS].reset_index(drop=True),
                      dummies.reset_index(drop=True)], axis=1)
    X = StandardScaler().fit_transform(raw.to_numpy(dtype=float))
    return X, list(raw.columns)


def sweep_k(X, k_range=K_RANGE, seed=42):
    """Silhouette score for each candidate k. Returns {k: score}."""
    scores = {}
    for k in k_range:
        labels = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(X)
        scores[k] = silhouette_score(X, labels)
    return scores


def best_k(scores):
    return max(scores, key=scores.get)


def stability_ari(X, k, seeds=STABILITY_SEEDS):
    """Mean +/- std of pairwise ARI between KMeans fits at different seeds -
    how much the cluster assignment itself depends on where KMeans started,
    independent of whether k is a good choice at all."""
    labelings = [KMeans(n_clusters=k, random_state=s, n_init=10).fit_predict(X) for s in seeds]
    pairwise = [
        adjusted_rand_score(labelings[i], labelings[j])
        for i in range(len(labelings)) for j in range(i + 1, len(labelings))
    ]
    return float(np.mean(pairwise)), float(np.std(pairwise))


def cluster_summary(miss_df, labels):
    """Human-readable description of each cluster: its size, its dominant
    finger/pattern (with the share of the cluster they make up), and its
    combo/position-in-map tendency. This is the part a reviewer can sanity
    check against intuition ("yeah, left-ring jacks early in the map" is a
    real, checkable claim)."""
    df = miss_df.copy()
    df["cluster"] = labels
    summaries = []
    for cluster_id, group in df.groupby("cluster"):
        finger_counts = group["finger"].value_counts(normalize=True)
        pattern_counts = group["pattern"].value_counts(normalize=True)
        summaries.append({
            "cluster": int(cluster_id),
            "size": int(len(group)),
            "share": float(len(group) / len(df)),
            "dominant_finger": finger_counts.index[0],
            "dominant_finger_share": float(finger_counts.iloc[0]),
            "dominant_pattern": pattern_counts.index[0],
            "dominant_pattern_share": float(pattern_counts.iloc[0]),
            "median_combo_before_miss": float(group["combo_before_miss"].median()),
            "mean_position_frac": float(group["position_frac"].mean()),
        })
    return sorted(summaries, key=lambda s: -s["size"])


def run_clustering_report(miss_df, seed=42):
    """Fits KMeans (k chosen by silhouette sweep) and Agglomerative
    clustering at the same k, and reports silhouette + stability for both so
    the two can be compared side by side rather than presenting KMeans's
    output as the only possible answer. Agglomerative has no random seed to
    sweep, so its "stability" is reported as plain silhouette only."""
    if len(miss_df) < 2 * max(K_RANGE):
        return {"error": "not enough usable misses to cluster", "usable_misses": len(miss_df)}

    X, feature_names = build_feature_matrix(miss_df)

    km_scores = sweep_k(X, seed=seed)
    k = best_k(km_scores)

    km_labels = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(X)
    km_ari_mean, km_ari_std = stability_ari(X, k)

    agg_labels = AgglomerativeClustering(n_clusters=k).fit_predict(X)
    agg_silhouette = silhouette_score(X, agg_labels)
    kmeans_vs_agglomerative_ari = adjusted_rand_score(km_labels, agg_labels)

    return {
        "usable_misses": len(miss_df),
        "feature_names": feature_names,
        "k": k,
        "silhouette_by_k": {int(kk): float(v) for kk, v in km_scores.items()},
        "kmeans": {
            "silhouette": float(km_scores[k]),
            "stability_ari_mean": km_ari_mean,
            "stability_ari_std": km_ari_std,
            "clusters": cluster_summary(miss_df, km_labels),
        },
        "agglomerative": {
            "silhouette": float(agg_silhouette),
            "clusters": cluster_summary(miss_df, agg_labels),
        },
        "kmeans_vs_agglomerative_ari": float(kmeans_vs_agglomerative_ari),
    }
