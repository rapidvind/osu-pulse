// Shared density overlay charts, used by /map and /session pages.
// Density is drawn as a filled area (single hue, sequential = magnitude).

// red, green, yellow, violet - a wide hue spread so all four stay visually
// distinct from each other and from the blue density curve underneath them.
const FINGER_COLORS = {
  left_middle: "var(--series-8)",
  left_index: "var(--series-6)",
  right_index: "var(--series-4)",
  right_middle: "var(--series-7)",
};
const FINGER_ORDER = ["left_middle", "left_index", "right_index", "right_middle"];

const JUDGMENT_LABELS = { "0": "miss", "50": "50", "100": "100", katu: "200 (good)" };

// Colors for the density-vs-judgment-type chart's non-miss options - misses
// keep their own per-finger coloring (FINGER_COLORS) since only misses carry
// key/finger attribution; these other judgment types don't.
const JUDGMENT_TYPE_COLORS = { "0": "var(--series-8)", "50": "var(--series-2)", "100": "var(--series-4)", katu: "var(--series-7)" };

function fmtTime(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

// Builds the density area/line + gridlines + time axis shared by both chart
// types below. Returns the pieces needed to layer markers on top.
function _densityBase(container, density) {
  const width = Math.max(container.clientWidth || 900, 600);
  const height = 220;
  const padTop = 10, padBottom = 24, padLeft = 8, padRight = 8;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const maxTime = density[density.length - 1][0];
  const maxDensity = Math.max(...density.map(d => d[1]), 1);

  const xScale = t => padLeft + (t / maxTime) * plotW;
  const yScale = v => padTop + plotH - (v / maxDensity) * plotH;

  let areaPath = `M ${xScale(0)} ${yScale(0)} `;
  density.forEach(([t, v]) => { areaPath += `L ${xScale(t)} ${yScale(v)} `; });
  areaPath += `L ${xScale(maxTime)} ${yScale(0)} Z`;

  let linePath = "";
  density.forEach(([t, v], i) => {
    linePath += (i === 0 ? "M" : "L") + ` ${xScale(t)} ${yScale(v)} `;
  });

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map(f => {
    const y = padTop + plotH * (1 - f);
    return `<line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="var(--grid)" stroke-width="1" />`;
  }).join("");

  const timeTicks = [0, 0.25, 0.5, 0.75, 1].map(f => {
    const t = maxTime * f;
    return `<text x="${xScale(t)}" y="${height - 6}" font-size="10" fill="var(--muted)" text-anchor="middle">${fmtTime(t)}</text>`;
  }).join("");

  const baseSvg = `
    ${gridLines}
    <path d="${areaPath}" fill="var(--series-1)" opacity="0.15" />
    <path d="${linePath}" fill="none" stroke="var(--series-1)" stroke-width="2" />
  `;

  return { width, height, padTop, xScale, baseSvg, timeTicks };
}

// Marker positions stack vertically when clustered within a few pixels of
// each other (e.g. miss bursts in dense jack/stream sections), closest-in-
// time first, so every event stays visible instead of overlapping into one dot.
function _stackMarkers(items, xScale, markerRadius) {
  const stackGap = markerRadius * 2 + 2;
  const clusterPx = markerRadius * 2;
  const positioned = items
    .map(item => ({ item, x: xScale(item.song_time_ms) }))
    .sort((a, b) => a.x - b.x);

  let clusterX = null, stackIndex = 0;
  return positioned.map(({ item, x }) => {
    if (clusterX === null || x - clusterX > clusterPx) {
      clusterX = x;
      stackIndex = 0;
    } else {
      stackIndex += 1;
    }
    return { item, x, stackIndex };
  });
}

function renderDensityChart(container, density, misses) {
  container.innerHTML = "";
  density = density || [];
  misses = misses || [];
  if (!density.length) {
    container.innerHTML = '<div class="empty">No beatmap data parsed for this map yet (needs the .osu file path from tosu).</div>';
    return;
  }

  const { width, height, padTop, xScale, baseSvg, timeTicks } = _densityBase(container, density);
  const MARKER_R = 4;
  const STACK_GAP = MARKER_R * 2 + 2;

  const stacked = _stackMarkers(misses.filter(m => m.song_time_ms != null), xScale, MARKER_R);
  const missMarkers = stacked.map(({ item: m, x, stackIndex }) => {
    const cy = padTop + 6 + stackIndex * STACK_GAP;
    const color = FINGER_COLORS[m.finger] || "var(--muted)";
    const title = `${fmtTime(m.song_time_ms)} · key ${m.key ?? "?"} · ${m.finger ?? "unmatched"}${m.pattern ? " · " + m.pattern : ""}`;
    return `<circle cx="${x}" cy="${cy}" r="${MARKER_R}" fill="${color}" stroke="var(--surface-1)" stroke-width="1.5"><title>${title}</title></circle>`;
  }).join("");

  container.innerHTML = `
    <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="overflow:visible">
      ${baseSvg}
      ${missMarkers}
      ${timeTicks}
    </svg>
    <div class="legend" style="margin-top:10px">
      ${FINGER_ORDER.map(f => `<div class="legend-item"><span class="swatch" style="background:${FINGER_COLORS[f]}"></span>${f}</div>`).join("")}
    </div>
  `;
}

// Same density backdrop as renderDensityChart, but plots one non-miss
// judgment type (100/50/200-good) instead of misses. These don't carry
// key/finger attribution (only true misses go through the key-hook match in
// collector.py), so markers are a single color per type with no legend.
function renderJudgmentDensityChart(container, density, judgments, typeKey) {
  container.innerHTML = "";
  density = density || [];
  judgments = judgments || [];
  if (!density.length) {
    container.innerHTML = '<div class="empty">No beatmap data parsed for this map yet (needs the .osu file path from tosu).</div>';
    return;
  }

  const { width, height, padTop, xScale, baseSvg, timeTicks } = _densityBase(container, density);
  const MARKER_R = 4;
  const STACK_GAP = MARKER_R * 2 + 2;
  const color = JUDGMENT_TYPE_COLORS[typeKey] || "var(--muted)";
  const label = JUDGMENT_LABELS[typeKey] || typeKey;

  const filtered = judgments.filter(j => j.judgment === typeKey && j.song_time_ms != null);
  const stacked = _stackMarkers(filtered, xScale, MARKER_R);
  const markers = stacked.map(({ item: j, x, stackIndex }) => {
    const cy = padTop + 6 + stackIndex * STACK_GAP;
    const title = `${fmtTime(j.song_time_ms)} - ${label}`;
    return `<circle cx="${x}" cy="${cy}" r="${MARKER_R}" fill="${color}" stroke="var(--surface-1)" stroke-width="1.5"><title>${title}</title></circle>`;
  }).join("");

  container.innerHTML = `
    <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="overflow:visible">
      ${baseSvg}
      ${markers}
      ${timeTicks}
    </svg>
    ${filtered.length === 0 ? `<div class="empty" style="margin-top:10px">No ${label} recorded for this play.</div>` : ""}
  `;
}

// Actual-vs-predicted PP/rank chart for the Ascent tab. One point per
// qualifying game session (x = session order, not wall-clock time - sessions
// without enough serious plays don't count and would otherwise create
// misleading gaps). `invert` flips the y-axis for rank, where a SMALLER
// number is the better outcome and should read as "higher" on the chart.
function renderForecastChart(container, points, opts) {
  container.innerHTML = "";
  const { actualKey, predictedKey, beatKey, formatValue, invert } = opts;
  const actualPoints = points
    .map((p, i) => ({ i, v: p[actualKey], beat: p[beatKey], startedAt: p.started_at }))
    .filter(p => p.v != null);
  if (!actualPoints.length) {
    container.innerHTML = '<div class="empty">Not enough data yet.</div>';
    return;
  }

  const width = Math.max(container.clientWidth || 900, 600);
  const height = 220;
  const padTop = 16, padBottom = 24, padLeft = 56, padRight = 8;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const n = points.length;
  const xScale = i => padLeft + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);

  const allValues = points.flatMap(p => [p[actualKey], p[predictedKey]]).filter(v => v != null);
  let yMin = Math.min(...allValues);
  let yMax = Math.max(...allValues);
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const pad = (yMax - yMin) * 0.1;
  yMin -= pad; yMax += pad;
  const yScale = v => {
    const f = (v - yMin) / (yMax - yMin);
    return padTop + plotH - (invert ? 1 - f : f) * plotH;
  };

  const yTickCount = 5;
  const yTicks = Array.from({ length: yTickCount }, (_, i) => yMin + (i / (yTickCount - 1)) * (yMax - yMin));
  const gridLines = yTicks.map(v => {
    const y = yScale(v);
    return `
      <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="var(--grid)" stroke-width="1" />
      <text x="${padLeft - 8}" y="${y + 3}" font-size="10" fill="var(--muted)" text-anchor="end">${formatValue(v)}</text>
    `;
  }).join("");

  function linePath(key, onlyDefined) {
    let path = "";
    let started = false;
    points.forEach((p, i) => {
      const v = p[key];
      if (v == null) { if (onlyDefined) started = false; return; }
      path += (!started ? "M" : "L") + ` ${xScale(i)} ${yScale(v)} `;
      started = true;
    });
    return path;
  }

  const actualPath = linePath(actualKey, false);
  const predictedPath = linePath(predictedKey, true);

  const markers = actualPoints.map(({ i, v, beat, startedAt }) => {
    const color = beat === true ? "var(--series-6)" : beat === false ? "var(--series-8)" : "var(--series-1)";
    const r = beat === true ? 5 : 4;
    const title = `${startedAt} - ${formatValue(v)}${beat === true ? " (beat forecast)" : beat === false ? " (missed forecast)" : ""}`;
    return `<circle cx="${xScale(i)}" cy="${yScale(v)}" r="${r}" fill="${color}" stroke="var(--surface-1)" stroke-width="1.5"><title>${title}</title></circle>`;
  }).join("");

  container.innerHTML = `
    <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="overflow:visible">
      ${gridLines}
      <path d="${predictedPath}" fill="none" stroke="var(--series-4)" stroke-width="2" stroke-dasharray="5,4" />
      <path d="${actualPath}" fill="none" stroke="var(--series-1)" stroke-width="2" />
      ${markers}
    </svg>
    <div class="legend" style="margin-top:10px">
      <div class="legend-item"><span class="swatch" style="background:var(--series-1)"></span>Actual</div>
      <div class="legend-item"><span class="swatch" style="background:var(--series-4)"></span>Predicted</div>
      <div class="legend-item"><span class="swatch" style="background:var(--series-6)"></span>Beat forecast</div>
      <div class="legend-item"><span class="swatch" style="background:var(--series-8)"></span>Missed forecast</div>
    </div>
  `;
}

