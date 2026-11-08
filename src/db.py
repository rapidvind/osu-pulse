import sqlite3
from contextlib import contextmanager

from config import DB_PATH
from namegen import random_session_name

# Three levels: a game_session spans one continuous osu!-open-to-close run
# (approximated by our websocket connection lifetime to tosu, since tosu
# exposes no actual process start/end timestamp). Each game_session contains
# many plays (one per map attempt). Each play contains its misses.
SCHEMA = """
CREATE TABLE IF NOT EXISTS game_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    ending_pp REAL,
    ending_rank_global INTEGER,
    name TEXT
);

CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_session_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    beatmap_id INTEGER,
    beatmap_title TEXT,
    beatmap_version TEXT,
    beatmap_path TEXT,
    background_path TEXT,
    last_song_time_ms INTEGER,
    failed INTEGER,
    accuracy REAL,
    max_combo INTEGER,
    FOREIGN KEY (game_session_id) REFERENCES game_sessions(id)
);

CREATE TABLE IF NOT EXISTS misses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    play_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    key TEXT,
    finger TEXT,
    combo_before_miss INTEGER,
    song_time_ms INTEGER,
    pattern TEXT,
    matched INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (play_id) REFERENCES plays(id)
);

-- Every judgment that isn't a perfect 300/MAX - accuracy loss isn't just
-- misses, so this is a separate, more complete record than `misses` (which
-- exists specifically for key/finger attribution of true misses).
CREATE TABLE IF NOT EXISTS judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    play_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    song_time_ms INTEGER,
    judgment TEXT NOT NULL,
    accuracy_loss REAL NOT NULL,
    FOREIGN KEY (play_id) REFERENCES plays(id)
);

-- Map-level descriptors computed once per beatmap (not per play) straight
-- from its .osu file - see beatmap_parser.compute_beatmap_stats() /
-- parse_mania_difficulty(). Lets the regression in src/analysis/ use real
-- note density/pattern-mix/difficulty features for any play of a beatmap
-- recorded from here on, instead of the judged_count/familiarity proxies
-- it has to fall back to for plays whose .osu file is no longer on disk.
-- Keyed by beatmap_id rather than play_id: these describe the chart
-- itself, not any one attempt at it, so every play of the same beatmap
-- shares one row (INSERT OR REPLACE on re-parse, in case the file changed).
CREATE TABLE IF NOT EXISTS beatmap_stats (
    beatmap_id INTEGER PRIMARY KEY,
    column_count INTEGER,
    note_count INTEGER,
    duration_ms INTEGER,
    notes_per_second REAL,
    max_notes_per_second REAL,
    jack_frac REAL,
    stream_frac REAL,
    isolated_frac REAL,
    circle_size REAL,
    overall_difficulty REAL,
    approach_rate REAL,
    hp_drain_rate REAL,
    computed_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Migrations for DBs created before these columns existed
        for statement in (
            "ALTER TABLE plays ADD COLUMN background_path TEXT",
            "ALTER TABLE plays ADD COLUMN last_song_time_ms INTEGER",
            "ALTER TABLE plays ADD COLUMN failed INTEGER",
            "ALTER TABLE plays ADD COLUMN accuracy REAL",
            "ALTER TABLE plays ADD COLUMN max_combo INTEGER",
            "ALTER TABLE game_sessions ADD COLUMN ending_pp REAL",
            "ALTER TABLE game_sessions ADD COLUMN ending_rank_global INTEGER",
            "ALTER TABLE game_sessions ADD COLUMN name TEXT",
        ):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass

        # Backfill sessions that predate the name column (or were imported
        # without one) - each needs its own random name, not a shared value.
        unnamed_ids = [
            row["id"] for row in conn.execute(
                "SELECT id FROM game_sessions WHERE name IS NULL"
            ).fetchall()
        ]
        for session_id in unnamed_ids:
            conn.execute(
                "UPDATE game_sessions SET name = ? WHERE id = ?",
                (random_session_name(), session_id),
            )

        # DEFAULT_KEY_TO_FINGER used to call the pinky-adjacent fingers
        # "ring" - they're actually "middle" (settings.py). Renames any
        # misses already logged under the old labels so historical data
        # reads correctly too, not just future plays. Idempotent (a no-op
        # once already applied).
        conn.execute("UPDATE misses SET finger = 'left_middle' WHERE finger = 'left_ring'")
        conn.execute("UPDATE misses SET finger = 'right_middle' WHERE finger = 'right_ring'")


# --- game sessions ---------------------------------------------------------

def start_game_session():
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO game_sessions (started_at, name) VALUES (datetime('now'), ?)",
            (random_session_name(),),
        )
        return cur.lastrowid


def rename_game_session(game_session_id, name):
    with get_conn() as conn:
        conn.execute(
            "UPDATE game_sessions SET name = ? WHERE id = ?",
            (name, game_session_id),
        )


def end_game_session(game_session_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE game_sessions SET ended_at = datetime('now') WHERE id = ?",
            (game_session_id,),
        )


def get_game_session(game_session_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM game_sessions WHERE id = ?", (game_session_id,)
        ).fetchone()
        return dict(row) if row else None


def plays_for_game_session(game_session_id):
    with get_conn() as conn:
        rows = conn.execute(
            _NEW_BEST_CTE + "SELECT p.*, f.miss_count, f.is_new_best FROM plays p "
            "JOIN flagged f ON f.play_id = p.id "
            "WHERE p.game_session_id = ? ORDER BY p.id",
            (game_session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def latest_game_session_id():
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM game_sessions ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"] if row else None


def game_session_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM game_sessions").fetchone()["c"]


def all_game_sessions():
    """For the session-history page: every session, newest first, with
    aggregate play/miss counts so the list is useful without a click-through.
    thumb_beatmap_ids is up to the first 4 distinct maps played, in the order
    they were first attempted, for the collapsed thumbnail-stack icon."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT gs.id, gs.name, gs.started_at, gs.ended_at, gs.ending_pp, gs.ending_rank_global, "
            "COUNT(DISTINCT p.id) AS play_count, COUNT(m.id) AS miss_count, "
            "(SELECT GROUP_CONCAT(beatmap_id) FROM ("
            "  SELECT beatmap_id FROM plays p2 WHERE p2.game_session_id = gs.id "
            "  GROUP BY beatmap_id ORDER BY MIN(p2.id) LIMIT 4"
            ")) AS thumb_beatmap_ids "
            "FROM game_sessions gs "
            "LEFT JOIN plays p ON p.game_session_id = gs.id "
            "LEFT JOIN misses m ON m.play_id = p.id "
            "GROUP BY gs.id ORDER BY gs.id DESC"
        ).fetchall()
        sessions = [dict(r) for r in rows]
        for s in sessions:
            ids = s.pop("thumb_beatmap_ids")
            s["thumb_beatmap_ids"] = [int(x) for x in ids.split(",")] if ids else []
        return sessions


