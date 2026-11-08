"""In-game overlay: a frameless, always-on-top window embedding the same
Flask dashboard the browser tab shows, toggled on/off with a global hotkey
(config.OVERLAY_HOTKEY) via the `keyboard` lib key_listener.py already hooks
with - no separate UI stack, the existing HTML/CSS/JS just gets reused.

pywebview's event loop (webview.start()) must own the main thread on
Windows, so this module's run() is meant to be the LAST call in main() -
everything else (Flask, the collector's threads) already runs in the
background by the time this blocks.
"""
import keyboard
import webview

from config import OVERLAY_HOTKEY

WINDOW_TITLE = "osu!Pulse Overlay"
WINDOW_WIDTH = 540
WINDOW_HEIGHT = 820


class Overlay:
    def __init__(self, url, hotkey=OVERLAY_HOTKEY):
        self.url = url
        self.hotkey = hotkey
        self.window = None
        self._visible = False

    def _toggle(self):
        if self.window is None:
            return
        if self._visible:
            self.window.hide()
        else:
            self.window.show()
        self._visible = not self._visible

    def _on_closed(self):
        # Only reachable if the OS itself killed the window (e.g. Alt+F4) -
        # the frameless window has no close button of its own. Once
        # destroyed it can't be re-shown, so just stop tracking it; the
        # hotkey becomes a no-op rather than erroring on a dead window.
        self.window = None

    def run(self):
        """Blocks - must be called from the main thread."""
        self.window = webview.create_window(
            WINDOW_TITLE,
            self.url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            on_top=True,
            frameless=True,
            easy_drag=True,
            hidden=True,
            # Native window-level transparency - required for the in-page
            # translucency slider (theme.js/style.css --overlay-opacity) to
            # actually show the desktop/game through as it's lowered,
            # rather than just fading toward an opaque window backdrop.
            transparent=True,
        )
        self.window.events.closed += self._on_closed
        keyboard.add_hotkey(self.hotkey, self._toggle)
        # pywebview's DEFAULT Windows backend (WinForms + embedded EdgeChrome)
        # implements `transparent` with a documented hack (their own source
        # comment: "no idea why this works") based on WinForms color-key
        # transparency - it doesn't alpha-blend, it just reveals the window's
        # backing color, which is why lowering the slider looked like fading
        # toward white instead of showing the desktop/game through. The Qt
        # backend uses Qt.WA_TranslucentBackground, the standard mechanism
        # real desktop overlays use for this - genuine alpha compositing.
        webview.start(gui="qt")


def run(port, hotkey=OVERLAY_HOTKEY):
    Overlay(f"http://127.0.0.1:{port}", hotkey).run()
