# Handoff: Cryptrink Workspace UI Redesign

## Overview

This package redesigns the Cryptrink operator UI. The current app (`src/cryptrink/web/`) is a
Gradio app organized as **6 flat tabs** (Backtest, Portfolio, Suggest, Live, Data, Status) with
per-tab log terminals and many manual "refresh / poll" buttons. The redesign replaces that with a
single **workspace**: a persistent header + mode banner, a workflow-grouped sidebar, a global
status rail, **one docked global terminal**, automated refresh, and a loud paper/live safety model.

The goal of this PR is **usability**, not new features. Every capability in the prototype already
exists in the backend — this is a re-organization and re-skin of the existing surface.

## About the Design Files

The files in this bundle are **design references created in HTML/JS** (`Cryptrink.dc.html`, a
self-contained prototype; `support.js` is its tiny runtime). They are **not production code to
copy**. The task is to **recreate this design in the existing Gradio environment** —
`gradio.Blocks`, the existing tab modules, and the `RuntimeState` singleton in
`src/cryptrink/web/state.py`. Keep the Python module boundaries; change the *presentation and
wiring*, not the engine code under `src/cryptrink/{backtest,strategy,data,exchange,...}`.

If a piece of the design genuinely cannot be expressed in Gradio (e.g. the crosshair candlestick
tooltip), use `gr.Plot`/Plotly for the interactive charts and approximate the rest with
`gr.HTML` + CSS. Favor a faithful layout over pixel-perfection where Gradio constrains you.

## Fidelity

**High-fidelity.** Final colors, type, spacing, and interaction model are intended as shown.
Three themes are included; **Carbon (dark, teal accent) is the default** — implement that first,
the other two (Slate, Daylight) are optional follow-ups driven by the same CSS variables.

---

## Information Architecture (the core change)

Current: 6 sibling tabs, equal weight, each with its own log box and refresh buttons.

New: workflow-grouped **left sidebar**, with Data + Status demoted to a "System" group and a
global terminal pulled out of the tabs entirely.

```
RESEARCH      Backtest        -> src/cryptrink/web/tabs/backtest.py (+ backtest_tuning.py)
              Portfolio       -> src/cryptrink/web/tabs/portfolio.py
TRADE         Suggest         -> src/cryptrink/web/tabs/suggest.py
              Live            -> src/cryptrink/web/tabs/live.py (+ live_loop.py, live_setup.py)
MONITOR       Dashboard       -> NEW thin view: reads positions/orders from exchange + state.py
SYSTEM        Data            -> src/cryptrink/web/tabs/data.py
              Settings        -> connection + risk defaults (from config), demoted out of the flow
```

Persistent chrome present on every screen:
- **Header** — logo, exchange-connection pill, account balance, "last synced" stamp, theme switch.
- **Mode banner** — full-width PAPER (amber) / LIVE (red, pulsing) state. See Safety Model.
- **Status rail** (right, ~296px) — live-loop heartbeat, today's P&L, open positions, watchlist.
- **Docked terminal** (bottom) — see Global Terminal.

---

## Screens / Views

### 1. Portfolio  (`tabs/portfolio.py`) — highest priority
- **Purpose**: build a multi-pair portfolio sharing one cash pool, then backtest the whole
  allocation in one run.
- **Layout**: two columns. Left (300px): a Portfolios picker list + an Allocations card (per-pair
  symbol, strategy, weight bar) + `Run backtest` / `Edit YAML` buttons. Right (fluid): a 4-up
  metrics row (Total return, Sharpe, Max drawdown, Win rate), an **interactive equity curve**
  (crosshair + tooltip showing date / value / % from start), and a per-allocation breakdown table
  (Symbol, Strategy, Trades, Win %, Realised P&L).
- **Mapping**: the YAML config + multi-pair `BacktestEngine` run already exist in `portfolio.py`;
  this screen reorganizes those inputs/outputs. Equity curve replaces the static matplotlib PNG
  with an interactive `gr.Plot` (Plotly).

### 2. Live  (`tabs/live.py`, `live_loop.py`, `live_setup.py`) — highest priority
- **Purpose**: run a strategy on an interval against Revolut X. Paper replays locally; live places
  real orders.