def delete_game_session(game_session_id):
    """Deletes every play (and its misses/judgments) in this session, then
    the session itself."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM misses WHERE play_id IN (SELECT id FROM plays WHERE game_session_id = ?)",
            (game_session_id,),
        )
        conn.execute(
            "DELETE FROM judgments WHERE play_id IN (SELECT id FROM plays WHERE game_session_id = ?)",
            (game_session_id,),
        )
        conn.execute("DELETE FROM plays WHERE game_session_id = ?", (game_session_id,))
        conn.execute("DELETE FROM game_sessions WHERE id = ?", (game_session_id,))


def export_game_session(game_session_id):
    """Full nested dump of one game session (its plays, and each play's
    misses/judgments) for the export-to-file feature. Local filesystem paths
    (beatmap_path/background_path) are deliberately omitted - they point
    nowhere useful on whoever imports the file, and would otherwise leak the
    exporter's local username/directory layout."""
    gs = get_game_session(game_session_id)
    if not gs:
        return None
    export_plays = []
    for p in plays_for_game_session(game_session_id):
        export_plays.append({
            "started_at": p["started_at"],
            "beatmap_id": p["beatmap_id"],
            "beatmap_title": p["beatmap_title"],
            "beatmap_version": p["beatmap_version"],
            "last_song_time_ms": p["last_song_time_ms"],
            "failed": p["failed"],
            "accuracy": p["accuracy"],
            "max_combo": p["max_combo"],
            "misses": [
                {k: m[k] for k in ("ts", "key", "finger", "combo_before_miss", "song_time_ms", "pattern", "matched")}
                for m in misses_for_play(p["id"])
            ],
            "judgments": [
                {k: j[k] for k in ("ts", "song_time_ms", "judgment", "accuracy_loss")}
                for j in judgments_for_play(p["id"])
            ],
        })
    return {
        "format": "osu-analytics-session",
        "version": 1,
        "game_session": {
            "name": gs["name"],
            "started_at": gs["started_at"],
            "ended_at": gs["ended_at"],
            "ending_pp": gs["ending_pp"],
            "ending_rank_global": gs["ending_rank_global"],
        },
        "plays": export_plays,
    }


