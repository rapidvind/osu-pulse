"""Builds the two tidy tables the rest of src/analysis/ works from.

Both are read-only views over the existing schema (db.py) - nothing here
writes to the database. See README.md's "Analytics / ML" section for the
honest limitations of what these features can and can't represent (notably:
no true map-difficulty feature exists for most historical plays, since the
.osu file that pattern/density parsing needs is only still on disk for a
fraction of recorded plays - see collector.py's beatmap_stats work for the
fix that makes this better for *future* plays).
"""
import numpy as np
import pandas as pd

from db import get_conn

# Columns a miss needs to be usable for clustering: a matched key/finger (an
# unmatched miss carries no attribution signal at all) and a non-null
# pattern (only set when the beatmap file was still parseable at play time).
_USABLE_PATTERN = {"jack", "stream", "isolated"}


def load_miss_features():
    """One row per miss that has enough information to be clustered.

    Returns a DataFrame with:
      miss_id, play_id, finger, pattern, combo_before_miss, song_time_ms,
      position_frac (song_time_ms / that play's last_song_time_ms, i.e. how
      far into the map the miss landed, 0..1), log_combo (log1p of
      combo_before_miss, since combo is heavily right-skewed).

    Also returns, as DataFrame.attrs['excluded'], a dict of counts for rows
    dropped and why - callers (the dashboard, tests) should surface this so
    "we clustered N misses" doesn't quietly imply N == total_miss_count().
    """
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT m.id AS miss_id, m.play_id, m.finger, m.pattern, "
            "m.combo_before_miss, m.song_time_ms, m.matched, "
            "p.last_song_time_ms "
            "FROM misses m JOIN plays p ON p.id = m.play_id",
            conn,
        )

    total = len(df)
    unmatched = int((df["matched"] == 0).sum())
    df = df[df["matched"] == 1].copy()

    is_usable_pattern = df["pattern"].isin(_USABLE_PATTERN)
    no_pattern = int((~is_usable_pattern).sum())
    df = df[is_usable_pattern].copy()

    no_duration = int((df["last_song_time_ms"].isna() | (df["last_song_time_ms"] <= 0)).sum())
    df = df[df["last_song_time_ms"].notna() & (df["last_song_time_ms"] > 0)].copy()

    df["position_frac"] = (df["song_time_ms"] / df["last_song_time_ms"]).clip(0, 1)
    df["combo_before_miss"] = df["combo_before_miss"].fillna(0)
    df["log_combo"] = np.log1p(df["combo_before_miss"])

    df = df.drop(columns=["matched", "last_song_time_ms"]).reset_index(drop=True)
    df.attrs["excluded"] = {
        "total_misses": total,
        "unmatched": unmatched,
        "no_usable_pattern": no_pattern,
        "no_play_duration": no_duration,
        "usable": len(df),
    }
    return df


def load_play_features():
    """One row per play, with the covariates the anomaly/regression modules
    use. miss_count and judged_count are derived here rather than trusted
    from a stored column, so they always match the misses/judgments actually
    on record. session_play_index is the play's 1-based position within its
    own game session (a simple fatigue proxy: "the Nth map attempted that
    session")."""
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT p.id AS play_id, p.game_session_id, p.beatmap_id, "
            "p.accuracy, p.max_combo, p.failed, p.prior_best_miss_count, "
            "(SELECT COUNT(*) FROM misses m WHERE m.play_id = p.id) AS miss_count, "
            "(SELECT COUNT(*) FROM judgments j WHERE j.play_id = p.id) AS judged_count "
            "FROM plays p ORDER BY p.game_session_id, p.id",
            conn,
        )

    df["failed"] = df["failed"].fillna(0).astype(int)
    df["session_play_index"] = df.groupby("game_session_id").cumcount() + 1
    df["miss_rate"] = np.where(df["judged_count"] > 0, df["miss_count"] / df["judged_count"], np.nan)

    df.attrs["excluded"] = {"total_plays": len(df)}
    return df
