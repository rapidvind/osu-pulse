import os
import sqlite3
import time

import db
import settings
from beatmap_parser import classify_pattern, compute_beatmap_stats, parse_mania_beatmap, parse_mania_difficulty
from config import MISS_ATTRIBUTION_WINDOW
from key_listener import KeyListener
from tosu_client import TosuClient

# Confirmed against a live tosu v2 payload (Aug 2026 build):
#   state.name == "play" while actively playing (tosu source: GameState enum)
#   beatmap.time.live is the current song position in ms
#   directPath.beatmapFile is RELATIVE to folders.songs, not absolute
#   play.mode.name == "mania" identifies the mode (osu/taiko/catch/mania)
#   play.hits keys are JSON strings ("0", "50", ...), not ints
#   profile.pp / profile.globalRank (tosu source: Profile interface, v2.ts)
PLAYING_STATE = "play"
MANIA_MODE = "mania"
SONG_TIME_PATHS = [("beatmap", "time", "live")]
PP_PATH = ("profile", "pp")
RANK_PATH = ("profile", "globalRank")

# osu!mania accuracy weights, straight from tosu's own calculateAccuracy()
# (packages/tosu/src/utils/calculators.ts, mode 3 / mirrors rosu-pp): stable
# ScoreV1 weights perfect(geki)=60, great(300)=60, good(katu/200)=40, ok(100)=20,
# meh(50)=10, miss=0, out of a max of 60 per note. Loss = 1 - weight/60.
# geki and 300 both score 100% for accuracy under ScoreV1 (no loss) - only
# the ScoreV2 mod differentiates them (61 vs 60), which we don't special-case.
# geki/300 ARE tracked (loss 0.0) despite costing nothing - a correct running
# accuracy curve needs the total note count, not just the lossy ones.
JUDGMENT_LOSS_FRACTION = {
    "geki": 0.0,
    "300": 0.0,
    "katu": 1 - 40 / 60,
    "100": 1 - 20 / 60,
    "50": 1 - 10 / 60,
    "0": 1.0,
}


def _dig(data, *paths):
    for path in paths:
        node = data
        ok = True
        for key in path:
            if not isinstance(node, dict) or key not in node:
                ok = False
                break
            node = node[key]
        if ok and node is not None:
            return node
    return None


