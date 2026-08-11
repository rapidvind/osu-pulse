// Auto-jumps every open dashboard page to whichever play is currently live,
// so you never have to manually navigate back to the play you're mid-map on.
// Persisted across pages/tabs via localStorage; the toggle button is the
// user's override - flip it off to browse freely while a play is active.
(function () {
  const ENABLED_KEY = "osuAnalytics.autoSwitchLive";

  function isEnabled() {
    return localStorage.getItem(ENABLED_KEY) !== "off";
  }

  function setEnabled(on) {
    localStorage.setItem(ENABLED_KEY, on ? "on" : "off");
    updateToggle();
  }

  function currentPlayIdFromUrl() {
    const m = location.pathname.match(/^\/play\/(\d+)/);
    return m ? Number(m[1]) : null;
  }

  let toggleEl = null;

  function updateToggle() {
    if (!toggleEl) return;
    const on = isEnabled();
    toggleEl.textContent = on ? "Auto-switch to live play: On" : "Auto-switch to live play: Off";
    toggleEl.style.background = on ? "var(--series-6, #008300)" : "var(--text-secondary, #8a5a71)";
  }

  function createToggle() {
    const el = document.createElement("button");
    el.id = "live-switch-toggle";
    el.style.cssText =
      "position:fixed;bottom:16px;right:16px;z-index:1000;padding:8px 14px;border:none;" +
      "border-radius:999px;color:#fff;font-size:12px;font-weight:600;cursor:pointer;" +
      "box-shadow:0 2px 8px rgba(0,0,0,0.25);opacity:0.9";
    el.onclick = () => setEnabled(!isEnabled());
    document.body.appendChild(el);
    toggleEl = el;
    updateToggle();
  }

  async function checkLivePlay() {
    if (!isEnabled()) return;
    try {
      const res = await fetch("/api/live");
      const data = await res.json();
      if (!data.active || !data.play) return;
      if (currentPlayIdFromUrl() !== data.play.id) {
        location.href = `/play/${data.play.id}`;
      }
    } catch (e) {
      // ignore - transient fetch failure, try again on the next tick
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createToggle);
  } else {
    createToggle();
  }

  checkLivePlay();
  setInterval(checkLivePlay, 3000);
})();