// Running accuracy over time: starts at 100%, drops on any non-perfect
// judgment. Density keeps its usual pink area+line treatment (same visual
// weight as the other charts) so it stays a clear, persistent backdrop -
// but it's still drawn on its OWN internal scale, never sharing the labeled
// y-axis with the accuracy line. Two different quantities sharing one
// y-scale is the #1 chart anti-pattern (it implies a false correlation
// between unrelated units); accuracy% is the only labeled, scaled axis,
// zoomed to the actual data range (not a fixed 0-100) so real single-digit
// percent drops stay visible.
function renderAccuracyChart(container, density, judgments) {
  container.innerHTML = "";
  density = density || [];
  judgments = judgments || [];
  if (!density.length) {
    container.innerHTML = '<div class="empty">No beatmap data parsed for this map yet (needs the .osu file path from tosu).</div>';
    return;
  }

  const width = Math.max(container.clientWidth || 900, 600);
  const height = 220;
  const padTop = 16, padBottom = 24, padLeft = 42, padRight = 8;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const maxTime = density[density.length - 1][0];
  const xScale = t => padLeft + (t / maxTime) * plotW;

  // Density area + line, same pink treatment as the other charts - its own
  // internal scale only, never sharing an axis with the accuracy line.
  const maxDensity = Math.max(...density.map(d => d[1]), 1);
  const densityY = v => padTop + plotH - (v / maxDensity) * plotH * 0.9;
  let densityArea = `M ${xScale(0)} ${densityY(0)} `;
  density.forEach(([t, v]) => { densityArea += `L ${xScale(t)} ${densityY(v)} `; });
  densityArea += `L ${xScale(maxTime)} ${densityY(0)} Z`;
  let densityLine = "";
  density.forEach(([t, v], i) => {
    densityLine += (i === 0 ? "M" : "L") + ` ${xScale(t)} ${densityY(v)} `;
  });

  // Running accuracy: each judgment contributes weight/60 to the numerator
  // and 1 to the denominator (see collector.py JUDGMENT_LOSS_FRACTION).
  const withPos = judgments.filter(j => j.song_time_ms != null).sort((a, b) => a.song_time_ms - b.song_time_ms);
  const points = [{ t: 0, acc: 100 }];
  let num = 0, den = 0;
  withPos.forEach(j => {
    num += (1 - j.accuracy_loss) * 60;
    den += 60;
    points.push({ t: j.song_time_ms, acc: (num / den) * 100, judgment: j.judgment, loss: j.accuracy_loss });
  });

  if (den === 0) {
    container.innerHTML = `
      <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
        <path d="${densityArea}" fill="var(--series-1)" opacity="0.15" />
        <path d="${densityLine}" fill="none" stroke="var(--series-1)" stroke-width="2" />
      </svg>
      <div class="empty">No judged notes recorded for this play yet.</div>
    `;
    return;
  }

  // Zoom the y-axis to the actual range reached (e.g. 96.9%-100%), not a
  // fixed 0-100 scale that would flatten every real deviation into a hairline.
  const minAcc = Math.min(...points.map(p => p.acc));
  const yMax = 100;
  const yMin = Math.max(0, Math.floor(minAcc * 2) / 2 - 0.5); // half-percent padding below the worst point
  const yScale = acc => padTop + plotH - ((acc - yMin) / (yMax - yMin)) * plotH;

  const yTickCount = 5;
  const yTicks = Array.from({ length: yTickCount }, (_, i) => yMin + (i / (yTickCount - 1)) * (yMax - yMin));
  const gridLines = yTicks.map(v => {
    const y = yScale(v);
    return `
      <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="var(--grid)" stroke-width="1" />
      <text x="${padLeft - 8}" y="${y + 3}" font-size="10" fill="var(--muted)" text-anchor="end">${v.toFixed(1)}%</text>
    `;
  }).join("");

  const timeTicks = [0, 0.25, 0.5, 0.75, 1].map(f => {
    const t = maxTime * f;
    return `<text x="${xScale(t)}" y="${height - 6}" font-size="10" fill="var(--muted)" text-anchor="middle">${fmtTime(t)}</text>`;
  }).join("");

  let linePath = "";
  points.forEach((p, i) => {
    linePath += (i === 0 ? "M" : "L") + ` ${xScale(p.t)} ${yScale(p.acc)} `;
  });

  // Small dots at the actual drop events (not the synthetic t=0 start point)
  // so hovering shows exactly what happened and by how much.
  const dropMarkers = points.slice(1).filter(p => p.loss > 0).map(p => {
    const label = JUDGMENT_LABELS[p.judgment] || p.judgment;
    const lossPct = Math.round(p.loss * 100);
    const title = `${fmtTime(p.t)} · ${label} · -${lossPct}% on that note · running ${p.acc.toFixed(2)}%`;
    return `<circle cx="${xScale(p.t)}" cy="${yScale(p.acc)}" r="3" fill="var(--series-6)" stroke="var(--surface-1)" stroke-width="1"><title>${title}</title></circle>`;
  }).join("");

  container.innerHTML = `
    <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="overflow:visible">
      <path d="${densityArea}" fill="var(--series-1)" opacity="0.15" />
      <path d="${densityLine}" fill="none" stroke="var(--series-1)" stroke-width="2" />
      ${gridLines}
      <path d="${linePath}" fill="none" stroke="var(--series-6)" stroke-width="2" />
      ${dropMarkers}
      ${timeTicks}
    </svg>
    <div class="sub" style="margin-top:10px">Green line is running accuracy (starts at 100%). Pink shape behind it is note density, on its own scale for context - the accuracy% axis is zoomed to this play's actual range.</div>
  `;
}