def import_game_session(data):
    """Reconstructs a game session (and its plays/misses/judgments) from an
    export_game_session()-shaped dict, as new rows with fresh ids. Raises
    (KeyError, TypeError) on malformed input - callers should catch these
    and turn them into a 400."""
    gs = data["game_session"]
    plays = data["plays"]
    if not isinstance(gs, dict) or not isinstance(plays, list):
        raise TypeError("expected 'game_session' object and 'plays' list")

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO game_sessions (started_at, ended_at, ending_pp, ending_rank_global, name) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                gs["started_at"],
                gs.get("ended_at"),
                gs.get("ending_pp"),
                gs.get("ending_rank_global"),
                gs.get("name") or random_session_name(),
            ),
        )
        new_session_id = cur.lastrowid

        for play in plays:
            if not isinstance(play, dict):
                raise TypeError("each play must be an object")
            cur = conn.execute(
                "INSERT INTO plays (game_session_id, started_at, beatmap_id, beatmap_title, "
                "beatmap_version, last_song_time_ms, failed, accuracy, max_combo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_session_id,
                    play["started_at"],
                    play.get("beatmap_id"),
                    play.get("beatmap_title"),
                    play.get("beatmap_version"),
                    play.get("last_song_time_ms"),
                    play.get("failed"),
                    play.get("accuracy"),
                    play.get("max_combo"),
                ),
            )
            new_play_id = cur.lastrowid

            for miss in play.get("misses", []):
                conn.execute(
                    "INSERT INTO misses (play_id, ts, key, finger, combo_before_miss, song_time_ms, pattern, matched) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_play_id,
                        miss["ts"],
                        miss.get("key"),
                        miss.get("finger"),
                        miss.get("combo_before_miss"),
                        miss.get("song_time_ms"),
                        miss.get("pattern"),
                        int(bool(miss.get("matched", 1))),
                    ),
                )

            for judgment in play.get("judgments", []):
                conn.execute(
                    "INSERT INTO judgments (play_id, ts, song_time_ms, judgment, accuracy_loss) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        new_play_id,
                        judgment["ts"],
                        judgment.get("song_time_ms"),
                        judgment["judgment"],
                        judgment["accuracy_loss"],
                    ),
                )

        return new_session_id


