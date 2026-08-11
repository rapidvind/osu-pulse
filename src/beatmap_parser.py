"""Parses a .osu (mania) file for hit-object timestamps per column.

tosu only reports what already happened in-game (combo, misses) - it has no
concept of upcoming notes or note density. That data only exists in the
beatmap file itself, so we read it directly to build a density curve and to
classify the note pattern around a miss (jack vs stream).
"""
import re


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
