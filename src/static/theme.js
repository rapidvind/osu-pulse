// Three themes: strawberry sunrise (morning), midday mandarin (afternoon),
// evening elderberry (night). Defaults to time-of-day on first visit; once
// the user picks one explicitly it's remembered (localStorage) and
// time-of-day is no longer consulted.
(function () {
  const THEMES = ["strawberry-sunrise", "midday-mandarin", "evening-elderberry"];
  const LABELS = { "strawberry-sunrise": "Strawberry Sunrise", "midday-mandarin": "Midday Mandarin", "evening-elderberry": "Evening Elderberry" };
  const STORAGE_KEY = "osu-pulse-theme";

  // Small line icons in the same style as the app's existing trash icon
  // (stroke=currentColor) so they recolor automatically with the button's
  // text color, including the active/white state.
  const ICON_SVG = {
    "strawberry-sunrise": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 8c5 0 8 4 8 8 0 3-3.5 6-8 6s-8-3-8-6c0-4 3-8 8-8Z"/>
      <path d="M12 8V5"/>
      <path d="M8 5c1-2 3-2 4-1"/>
      <path d="M16 5c-1-2-3-2-4-1"/>
      <circle cx="9.5" cy="15" r="0.6" fill="currentColor" stroke="none"/>
      <circle cx="14.5" cy="15" r="0.6" fill="currentColor" stroke="none"/>
      <circle cx="12" cy="18.5" r="0.6" fill="currentColor" stroke="none"/>
    </svg>`,
    "midday-mandarin": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="13" r="7"/>
      <path d="M12 6V3"/>
      <path d="M12 3c1.5-1.5 3.5-1 4 1"/>
      <path d="M12 8v10"/>
      <path d="M6.5 9.5c2-1.5 9-1.5 11 0"/>
      <path d="M6.5 16.5c2 1.5 9 1.5 11 0"/>
    </svg>`,
    "evening-elderberry": `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 3v4"/>
      <path d="M12 4c1.2-1.4 3-1.4 3.6 0.2"/>
      <circle cx="9" cy="11" r="2.6"/>
      <circle cx="14.5" cy="10.5" r="2.4"/>
      <circle cx="12" cy="15" r="2.6"/>
      <circle cx="16.5" cy="15" r="2.2"/>
      <circle cx="8" cy="16.5" r="2.1"/>
    </svg>`,
  };

  function themeForHour(hour) {
    if (hour >= 6 && hour < 17) return "strawberry-sunrise";
    if (hour >= 17 && hour < 20) return "midday-mandarin";
    return "evening-elderberry";
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll(".theme-toggle button").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.theme === theme);
    });
  }

  function setTheme(theme, remember) {
    applyTheme(theme);
    if (remember) localStorage.setItem(STORAGE_KEY, theme);
  }

  function buildToggle() {
    const bar = document.createElement("div");
    bar.className = "theme-toggle";
    THEMES.forEach(theme => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.theme = theme;
      btn.title = `${LABELS[theme]} mode`;
      btn.setAttribute("aria-label", `${LABELS[theme]} mode`);
      btn.innerHTML = ICON_SVG[theme];
      btn.addEventListener("click", () => setTheme(theme, true));
      bar.appendChild(btn);
    });
    document.body.appendChild(bar);
    applyTheme(document.documentElement.dataset.theme || themeForHour(new Date().getHours()));
  }

  // Translucency control - only meaningful (and only ever built) inside the
  // native overlay window, never a normal browser tab: `window.pywebview`
  // is injected automatically by pywebview into every page it loads (see
  // overlay.py), which is exactly how a page can tell the two apart. Fades
  // .viz-root (background + content together, see style.css) rather than
  // <body>, so this control and the theme toggle - both direct children of
  // <body>, not descendants of .viz-root - stay fully visible and grabbable
  // no matter how low the opacity goes.
  const OPACITY_KEY = "osu-pulse-overlay-opacity";
  const OPACITY_MIN = 0.25;

  function applyOpacity(value) {
    document.documentElement.style.setProperty("--overlay-opacity", value);
  }

  function initOpacitySlider() {
    // window.pywebview is injected asynchronously - it's not guaranteed to
    // exist yet by the time this script runs, even inside the overlay
    // window, so a one-shot check here would flakily skip building the
    // slider depending on load timing. pywebviewready is pywebview's own
    // signal that the bridge has finished initializing; fall back to it
    // when the object isn't there yet, and only build when we're sure one
    // way or the other (never in a normal browser tab, where this event
    // simply never fires).
    if (window.pywebview) {
      buildOpacitySlider();
    } else {
      window.addEventListener("pywebviewready", buildOpacitySlider, { once: true });
    }
  }

  function buildOpacitySlider() {
    const saved = parseFloat(localStorage.getItem(OPACITY_KEY));
    const initial = Number.isFinite(saved) ? Math.min(1, Math.max(OPACITY_MIN, saved)) : 1;
    applyOpacity(initial);

    const wrap = document.createElement("div");
    wrap.className = "overlay-opacity-control";
    wrap.innerHTML = `
      <label for="overlay-opacity-slider">Opacity</label>
      <input type="range" id="overlay-opacity-slider" min="${OPACITY_MIN}" max="1" step="0.05" value="${initial}">
    `;
    wrap.querySelector("input").addEventListener("input", (e) => {
      const v = parseFloat(e.target.value);
      applyOpacity(v);
      localStorage.setItem(OPACITY_KEY, v);
    });
    document.body.appendChild(wrap);
  }

  function build() {
    buildToggle();
    initOpacitySlider();
  }

  // Applied as early as possible (before first paint) to avoid a flash of
  // the wrong theme; see the inline snippet in each template's <head>.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