def update_session_profile(game_session_id, pp, rank_global):
    """Called on every tosu tick during a session - keeps the session's
    ending PP/rank fresh with whatever the latest known value is, so
    whenever the session actually ends we already have its final state."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE game_sessions SET ending_pp = ?, ending_rank_global = ? WHERE id = ?",
            (pp, rank_global, game_session_id),
        )


def all_game_sessions_with_profile():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, started_at, ending_pp, ending_rank_global FROM game_sessions "
            "WHERE ending_pp IS NOT NULL ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def plays_for_seriousness_check(game_session_id):
    """Minimal fields needed to decide which plays were 'serious' (not a
    spoof/warmup/instant-quit) - see progress.py."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, beatmap_path, last_song_time_ms FROM plays WHERE game_session_id = ?",
            (game_session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# "New best" = fewest misses ever recorded for that beatmap, up to and
# including this play, evaluated across ALL plays/game sessions for that
# beatmap (not just whatever subset a given view happens to be showing).
# Failed attempts are excluded from the comparison entirely - a fail with
# few misses (e.g. died early, before racking many up) must never outrank a
# genuine clear, and must never itself be flagged as a "best".
_NEW_BEST_CTE = """
WITH play_misses AS (
    SELECT p.id AS play_id, p.beatmap_id, COUNT(m.id) AS miss_count,
        COALESCE(p.failed, 0) AS failed
    FROM plays p LEFT JOIN misses m ON m.play_id = p.id
    GROUP BY p.id
),
best_among_clears AS (
    SELECT play_id,
        miss_count = MIN(miss_count) OVER (
            PARTITION BY beatmap_id ORDER BY play_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS is_new_best
    FROM play_misses
    WHERE failed = 0
),
flagged AS (
    SELECT pm.play_id, pm.miss_count, COALESCE(bac.is_new_best, 0) AS is_new_best
    FROM play_misses pm
    LEFT JOIN best_among_clears bac ON bac.play_id = pm.play_id
)
"""


# --- plays (one per map attempt) -------------------------------------------

def start_play(game_session_id, beatmap_id, beatmap_title, beatmap_version, beatmap_path=None, background_path=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO plays (game_session_id, started_at, beatmap_id, beatmap_title, beatmap_version, beatmap_path, background_path) "
            "VALUES (?, datetime('now'), ?, ?, ?, ?, ?)",
            (game_session_id, beatmap_id, beatmap_title, beatmap_version, beatmap_path, background_path),
        )
        return cur.lastrowid


def update_play_progress(play_id, last_song_time_ms):
    """Called on every tosu tick during a play - keeps the furthest song
    position we've seen so far, so a play that quits early doesn't look
    'serious' just because it happened to log a miss late (or no misses at
    all, in which case this is the ONLY way we know how far they got)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE plays SET last_song_time_ms = ? WHERE id = ? "
            "AND (last_song_time_ms IS NULL OR ? > last_song_time_ms)",
            (last_song_time_ms, play_id, last_song_time_ms),
        )


def update_play_stats(play_id, accuracy, max_combo):
    """accuracy/max_combo come straight from tosu's own play.accuracy /
    play.combo.max - authoritative, computed by tosu itself from the same
    formula osu! uses. Kept separate from our own event-log-derived accuracy
    trajectory (used only for the chart), since that reconstruction can
    drift if any tosu ticks are missed - this is the number that should
    always be trusted for the headline stat."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE plays SET accuracy = ?, max_combo = ? WHERE id = ?",
            (accuracy, max_combo, play_id),
        )


def update_play_failed(play_id, failed):
    with get_conn() as conn:
        conn.execute("UPDATE plays SET failed = ? WHERE id = ?", (int(bool(failed)), play_id))


def background_path_for_beatmap(beatmap_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT background_path FROM plays WHERE beatmap_id = ? AND background_path IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (beatmap_id,),
        ).fetchone()
        return row["background_path"] if row else None


