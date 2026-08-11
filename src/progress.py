"""PP/rank progress tracking and conservative forecasting.

The core idea (see project discussion): predict PP/rank progression across
many game sessions, deliberately conservative, so beating the prediction is
a real but attainable feel-good moment - not a strawman.

Three problems this solves:
1. Which plays are "serious" (an actual attempt) vs a spoof/warmup/instant
   quit that would just pollute the trend. Heuristic: did the player reach
   most of the way through the song? We track the furthest song position
   observed during a play (db.update_play_progress) and compare it to the
   beatmap's actual length (parsed from the .osu file, same parser used for
   density charts).
2. Which game sessions have enough serious plays to "count" toward the
   training data at all.
3. Given qualifying sessions' PP/rank history, produce a conservative
   walk-forward forecast: at each point, fit a trend on everything before
   it, dampen the slope, and predict one step ahead. Comparing that
   prediction to what actually happened is the "did you beat your own
   forecast" chart.
"""
import os
from functools import lru_cache

import db
from beatmap_parser import parse_mania_beatmap
from config import (
    MIN_QUALIFYING_SESSIONS_FOR_PREDICTION,
    MIN_SERIOUS_PLAYS_PER_QUALIFYING_SESSION,
    PREDICTION_DAMPENING_FACTOR,
    SERIOUS_PLAY_COMPLETION_RATIO,
)


@lru_cache(maxsize=512)
def _beatmap_length_ms(beatmap_path):
    """Last hit-object time for a beatmap file, or None if it can't be
    determined (deleted/moved file, or we never had the path). Cached since
    the same beatmap gets checked across many plays and this is a real
    file-parse cost, not a free lookup."""
    if not beatmap_path or not os.path.isfile(beatmap_path):
        return None
    try:
        _, hit_objects = parse_mania_beatmap(beatmap_path)
    except (OSError, ValueError):
        return None
    if not hit_objects:
        return None
    return hit_objects[-1][0]


def is_play_serious(play):
    """None (not just False) when we lack the evidence to decide - such a
    play is excluded from both the numerator and denominator rather than
    counted as a failure, since 'unknown' isn't the same claim as 'spoof'."""
    length = _beatmap_length_ms(play.get("beatmap_path"))
    last_seen = play.get("last_song_time_ms")
    if length is None or last_seen is None or length <= 0:
        return None
    return (last_seen / length) >= SERIOUS_PLAY_COMPLETION_RATIO


def qualifying_game_sessions():
    """Every game session that has enough serious plays to count toward the
    PP/rank training data, in chronological order, each with its ending
    PP/rank snapshot."""
    qualifying = []
    for session in db.all_game_sessions_with_profile():
        plays = db.plays_for_seriousness_check(session["id"])
        serious_count = sum(1 for p in plays if is_play_serious(p) is True)
        if serious_count >= MIN_SERIOUS_PLAYS_PER_QUALIFYING_SESSION:
            qualifying.append({**session, "serious_play_count": serious_count})
    return qualifying


def _linear_fit(xs, ys):
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0, mean_y
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _walk_forward_forecast(values):
    """For each point from MIN_QUALIFYING_SESSIONS_FOR_PREDICTION onward,
    fit a line on every prior point, dampen its slope, and predict this
    point from it. Returns a list aligned to `values`, with None for indices
    too early to have a prediction. Also returns one extra forecast point
    for the session after the last known one (the actual 'what's next')."""
    predictions = [None] * len(values)
    for i in range(MIN_QUALIFYING_SESSIONS_FOR_PREDICTION, len(values)):
        xs = list(range(i))
        ys = values[:i]
        slope, intercept = _linear_fit(xs, ys)
        dampened_slope = slope * PREDICTION_DAMPENING_FACTOR
        # Re-anchor at the last known point rather than the fitted intercept,
        # so the forecast starts from reality instead of drifting off a
        # regression line that may not touch the most recent actual value.
        predictions[i] = values[i - 1] + dampened_slope

    next_point = None
    if len(values) >= MIN_QUALIFYING_SESSIONS_FOR_PREDICTION:
        xs = list(range(len(values)))
        slope, intercept = _linear_fit(xs, values)
        dampened_slope = slope * PREDICTION_DAMPENING_FACTOR
        next_point = values[-1] + dampened_slope

    return predictions, next_point


def get_progress_forecast():
    """Top-level entry point for the dashboard. Returns eligibility status
    plus, once eligible, actual-vs-predicted series for PP and global rank."""
    sessions = qualifying_game_sessions()

    if len(sessions) < MIN_QUALIFYING_SESSIONS_FOR_PREDICTION:
        return {
            "eligible": False,
            "qualifying_sessions": len(sessions),
            "sessions_needed": MIN_QUALIFYING_SESSIONS_FOR_PREDICTION,
        }

    pp_values = [s["ending_pp"] for s in sessions]
    rank_values = [s["ending_rank_global"] for s in sessions]

    pp_predicted, pp_next = _walk_forward_forecast(pp_values)
    rank_predicted, rank_next = _walk_forward_forecast(rank_values)

    points = []
    for i, s in enumerate(sessions):
        points.append({
            "game_session_id": s["id"],
            "started_at": s["started_at"],
            "actual_pp": pp_values[i],
            "predicted_pp": pp_predicted[i],
            "beat_pp_prediction": (
                pp_predicted[i] is not None and pp_values[i] > pp_predicted[i]
            ),
            "actual_rank": rank_values[i],
            "predicted_rank": rank_predicted[i],
            "beat_rank_prediction": (
                rank_predicted[i] is not None and rank_values[i] < rank_predicted[i]
            ),
        })

    return {
        "eligible": True,
        "qualifying_sessions": len(sessions),
        "points": points,
        "next_forecast": {"pp": pp_next, "rank": rank_next},
    }