class Collector:
    """Watches tosu state for new misses (play.hits["0"] incrementing) and
    attributes each one to the most recently pressed tracked key, via the
    KeyListener's rolling buffer.

    Two levels of grouping: a game_session spans one continuous osu!-open
    run (approximated by our websocket connection lifetime - tosu exposes
    no real process start/end time), and each game_session contains many
    plays, one per map attempt.
    """

    def __init__(self):
        self.key_to_finger = settings.get_key_to_finger()
        # Column order assumed to match the left-to-right key order in the
        # mapping (a=col0, s=col1, ...). Only used for pattern classification.
        self.key_to_column = {key: i for i, key in enumerate(self.key_to_finger)}

        self.key_listener = KeyListener(self.key_to_finger)
        self.tosu = TosuClient(
            on_update=self._on_update,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
        )

        self._game_session_id = None
        self._play_id = None
        self._current_beatmap_id = None
        self._last_miss_count = None
        self._last_state = None
        self._last_pp = None
        self._last_rank = None
        self._last_recorded_song_time_ms = None
        self._last_combo = None
        self._last_failed = None
        self._last_accuracy = None
        self._last_max_combo = None
        self._last_hit_counts = {}  # judgment -> last observed cumulative count
        self._beatmap_cache = {}  # beatmap_id -> (column_count, hit_objects)

    def start(self):
        db.init_db()
        self.key_listener.start()
        self.tosu.start()

    def stop(self):
        self.key_listener.stop()
        self.tosu.stop()

    def is_playing(self):
        """True while tosu reports an active osu!mania play - used to decide
        whether the dashboard should auto-jump viewers to the live play."""
        return self._last_state == PLAYING_STATE

    def reload_keys(self):
        """Called after the dashboard's key-settings form saves a new
        mapping, so a running collector picks it up without a restart."""
        self.key_to_finger = settings.get_key_to_finger()
        self.key_to_column = {key: i for i, key in enumerate(self.key_to_finger)}
        self.key_listener.set_keys(self.key_to_finger)

    def _on_connect(self):
        self._game_session_id = db.start_game_session()
        self._play_id = None
        self._current_beatmap_id = None
        self._last_pp = None
        self._last_rank = None

    def _on_disconnect(self):
        """Fires when the tosu websocket connection drops - osu! (or tosu)
        closed, or we're shutting down ourselves. Either way, that's the
        real end of this game session (see TosuClient's docstring)."""
        self.end_session()

    def end_session(self):
        if self._game_session_id is not None:
            db.end_game_session(self._game_session_id)
            self._game_session_id = None

    def _on_update(self, data):
        if self._game_session_id is None:
            # on_connect should have already fired, but guard in case a
            # stray update arrives before the connect callback runs
            self._game_session_id = db.start_game_session()

        # PP/rank are available in every state (menu, results, play, ...),
        # not just while actively playing - track them continuously so the
        # session's "ending" snapshot reflects wherever the player actually
        # left off, not just their last note hit.
        pp = _dig(data, PP_PATH)
        rank = _dig(data, RANK_PATH)
        if (pp is not None or rank is not None) and (pp, rank) != (self._last_pp, self._last_rank):
            self._last_pp, self._last_rank = pp, rank
            db.update_session_profile(self._game_session_id, pp, rank)

        state_name = data.get("state", {}).get("name")
        play = data.get("play", {}) or {}
        beatmap = data.get("beatmap", {}) or {}

        if state_name != PLAYING_STATE or play.get("mode", {}).get("name") != MANIA_MODE:
            self._last_state = state_name
            self._last_miss_count = None
            return

        beatmap_id = beatmap.get("id")
        if beatmap_id != self._current_beatmap_id or self._play_id is None:
            self._current_beatmap_id = beatmap_id
            beatmap_path = self._resolve_beatmap_path(data)
            background_path = self._resolve_songs_relative_path(data, "beatmapBackground")
            self._play_id = db.start_play(
                self._game_session_id,
                beatmap_id,
                beatmap.get("title"),
                beatmap.get("version"),
                beatmap_path,
                background_path,
            )
            self._last_miss_count = None
            self._last_recorded_song_time_ms = None
            self._last_combo = None
            self._last_failed = None
            self._last_accuracy = None
            self._last_max_combo = None
            self._last_hit_counts = {}
            self._ensure_beatmap_parsed(beatmap_id, beatmap_path)

        hits = play.get("hits", {}) or {}
        miss_count = hits.get("0")  # JSON object keys are always strings, not ints
        combo_current = play.get("combo", {}).get("current")
        song_time_ms = _dig(data, *SONG_TIME_PATHS)
        failed = play.get("failed")

        if failed is not None and failed != self._last_failed:
            self._last_failed = failed
            db.update_play_failed(self._play_id, failed)

        accuracy = play.get("accuracy")
        max_combo = play.get("combo", {}).get("max")
        if (accuracy, max_combo) != (self._last_accuracy, self._last_max_combo):
            self._last_accuracy = accuracy
            self._last_max_combo = max_combo
            db.update_play_stats(self._play_id, accuracy, max_combo)

        # Throttle: only worth a write once progress has moved meaningfully.
        if song_time_ms is not None and (
            self._last_recorded_song_time_ms is None
            or song_time_ms - self._last_recorded_song_time_ms >= 1000
        ):
            self._last_recorded_song_time_ms = song_time_ms
            db.update_play_progress(self._play_id, song_time_ms)

        self._record_judgment_deltas(hits, song_time_ms)

        if miss_count is None:
            return

        if self._last_miss_count is not None and miss_count > self._last_miss_count:
            # combo.current in THIS tick already reflects the post-miss reset
            # (osu! resets combo atomically with the miss) - the streak that
            # actually got broken is whatever combo was on the PRIOR tick.
            combo_before_miss = self._last_combo
            new_misses = miss_count - self._last_miss_count
            for _ in range(new_misses):
                self._record_miss(combo_before_miss, song_time_ms)

        self._last_miss_count = miss_count
        self._last_combo = combo_current
        self._last_state = state_name

    def _resolve_beatmap_path(self, data):
        return self._resolve_songs_relative_path(data, "beatmapFile")

    def _resolve_songs_relative_path(self, data, direct_path_key):
        relative = _dig(data, ("directPath", direct_path_key))
        songs_root = _dig(data, ("folders", "songs"))
        if not relative or not songs_root:
            return None
        return os.path.join(songs_root, relative)

    def _ensure_beatmap_parsed(self, beatmap_id, beatmap_path):
        if beatmap_id in self._beatmap_cache or not beatmap_path:
            return
        if not os.path.isfile(beatmap_path):
            return
        try:
            column_count, hit_objects = parse_mania_beatmap(beatmap_path)
            self._beatmap_cache[beatmap_id] = (column_count, hit_objects)
        except (OSError, ValueError):
            return
        self._record_beatmap_stats(beatmap_id, beatmap_path, column_count, hit_objects)

    def _record_beatmap_stats(self, beatmap_id, beatmap_path, column_count, hit_objects):
        """Persists map-level stats (note density, pattern mix, CS/OD/AR/HP)
        the first time a beatmap's .osu file is successfully parsed, so
        future analysis (src/analysis/regression.py) has a real difficulty
        feature to use even after this file is gone from disk - see
        db.py's beatmap_stats table docstring. Best-effort: a failure here
        shouldn't break collection of the play itself."""
        stats = compute_beatmap_stats(column_count, hit_objects)
        if stats is None:
            return
        try:
            stats.update(parse_mania_difficulty(beatmap_path))
        except (OSError, ValueError):
            pass
        try:
            db.upsert_beatmap_stats(beatmap_id, stats)
        except sqlite3.Error:
            pass

    def _record_judgment_deltas(self, hits, song_time_ms):
        """Logs every judgment (not just misses - 50s, 100s, and 'good'/katu
        all cost accuracy too, and perfects are needed to compute a correct
        running accuracy curve) for the accuracy-over-time chart. Uses the
        same increment-watching technique as miss detection, independently
        per judgment type."""
        for judgment, loss in JUDGMENT_LOSS_FRACTION.items():
            current = hits.get(judgment)
            if current is None:
                continue
            last = self._last_hit_counts.get(judgment)
            if last is not None and current > last:
                for _ in range(current - last):
                    db.log_judgment(self._play_id, judgment, loss, song_time_ms)
            self._last_hit_counts[judgment] = current

    def _record_miss(self, combo_before_miss, song_time_ms):
        now = time.monotonic()
        match = self.key_listener.most_recent_key_before(now, MISS_ATTRIBUTION_WINDOW)
        pattern = self._classify(song_time_ms, match[0] if match else None)

        if match:
            key, _ = match
            finger = self.key_to_finger.get(key)
            db.log_miss(self._play_id, key, finger, combo_before_miss, song_time_ms, pattern, matched=True)
        else:
            db.log_miss(self._play_id, None, None, combo_before_miss, song_time_ms, pattern, matched=False)

    def _classify(self, song_time_ms, key):
        if song_time_ms is None or key is None:
            return None
        cached = self._beatmap_cache.get(self._current_beatmap_id)
        if not cached:
            return None
        _, hit_objects = cached
        column = self.key_to_column.get(key)
        if column is None:
            return None
        return classify_pattern(hit_objects, song_time_ms, column)


if __name__ == "__main__":
    c = Collector()
    c.start()
    print("Collector running. Waiting for tosu + osu!mania... Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        c.stop()