def beatmap_path_for_beatmap(beatmap_id):
    """Any known .osu file path for this beatmap - fallback source for
    resolving its background image when no play recorded background_path
    directly (plays recorded before that column existed)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT beatmap_path FROM plays WHERE beatmap_id = ? AND beatmap_path IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (beatmap_id,),
        ).fetchone()
        return row["beatmap_path"] if row else None


def get_play(play_id):
    with get_conn() as conn:
        row = conn.execute(
            _NEW_BEST_CTE + "SELECT p.*, f.miss_count, f.is_new_best FROM plays p "
            "JOIN flagged f ON f.play_id = p.id WHERE p.id = ?",
            (play_id,),
        ).fetchone()
        return dict(row) if row else None


def misses_for_play(play_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM misses WHERE play_id = ? ORDER BY id", (play_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def plays_for_beatmap(beatmap_id):
    with get_conn() as conn:
        rows = conn.execute(
            _NEW_BEST_CTE + "SELECT p.*, f.miss_count, f.is_new_best FROM plays p "
            "JOIN flagged f ON f.play_id = p.id "
            "WHERE p.beatmap_id = ? ORDER BY p.id DESC",
            (beatmap_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def all_beatmaps():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.beatmap_id, p.beatmap_title, p.beatmap_version, COUNT(DISTINCT p.id) AS plays, "
            "COUNT(m.id) AS misses "
            "FROM plays p LEFT JOIN misses m ON m.play_id = p.id "
            "GROUP BY p.beatmap_id ORDER BY MAX(p.id) DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_beatmap_stats(beatmap_id, stats):
    """stats is a dict shaped like beatmap_parser.compute_beatmap_stats()'s
    output merged with parse_mania_difficulty()'s - any keys matching a
    beatmap_stats column are written, anything else is ignored so callers
    can pass extra context without this needing to know about it."""
    columns = [
        "column_count", "note_count", "duration_ms", "notes_per_second", "max_notes_per_second",
        "jack_frac", "stream_frac", "isolated_frac",
        "circle_size", "overall_difficulty", "approach_rate", "hp_drain_rate",
    ]
    values = [stats.get(c) for c in columns]
    with get_conn() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO beatmap_stats (beatmap_id, {', '.join(columns)}, computed_at) "
            f"VALUES (?, {', '.join('?' for _ in columns)}, datetime('now'))",
            (beatmap_id, *values),
        )


def beatmap_stats_for(beatmap_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM beatmap_stats WHERE beatmap_id = ?", (beatmap_id,)
        ).fetchone()
        return dict(row) if row else None


def all_beatmap_stats():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM beatmap_stats").fetchall()
        return [dict(r) for r in rows]


def delete_beatmap(beatmap_id):
    """Deletes every play (and its misses/judgments) recorded for this beatmap."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM misses WHERE play_id IN (SELECT id FROM plays WHERE beatmap_id = ?)",
            (beatmap_id,),
        )
        conn.execute(
            "DELETE FROM judgments WHERE play_id IN (SELECT id FROM plays WHERE beatmap_id = ?)",
            (beatmap_id,),
        )
        conn.execute("DELETE FROM plays WHERE beatmap_id = ?", (beatmap_id,))
        conn.execute("DELETE FROM beatmap_stats WHERE beatmap_id = ?", (beatmap_id,))


def delete_play(play_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM misses WHERE play_id = ?", (play_id,))
        conn.execute("DELETE FROM judgments WHERE play_id = ?", (play_id,))
        conn.execute("DELETE FROM plays WHERE id = ?", (play_id,))


def log_judgment(play_id, judgment, accuracy_loss, song_time_ms=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO judgments (play_id, ts, song_time_ms, judgment, accuracy_loss) "
            "VALUES (?, datetime('now'), ?, ?, ?)",
            (play_id, song_time_ms, judgment, accuracy_loss),
        )


def judgments_for_play(play_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM judgments WHERE play_id = ? ORDER BY id", (play_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def latest_play_id():
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM plays ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"] if row else None


def play_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM plays").fetchone()["c"]


# --- misses ------------------------------------------------------------

def log_miss(play_id, key, finger, combo_before_miss, song_time_ms=None, pattern=None, matched=True):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO misses (play_id, ts, key, finger, combo_before_miss, song_time_ms, pattern, matched) "
            "VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)",
            (play_id, key, finger, combo_before_miss, song_time_ms, pattern, int(matched)),
        )


def miss_counts_by_finger():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT COALESCE(finger, 'unmatched') AS finger, COUNT(*) AS count "
            "FROM misses GROUP BY finger ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def miss_counts_by_key():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT COALESCE(key, 'unmatched') AS key, COUNT(*) AS count "
            "FROM misses GROUP BY key ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def misses_by_beatmap():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.beatmap_id, p.beatmap_title, p.beatmap_version, COUNT(m.id) AS count "
            "FROM misses m JOIN plays p ON m.play_id = p.id "
            "GROUP BY p.beatmap_id ORDER BY count DESC LIMIT 25"
        ).fetchall()
        return [dict(r) for r in rows]


def recent_misses(limit=50):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT m.ts, m.key, m.finger, m.combo_before_miss, m.play_id, "
            "p.beatmap_id, p.beatmap_title, p.beatmap_version "
            "FROM misses m JOIN plays p ON m.play_id = p.id "
            "ORDER BY m.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def total_miss_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM misses").fetchone()["c"]