- **Layout**: a mode callout at top (mirrors the global banner), then two columns. Left (fluid):
  an **interactive candlestick chart** (1h, crosshair tooltip O/H/L/C) + a "Loop activity" stats
  row (Iterations, Signals, Executions, Errors). Right (320px): a **Loop configuration** card
  (Strategy, Dataset, Interval, Paper balance; an `Advanced` `<details>` holding risk + Discord
  heartbeat) with a primary Start/Stop button + `Test connection` / `Pre-flight`; below it a
  **Loop status** card (Symbol, Strategy, Interval, Mode, Engine ID, Last signal).
- **Mapping**: `LiveLoop` start/stop, interval, paper vs live, and the heartbeat all exist. The
  Start button must route through the **confirm dialog** when mode == live (see Safety Model).
  Loop status fields read from the running `LiveLoop` / `RuntimeState`.

### 3. Dashboard  (NEW thin monitoring view)
- **Purpose**: at-a-glance engine state, open positions, order history across paper + live.
- **Layout**: 4-up metrics (Account equity, Open P&L, Realised 30d, Active engines), an Open
  positions table (Symbol, Side, Qty, Entry, Mark, Unreal. P&L), a Recent orders table (Time,
  Symbol, Side, Type, Qty, Price, Status).
- **Mapping**: reads from the exchange portfolio/orders endpoints + `RuntimeState`. No new engine
  logic — this is a read-only aggregation of data the Status tab already surfaces.

### 4. Backtest  (`tabs/backtest.py`, `tabs/backtest_tuning.py`)
- **Purpose**: replay a single strategy over a stored dataset; tune by hand or sweep.
- **Layout**: left config card (Strategy, Dataset, Start, Capital; two collapsed `<details>`:
  "Strategy parameters" and "Auto-tuning · grid / Optuna TPE"); right: 4-up metrics + interactive
  equity curve.
- **Mapping**: existing `BacktestEngine` run + the tuning module. Progressive disclosure is the
  key change: tuning + raw params are collapsed by default so the common path is one click.

### 5. Suggest  (`tabs/suggest.py`)
- **Purpose**: one-shot trade suggestion from the latest stored candle; places no order.
- **Layout**: a single input row (Strategy, Dataset, `Suggest`) + a result card (big BUY/SELL/HOLD
  verdict, strength badge, and a key/value grid: Symbol, Timeframe, Signal, Strength, Price,
  Candles used).

### 6. Data  (`tabs/data.py`)
- **Purpose**: backfill + inspect stored OHLCV.
- **Layout**: a backfill row (Symbol, Timeframe, Start, `Backfill`) + a Stored datasets table
  (Symbol, TF, Candles, Range, freshness). Maintenance ops (wipe/reset/checkpoint) move behind an
  `Advanced` disclosure. The dataset list **auto-refreshes on startup** (see Automation) — the
  manual "refresh datasets" button is removed.

### 7. Settings  (connection + risk defaults; demoted)
- **Purpose**: the rarely-changed knobs, pulled out of the workflow.
- **Layout**: a Revolut X connection card (API key masked, private key status, base URL, webhook),
  a Risk defaults card (max position size, stop loss, take profit, circuit breaker, max open
  positions), and an Appearance card (the 3 theme swatches).
- **Mapping**: this is where the "too many confusing non-Revolut-X knobs" go. Keep Revolut X
  config minimal and obvious; everything else is a labeled default here.

---

## Interactions & Behavior

### Safety Model (paper vs live) — implement loudly
- A persistent **mode banner** spans the app. PAPER = amber tint, static dot, copy "Simulated
  against stored data — no real orders." LIVE = red tint, **pulsing** dot, copy "Real orders are
  placed on Revolut X with account funds."
- Switching paper -> live **always** opens a blocking confirm dialog ("Switch to LIVE trading?").
  Switching live -> paper is immediate.
