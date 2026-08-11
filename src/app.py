import os
import threading
import webbrowser

from flask import Flask, abort, jsonify, render_template, request, send_file

import db
import progress
import settings
from beatmap_parser import density_curve, parse_background_filename, parse_mania_beatmap
from collector import Collector
from config import FLASK_PORT
from tosu_launcher import ensure_tosu_running, stop_tosu_if_we_started_it

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
collector = Collector()


def _get_hit_objects(beatmap_id, beatmap_path):
    """collector._beatmap_cache only gets populated in memory when a play
    STARTS during the current process's lifetime - after a restart, a map
    played in a previous run has no cache entry even though its .osu file
    is still sitting right there on disk. Fall back to parsing it directly
    (and cache the result) instead of silently showing no density data."""
    cached = collector._beatmap_cache.get(beatmap_id)
    if cached:
        return cached[1]
    if beatmap_path and os.path.isfile(beatmap_path):
        try:
            parsed = parse_mania_beatmap(beatmap_path)
            collector._beatmap_cache[beatmap_id] = parsed
            return parsed[1]
        except (OSError, ValueError):
            return None
    return None


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/map/<int:beatmap_id>")
def map_page(beatmap_id):
    return render_template("map.html", beatmap_id=beatmap_id)


@app.route("/play/<int:play_id>")
def play_page(play_id):
    return render_template("play.html", play_id=play_id)


@app.route("/game-session/<int:game_session_id>")
def game_session_page(game_session_id):
    return render_template("game_session.html", game_session_id=game_session_id)


@app.route("/sessions")
def sessions_page():
    return render_template("sessions.html")


@app.route("/api/sessions")
def api_sessions():
    return jsonify(db.all_game_sessions())


@app.route("/ascent")
def ascent_page():
    return render_template("ascent.html")


