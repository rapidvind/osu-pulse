"""Parses a .osu (mania) file for hit-object timestamps per column.

tosu only reports what already happened in-game (combo, misses) - it has no
concept of upcoming notes or note density. That data only exists in the
beatmap file itself, so we read it directly to build a density curve and to
classify the note pattern around a miss (jack vs stream).
"""
import re
from pathlib import Path

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def parse_mania_beatmap(osu_file_path):
    """Returns (column_count, [(time_ms, column), ...]) sorted by time."""
    column_count = 4
    hit_objects = []
    section = None

    with open(osu_file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue

            if section == "Difficulty" and line.startswith("CircleSize:"):
                column_count = int(float(line.split(":", 1)[1].strip()))

            elif section == "HitObjects":
                parts = line.split(",")
                if len(parts) < 3:
                    continue
                try:
                    x = int(parts[0])
                    time_ms = int(parts[2])
                except ValueError:
                    continue
                column = min(int(x * column_count / 512), column_count - 1)
                hit_objects.append((time_ms, column))

    hit_objects.sort(key=lambda t: t[0])
    return column_count, hit_objects


def parse_background_filename(osu_file_path):
    """Pulls the background image filename out of a .osu file's [Events]
    section (format: `0,0,"bg.jpg",0,0`). Used as a fallback for beatmaps
    played before we started recording background_path directly, where no
    play row has a usable path on disk."""
    with open(osu_file_path, "r", encoding="utf-8", errors="ignore") as f:
        section = None
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if section == "Events":
                parts = line.split(",")
                if len(parts) >= 3 and parts[0] == "0":
                    return parts[2].strip().strip('"')
    return None


def resolve_background_path(base_dir, bg_filename):
    """Resolves bg_filename (pulled straight out of a .osu file's [Events]
    section by parse_background_filename) against base_dir, and returns it
    only if the resolved path stays inside base_dir and has an allowed
    image extension.

    .osu files are routinely downloaded from third-party/community sources,
    so bg_filename is untrusted input - it can contain `../` traversal, an
    absolute path, or a drive letter/UNC prefix. See GH issue #2 (path
    traversal / arbitrary file read in /beatmap-image)."""
    if not bg_filename:
        return None
    base = Path(base_dir).resolve()
    candidate = (base / bg_filename).resolve()
    if not candidate.is_relative_to(base):
        return None
    if candidate.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        return None
    return str(candidate)


def density_curve(hit_objects, bucket_ms=1000):
    """Bucket note counts into fixed-width time windows for a density chart.
    Returns [(bucket_start_ms, note_count), ...]."""
    if not hit_objects:
        return []
    end_time = hit_objects[-1][0]
    buckets = {}
    for time_ms, _ in hit_objects:
        bucket = (time_ms // bucket_ms) * bucket_ms
        buckets[bucket] = buckets.get(bucket, 0) + 1
    return [(b, buckets.get(b, 0)) for b in range(0, end_time + bucket_ms, bucket_ms)]


def classify_pattern(hit_objects, time_ms, column, lookback_ms=600):
    """Best-effort label for the note pattern leading into a given note:
    'jack' if the same column repeated rapidly just before it, 'stream' if
    multiple columns were firing back-to-back, else 'isolated'."""
    window = [ho for ho in hit_objects if time_ms - lookback_ms <= ho[0] < time_ms]
    if not window:
        return "isolated"
    same_column = sum(1 for _, c in window if c == column)
    if same_column >= 2:
        return "jack"
    if len(window) >= 3:
        return "stream"
    return "isolated"


_DIFFICULTY_KEYS = {
    "CircleSize": "circle_size",
    "OverallDifficulty": "overall_difficulty",
    "ApproachRate": "approach_rate",
    "HPDrainRate": "hp_drain_rate",
}


def parse_mania_difficulty(osu_file_path):
    """Pulls the raw [Difficulty] section values out of a .osu file - these
    are the same CS/OD/AR/HP numbers osu! itself shows on the song select
    screen. Not a computed star rating (that needs the full pp calculation
    this app doesn't implement) - just what's directly in the file. Missing
    keys (ApproachRate didn't always exist in older beatmap formats) come
    back as None rather than a guessed default."""
    values = {v: None for v in _DIFFICULTY_KEYS.values()}
    section = None
    with open(osu_file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if section != "Difficulty" or ":" not in line:
                continue
            key, _, raw_value = line.partition(":")
            field = _DIFFICULTY_KEYS.get(key.strip())
            if field is None:
                continue
            try:
                values[field] = float(raw_value.strip())
            except ValueError:
                pass
    return values


def compute_pattern_mix(hit_objects, lookback_ms=600):
    """Same jack/stream/isolated classification as classify_pattern(), but
    computed once for every note in the map instead of one note at a time -
    classify_pattern's per-call full-list filter is fine for a single miss
    lookup, but re-running it per note would be O(n^2) over a whole map.
    This keeps the same windowing logic (notes in (time_ms - lookback_ms,
    time_ms)) via a two-pointer sweep over the time-sorted list instead.

    Returns {"jack_frac": .., "stream_frac": .., "isolated_frac": ..} (each
    a share of the map's total note count), or all-None fractions for a map
    with fewer than 2 notes (not enough to classify anything)."""
    if len(hit_objects) < 2:
        return {"jack_frac": None, "stream_frac": None, "isolated_frac": None}

    counts = {"jack": 0, "stream": 0, "isolated": 0}
    left = 0
    for i, (t, column) in enumerate(hit_objects):
        while hit_objects[left][0] < t - lookback_ms:
            left += 1
        window = hit_objects[left:i]  # all have time < t by construction
        same_column = sum(1 for _, c in window if c == column)
        if same_column >= 2:
            counts["jack"] += 1
        elif len(window) >= 3:
            counts["stream"] += 1
        else:
            counts["isolated"] += 1

    total = len(hit_objects)
    return {f"{k}_frac": v / total for k, v in counts.items()}


def compute_beatmap_stats(column_count, hit_objects):
    """Map-level descriptors independent of any particular play - the
    "difficulty" features a regression actually needs (see
    src/analysis/regression.py's docstring), as opposed to the per-miss
    pattern label classify_pattern() produces. Returns None if the map has
    no parseable hit objects at all."""
    if not hit_objects:
        return None

    duration_ms = hit_objects[-1][0]
    note_count = len(hit_objects)
    buckets = density_curve(hit_objects)
    bucket_counts = [c for _, c in buckets] or [0]

    stats = {
        "column_count": column_count,
        "note_count": note_count,
        "duration_ms": duration_ms,
        "notes_per_second": note_count / (duration_ms / 1000) if duration_ms > 0 else None,
        "max_notes_per_second": max(bucket_counts),
    }
    stats.update(compute_pattern_mix(hit_objects))
    return stats
