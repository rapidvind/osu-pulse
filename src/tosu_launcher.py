"""Starts tosu (https://github.com/tosuapp/tosu) automatically so the user
never has to install or run it separately.

tosu is a third-party tool, LGPL-3.0 licensed, not authored by this project -
see THIRD_PARTY_NOTICES.md. We only launch their official prebuilt binary as
a separate hidden process; we never modify or embed their code.

If tosu is already running (e.g. the user runs it themselves for stream
overlays), we leave it alone rather than starting a second instance, which
would just fail to bind the same port.
"""
import os
import subprocess
import sys

TOSU_PROCESS_NAME = "tosu.exe"
CREATE_NO_WINDOW = 0x08000000  # Windows-only flag; suppresses the console tosu would otherwise open

# Set only if THIS process launched tosu itself - used by stop_tosu_if_we_started_it()
# so "End session" never kills a tosu instance the user was already running for
# something else (stream overlays, etc).
_our_tosu_process = None


def _tosu_path():
    if getattr(sys, "frozen", False):
        # PyInstaller onefile extracts bundled data next to the running exe's
        # temp dir at runtime (sys._MEIPASS)
        base = sys._MEIPASS
    else:
        # This file lives in src/; vendor/ sits one level up at the project root
        src_dir = os.path.dirname(os.path.abspath(__file__))
        base = os.path.join(os.path.dirname(src_dir), "vendor")
    return os.path.join(base, TOSU_PROCESS_NAME)


def is_tosu_running():
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {TOSU_PROCESS_NAME}"],
            capture_output=True, text=True, timeout=5,
        )
        return TOSU_PROCESS_NAME.lower() in result.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_tosu_running():
    """Launch tosu hidden if it isn't already running. Returns True if tosu
    is running afterward (whether we started it or it was already up),
    False if we couldn't find/start it - the collector will just retry its
    websocket connection quietly until tosu shows up."""
    if is_tosu_running():
        return True

    path = _tosu_path()
    if not os.path.isfile(path):
        return False

    try:
        global _our_tosu_process
        _our_tosu_process = subprocess.Popen(
            [path],
            cwd=os.path.dirname(path),
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )
        return True
    except OSError:
        return False


def stop_tosu_if_we_started_it():
    global _our_tosu_process
    if _our_tosu_process is not None and _our_tosu_process.poll() is None:
        _our_tosu_process.terminate()
    _our_tosu_process = None


if __name__ == "__main__":
    if is_tosu_running():
        print("tosu is already running.")
    elif ensure_tosu_running():
        print(f"tosu started hidden from {_tosu_path()}")
    else:
        print(f"Could not start tosu - checked for it at {_tosu_path()}")