@app.route("/api/ascent")
def api_ascent():
    return jsonify(progress.get_progress_forecast())


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Stops the key hook, tosu (only if we launched it ourselves), and this
    Flask process. Exists because closing the terminal window running this
    app does NOT stop tosu - it's a detached hidden process by design (see
    tosu_launcher.py) - so users were left with an orphaned tosu.exe."""
    collector.end_session()
    collector.stop()
    stop_tosu_if_we_started_it()
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify({"stopped": True})


@app.route("/api/summary")
def api_summary():
    return jsonify(
        {
            "game_sessions": db.game_session_count(),
            "plays": db.play_count(),
            "total_misses": db.total_miss_count(),
            "by_finger": db.miss_counts_by_finger(),
            "by_key": db.miss_counts_by_key(),
            "by_beatmap": db.misses_by_beatmap(),
            "recent": db.recent_misses(),
        }
    )


@app.route("/api/beatmaps")
def api_beatmaps():
    return jsonify(db.all_beatmaps())


@app.route("/api/settings/keys", methods=["GET"])
def api_get_keys():
    return jsonify({"key_to_finger": settings.get_key_to_finger()})


@app.route("/api/settings/keys", methods=["POST"])
def api_set_keys():
    body = request.get_json(silent=True) or {}
    mapping = body.get("key_to_finger")
    try:
        saved = settings.set_key_to_finger(mapping)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    collector.reload_keys()
    return jsonify({"key_to_finger": saved})


@app.route("/api/beatmap/<int:beatmap_id>", methods=["DELETE"])
def api_delete_beatmap(beatmap_id):
    db.delete_beatmap(beatmap_id)
    return jsonify({"deleted": True})


@app.route("/api/play/<int:play_id>", methods=["DELETE"])
def api_delete_play(play_id):
    db.delete_play(play_id)
    return jsonify({"deleted": True})


@app.route("/api/game-session/<int:game_session_id>", methods=["DELETE"])
def api_delete_game_session(game_session_id):
    db.delete_game_session(game_session_id)
    return jsonify({"deleted": True})


@app.route("/api/game-session/<int:game_session_id>/name", methods=["POST"])
def api_rename_game_session(game_session_id):
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name can't be empty."}), 400
    if len(name) > 60:
        return jsonify({"error": "Name is too long (60 characters max)."}), 400
    db.rename_game_session(game_session_id, name)
    return jsonify({"name": name})


@app.route("/api/game-session/<int:game_session_id>/export")
def api_export_game_session(game_session_id):
    data = db.export_game_session(game_session_id)
    if data is None:
        abort(404)
    resp = jsonify(data)
    resp.headers["Content-Disposition"] = f"attachment; filename=osu-session-{game_session_id}.json"
    return resp


@app.route("/api/game-session/import", methods=["POST"])
def api_import_game_session():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get("format") != "osu-analytics-session":
        return jsonify({"error": "Not a valid osu-analytics session export file."}), 400
    try:
        new_id = db.import_game_session(data)
    except (KeyError, TypeError) as e:
        return jsonify({"error": f"Malformed session file ({e})."}), 400
    return jsonify({"imported": True, "game_session_id": new_id})


@app.route("/beatmap-image/<int:beatmap_id>")
def beatmap_image(beatmap_id):
    path = db.background_path_for_beatmap(beatmap_id)
    if not path or not os.path.isfile(path):
        path = _resolve_background_fallback(beatmap_id)
    if not path or not os.path.isfile(path):
        abort(404)
    return send_file(path)


def _resolve_background_fallback(beatmap_id):
    """background_path is only recorded from plays made after that column was
    added - beatmaps last played before then have no path in the DB even
    though the .osu file (and its background) is still sitting on disk. Read
    the background filename straight out of the .osu file instead."""
    beatmap_path = db.beatmap_path_for_beatmap(beatmap_id)
    if not beatmap_path or not os.path.isfile(beatmap_path):
        return None
    try:
        bg_filename = parse_background_filename(beatmap_path)
    except OSError:
        return None
    if not bg_filename:
        return None
    return os.path.join(os.path.dirname(beatmap_path), bg_filename)


@app.route("/api/live")
def api_live():
    """Current/most recent play, for a fast-refreshing live view. `active`
    reflects whether a play is happening right now (vs. just the last one
    recorded) - used by the dashboard to auto-switch viewers to it."""
    play_id = db.latest_play_id()
    if play_id is None:
        return jsonify({"play": None, "active": False})
    payload = _play_payload(play_id)
    payload["active"] = collector.is_playing()
    return jsonify(payload)


@app.route("/api/play/<int:play_id>")
def api_play(play_id):
    return jsonify(_play_payload(play_id))


def _play_payload(play_id):
    play = db.get_play(play_id)
    if not play:
        return {"play": None}
    misses = db.misses_for_play(play_id)
    judgments = db.judgments_for_play(play_id)

    hit_objects = _get_hit_objects(play["beatmap_id"], play.get("beatmap_path"))
    density = density_curve(hit_objects) if hit_objects else []

    return {
        "play": play,
        "misses": misses,
        "judgments": judgments,
        "density": density,
    }


@app.route("/api/map/<int:beatmap_id>")
def api_map(beatmap_id):
    plays = db.plays_for_beatmap(beatmap_id)  # already ordered latest-first

    # Density-vs-misses/accuracy-loss charts show ONE play at a time (default
    # latest), not every play combined - a combined view mixes note timings
    # across potentially-different mod speeds/attempts into one meaningless
    # blob. The map-level tiles below still aggregate across all plays.
    requested_play_id = request.args.get("play_id", type=int)
    selected_play = None
    if plays:
        selected_play = next((p for p in plays if p["id"] == requested_play_id), plays[0])
    selected_play_id = selected_play["id"] if selected_play else None

    hit_objects = _get_hit_objects(beatmap_id, selected_play["beatmap_path"] if selected_play else None)
    density = density_curve(hit_objects) if hit_objects else []

    misses = db.misses_for_play(selected_play_id) if selected_play_id else []
    judgments = db.judgments_for_play(selected_play_id) if selected_play_id else []

    total_misses = sum(p["miss_count"] for p in plays)

    return jsonify({
        "plays": plays,
        "density": density,
        "misses": misses,
        "judgments": judgments,
        "selected_play_id": selected_play_id,
        "total_misses": total_misses,
    })


@app.route("/api/game-session/<int:game_session_id>")
def api_game_session(game_session_id):
    game_session = db.get_game_session(game_session_id)
    plays = db.plays_for_game_session(game_session_id)
    return jsonify({"game_session": game_session, "plays": plays})


@app.route("/api/live-game-session")
def api_live_game_session():
    game_session_id = db.latest_game_session_id()
    if game_session_id is None:
        return jsonify({"game_session": None})
    game_session = db.get_game_session(game_session_id)
    plays = db.plays_for_game_session(game_session_id)
    return jsonify({"game_session": game_session, "plays": plays})


def main():
    ensure_tosu_running()
    collector.start()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{FLASK_PORT}")).start()
    app.run(host="127.0.0.1", port=FLASK_PORT, debug=False)


if __name__ == "__main__":
    main()
