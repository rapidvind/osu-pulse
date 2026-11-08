"""Tests for beatmap_parser.resolve_background_path - the containment check
guarding /beatmap-image against a path traversal / arbitrary file read via
an unsanitised .osu background filename (GH issue #2)."""
import os

from beatmap_parser import resolve_background_path


def _make_song_folder(tmp_path):
    base = tmp_path / "Songs" / "123 Some Artist - Some Song"
    base.mkdir(parents=True)
    (base / "bg.jpg").write_bytes(b"fake-jpg-bytes")
    # A secret file outside the beatmap's own folder, at the Songs root.
    (tmp_path / "Songs" / "secret.png").write_bytes(b"fake-secret-bytes")
    return base


def test_normal_filename_resolves_inside_base(tmp_path):
    base = _make_song_folder(tmp_path)

    resolved = resolve_background_path(str(base), "bg.jpg")

    assert resolved == str((base / "bg.jpg").resolve())


def test_relative_traversal_is_rejected(tmp_path):
    base = _make_song_folder(tmp_path)

    resolved = resolve_background_path(str(base), "../secret.png")

    assert resolved is None


def test_absolute_path_is_rejected(tmp_path):
    base = _make_song_folder(tmp_path)
    outside_secret = tmp_path / "Songs" / "secret.png"

    resolved = resolve_background_path(str(base), str(outside_secret))

    assert resolved is None


def test_encoded_traversal_is_not_decoded_or_escaped(tmp_path):
    base = _make_song_folder(tmp_path)
    real_secret = str((tmp_path / "Songs" / "secret.png").resolve())

    # "%2e%2e" must stay a literal string, not get decoded into "..". If it
    # were decoded, this would resolve to the real secret.png one level up;
    # left literal, it's just a nonexistent "%2e%2e" subdirectory that is
    # still contained within base.
    resolved = resolve_background_path(str(base), "%2e%2e/%2e%2e/secret.png")

    assert resolved != real_secret
    if resolved is not None:
        assert resolved.startswith(str(base))


def test_non_image_extension_is_rejected(tmp_path):
    base = _make_song_folder(tmp_path)
    (base / "notes.osu").write_text("[Events]\n")

    resolved = resolve_background_path(str(base), "notes.osu")

    assert resolved is None
