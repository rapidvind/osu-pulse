import threading
import time
from collections import deque

import keyboard


class KeyListener:
    """Global keyboard hook that timestamps presses of the tracked mania keys.

    Runs a rolling buffer so the correlator can look back a few hundred ms
    when a miss is reported, without needing precise event-to-event sync.

    Matches on hardware scan code rather than the reported key name. Caps
    Lock (and Shift) change what character/name a keypress produces - 'a'
    becomes 'A' - which would silently break a name-based match. The scan
    code for a physical key never changes regardless of modifier state, so
    hooking on scan code makes tracking immune to Caps Lock being toggled
    mid-session.
    """

    def __init__(self, key_to_finger, buffer_seconds=5.0):
        self.buffer_seconds = buffer_seconds
        self._buffer = deque()  # list of (timestamp, key)
        self._lock = threading.Lock()
        self._scan_code_to_key = {}
        self.set_keys(key_to_finger)

    def set_keys(self, key_to_finger):
        """Rebuilds the scan-code lookup for a new key mapping. Safe to call
        while the hook is already running (e.g. from the settings API) -
        `keyboard.hook` reads this dict on every event, so updating it here
        takes effect on the very next keypress with no re-hook needed."""
        mapping = {}
        for key in key_to_finger:
            for scan_code in keyboard.key_to_scan_codes(key):
                mapping[scan_code] = key
        with self._lock:
            self._scan_code_to_key = mapping

    def start(self):
        keyboard.hook(self._on_event)

    def _on_event(self, event):
        if event.event_type != keyboard.KEY_DOWN:
            return
        with self._lock:
            key = self._scan_code_to_key.get(event.scan_code)
        if key is None:
            return
        now = time.monotonic()
        with self._lock:
            self._buffer.append((now, key))
            cutoff = now - self.buffer_seconds
            while self._buffer and self._buffer[0][0] < cutoff:
                self._buffer.popleft()

    def most_recent_key_before(self, when, window):
        """Return (key, press_time) for the latest tracked key press at or
        before `when`, within `window` seconds. None if nothing matches."""
        with self._lock:
            candidates = [(t, k) for (t, k) in self._buffer if when - window <= t <= when]
        if not candidates:
            return None
        t, k = max(candidates, key=lambda tk: tk[0])
        return k, t

    def stop(self):
        keyboard.unhook_all()
