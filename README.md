# osu!Pulse

A local tool for osu!mania that tracks and helps you identify flaws to
improve: it watches you play in real time, records every miss, attributes
it to the key/finger that most likely caused it, and shows the breakdown —
per map, per play, and per game session — in a web dashboard styled after
osu!'s own pink-and-white look.

## Folder structure

```
osu-analytics/
├── src/                  All Python source + Flask templates/static
│   ├── app.py            Flask app: routes, API, entry point
│   ├── collector.py      Ties tosu + the key hook together, detects misses
│   ├── tosu_client.py    Websocket client for tosu's live data feed
│   ├── tosu_launcher.py  Auto-starts tosu hidden if it isn't already running
│   ├── key_listener.py   Global keyboard hook (scan-code based)
│   ├── beatmap_parser.py Reads .osu files for note density / pattern data
│   ├── db.py             SQLite schema + queries
│   ├── settings.py       Loads/saves the key-to-finger mapping (settings.json)
│   ├── config.py         Tunables (tosu URL, miss attribution window, ports)
│   ├── templates/        Dashboard, map, play, game-session pages
│   └── static/           CSS + chart rendering JS
├── vendor/               tosu.exe lands here (fetched, not committed)
├── dist/                 PyInstaller output (.exe) lands here — outside src/
├── fetch_tosu.ps1        Downloads tosu's latest Windows release into vendor/
├── requirements.txt
├── THIRD_PARTY_NOTICES.md
├── osu_analytics.db      Created automatically at the project root
└── settings.json         Key-to-finger mapping — created automatically,
                           editable from the dashboard or by hand
```

Scripts stay together under `src/`; the packaged executable is built into
`dist/`, outside of it — the two are never mixed.

## What it tracks

| Level | What it is | Example |
|---|---|---|
| **Game session** | One continuous osu!-open-to-close run | "Tuesday night's 2-hour session" |
| **Play** | One attempt at one map, within a game session | "3rd attempt at Cryptarithm [MASTER]" |
| **Miss** | One missed note within a play | key, finger, song position, combo at the time, local note pattern |

## How it works

tosu (https://github.com/tosuapp/tosu) reads osu!'s live memory and exposes
it over a local websocket — that's the *only* way to get miss/combo/beatmap
data out of osu! at all, since the game itself exposes nothing to outside
programs. But tosu has no idea which physical key you pressed. So this
project layers a second signal on top: a global keyboard hook that
timestamps your 4 mania keys, and correlates "a miss just happened" (from
tosu) with "which tracked key was pressed most recently" (from the hook) to
attribute each miss to a finger.

![Architecture flowchart](docs/architecture.png)

### Why a heuristic, not ground truth

Neither tosu nor osu! itself will tell an outside program "key X caused
miss Y" — that mapping only exists inside the game's own hit-judgment code.
The best available proxy is timing correlation: whichever tracked key was
pressed most recently before the miss was reported, within
`MISS_ATTRIBUTION_WINDOW` (config.py, default 350ms). This is accurate for
isolated misses but noisier on dense jacks/chords where multiple notes miss
within the same tosu update tick — in that case they may share a timestamp
and get stacked visually on the density chart rather than perfectly
separated.

## Setup (running from source)

1. Fetch tosu into `vendor/tosu.exe`:
   ```powershell
   .\fetch_tosu.ps1
   ```
   (or download manually from https://github.com/tosuapp/tosu/releases and
   place `tosu.exe` in `vendor/`)
2. Your keybinds default to `A S ; '`. If that's not what you play with,
   change it either from the dashboard's "Key settings" panel once the app
   is running (takes effect immediately, no restart), or by editing
   `settings.json` directly. Must match your actual in-game keybinds (osu!
   Options > Input > osu!mania Bindings), and the order (left to right)
   must match your in-game column order.
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run it — **double-click `START osu!Pulse.bat`** in the project
   root. It requests Administrator automatically (see note below) and then
   starts everything: tosu (hidden, if not already running), the collector
   (key hook + tosu listener), and the dashboard, opened in your browser at
   http://127.0.0.1:5151. Close its console window to stop the app.

   (Equivalent manual command, if you'd rather run it yourself from an
   Administrator terminal: `python src/app.py` from the project root.)

**Administrator note:** the global keyboard hook needs the terminal (or the
packaged exe) run as Administrator to reliably catch key presses while
osu! — a focused game window — has input focus. Without it, misses may log
as "unmatched" (no key/finger).

## Features

- **Dashboard** — live totals, misses by finger/key (column charts), misses
  by beatmap with thumbnail art, collapsible recent-misses log, one-click
  jump to whatever's currently live.
- **Map page** (`/map/<id>`) — every attempt at a beatmap, note-density-vs-
  miss overlay combining all plays, miss trend across attempts, delete
  individual plays.
- **Play page** (`/play/<id>`) — live view of a single attempt, refreshing
  every 2s while in progress: misses plotted against that map's density
  curve, best combo before a miss, per-finger breakdown.
- **Game session page** (`/game-session/<id>`) — every map played in one
  sitting, in order, with miss counts per map.
- **Delete controls** — remove a single play, or every recorded play for a
  beatmap, from the relevant tables.

## Packaging into a standalone .exe

Once everything works via `python src/app.py`:

1. Make sure `vendor/tosu.exe` is present (`.\fetch_tosu.ps1` if not).
2. From the project root, build with PyInstaller:
   ```
   pyinstaller --onefile --name osu-pulse ^
     --add-data "src/templates;templates" ^
     --add-data "src/static;static" ^
     --add-binary "vendor/tosu.exe;." ^
     --icon "src/static/mascot.ico" ^
     src/app.py
   ```

The resulting `dist/osu-pulse.exe` bundles Python, all dependencies,
and tosu itself — outside `src/`, per the folder structure above. Users
just run it (as Administrator, for the key hook) — no separate tosu
install needed, no Python install needed. It opens the dashboard in the
default browser automatically, and keeps `osu_analytics.db` next to the
exe so data persists between runs.

## Third-party credit

This project bundles and auto-launches **tosu** for convenience — all
credit for the live memory-reading itself belongs to its authors. Full
attribution and license details (LGPL-3.0) are in
`THIRD_PARTY_NOTICES.md`.
