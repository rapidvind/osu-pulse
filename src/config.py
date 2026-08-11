import os
import sys

# Key-to-finger mapping now lives in settings.py (settings.json, editable from
# the dashboard) instead of here - see settings.DEFAULT_KEY_TO_FINGER for the
# fallback default.

TOSU_WS_URL = "ws://localhost:24050/websocket/v2"

# Max time (seconds) between a key press and a reported miss for us to attribute
# the miss to that key. tosu polls memory rather than reacting instantly, so this
# needs some slack. Tune down if attribution looks wrong, up if misses go unmatched.
MISS_ATTRIBUTION_WINDOW = 0.35

# --- PP/rank progress prediction -------------------------------------------
# A play counts as "serious" (not a spoof/warmup/instant-quit) if the last
# song position we observed reached at least this fraction of the beatmap's
# total length.
SERIOUS_PLAY_COMPLETION_RATIO = 0.9

# A game session only counts toward the PP/rank training data if it has at
# least this many serious plays.
MIN_SERIOUS_PLAYS_PER_QUALIFYING_SESSION = 3

# The forecast chart only appears once there are at least this many
# qualifying sessions - fitting a trend off fewer points is just noise.
MIN_QUALIFYING_SESSIONS_FOR_PREDICTION = 8

# Conservative bias: the forecast is fit to the recent trend, then projected
# forward at this fraction of that slope. <1.0 makes the prediction easier
# to beat on purpose - see project discussion on the "beat your own forecast"
# motivational mechanic.
PREDICTION_DAMPENING_FACTOR = 0.7

if getattr(sys, "frozen", False):
    # Packaged .exe: keep the database next to the exe itself, not inside
    # PyInstaller's temp extraction dir, so data survives between runs.
    _DATA_DIR = os.path.dirname(sys.executable)
else:
    # Source checkout: this file lives in src/, database sits at the
    # project root regardless of what directory the script is launched from.
    _DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(_DATA_DIR, "osu_analytics.db")
FLASK_PORT = 5151