- Pressing **Start** on the Live loop while in live mode opens a second confirm ("Start LIVE
  loop?") before any order can be placed. Paper start is immediate.
- The Live Start button is teal in paper, red in live, and turns red "Stop" while running.
- Confirm dialogs: red accent, warning glyph, `Cancel` (secondary) + a red primary action.

### Global Terminal (replaces per-tab logs)
- One terminal docked at the bottom, collapsible via the caret. ~150px tall open.
- Each line: `time · source · message`, monospace, message colored by level
  (ok=green, info=dim, warn=amber, err=red), source-tag colored per source.
- **Source filter** chips: `all / sys / data / backtest / live`. `clear` empties it.
- Auto-scrolls to newest; shows a blinking cursor. Every backend action (`emit(source, level,
  msg)` in the prototype) should map to a structured log push from the Python side — i.e. replace
  the scattered `gr.Textbox` logs with one shared log stream that all modules append to.

### Automation (remove manual poll/refresh buttons)
- On **startup**: sync exchange connection, symbol vocabulary, and stored-dataset list; log each to
  the terminal. (Prototype shows these as the first terminal lines.)
- On **focus/select**: refresh the relevant read-only data when a screen is opened or a
  dataset/symbol is selected — not via a button.
- Always show a **"last synced" / "auto-synced" timestamp** instead of a refresh button.
- Keep manual control only where it hits the live API destructively (placing/canceling orders,
  backfill, wipe). Read refreshes are automatic.

### Charts
- Equity curve: line + area-gradient fill, 3 gridlines, crosshair on mouse-move with a dot at the
  hovered point and a tooltip (date, €value, % vs start). Use Plotly via `gr.Plot`.
- Candlestick: standard OHLC candles (green up / red down), crosshair + O/H/L/C tooltip.
- Charts must re-read theme colors when the theme changes.

### Theme switching
- Header swatches + Settings cards switch between Carbon / Slate / Daylight by swapping a set of
  CSS custom properties on the root. Default Carbon. Charts repaint on switch.

---

## State Management

Reuse / extend `src/cryptrink/web/state.py` (`RuntimeState` singleton). State the UI needs:
- `screen` (active sidebar item) — drives which view renders.
- `mode` — `"paper" | "live"`, plus the gating for confirm dialogs.
- `live_running`, `live_engine_id`, `last_signal`, loop counters (iterations/signals/exec/errors).
- `theme` — `"carbon" | "slate" | "daylight"` (cosmetic; can be client-side).
- A shared **log buffer** (source, level, time, message) that every module appends to and the
  terminal renders + filters.
- Cached read snapshots with timestamps: connection status, symbol list, dataset list, positions,
  orders, balance, watchlist — each refreshed on startup/focus, each carrying a `last_synced`.

## Design Tokens (Carbon, the default theme)

```
--bg        #14171c     --text     #e7e9ec    --pos      #3fd98a (gains, BUY/long)
--surface   #1b1f25     --dim      #9aa1ab    --neg      #f0616d (losses, SELL/short)
--surface2  #232830     --faint    #6b7280    --paper    #f0b54a (paper-mode amber)
--border    #2e343d     --accent   #3fd9a8    --live     #ef4658 (live-mode red)
--accent-dim #1f6b56    --accent-soft #16302a
```
Slate and Daylight token sets are in `Cryptrink.dc.html` (the `THEMES` object in the logic class).

- **Type**: IBM Plex Sans (UI), IBM Plex Mono (all numbers, prices, log lines, IDs).
- **Radius**: cards 11px, buttons/inputs 8px, chips/badges 4–6px.
- **Spacing**: screen padding 22–26px; card padding 13–16px; grid gaps 12–20px.
- **Base font size** 13px; metric values 19–22px; screen title 20px.
- **App is desktop-width** (min ~1180px); it is not a responsive/mobile layout.

## Assets

None external. Coin glyphs are CSS-colored monospace initials (BTC/ETH/SOL/…), not image files.
Fonts load from Google Fonts (IBM Plex Sans + Mono). No logos or brand assets.

## Files

- `Cryptrink.dc.html` — the full interactive prototype. Open it in a browser to click through
  every screen, the theme switch, the paper/live banner + confirm dialogs, the global terminal
  filters, and the chart crosshairs. All values are realistic mock data wired to the real module
  vocabulary (strategies, datasets, modes, Revolut X).
- `support.js` — the prototype's small runtime (needed for the HTML to render). Not relevant to
  the Gradio implementation.

## Implementation order (suggested)

1. Workspace shell: header + mode banner + sidebar + status rail + docked global terminal, with
   the shared log buffer feeding the terminal.
2. Port the two priority screens — **Portfolio** and **Live** — including the safety confirm flow.
3. Wire **automation**: startup sync + focus-refresh + last-synced stamps; delete the old per-tab
   log boxes and manual refresh buttons.
4. Port Backtest / Suggest / Data / Dashboard / Settings.
5. Optional: Slate + Daylight themes.
