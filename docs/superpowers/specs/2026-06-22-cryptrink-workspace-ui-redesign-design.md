# Cryptrink Workspace UI Redesign — Design Spec

Date: 2026-06-22
Status: Approved (design), pending implementation
Source of truth: `design_handoff_ui_redesign/README.md` + `design_handoff_ui_redesign/Cryptrink.dc.html`

## 1. Goal

Replace the current 6-flat-tab Gradio app (`src/cryptrink/web/`) with a single **workspace**:
a persistent header + mode banner, a workflow-grouped sidebar, a right status rail, one docked
global terminal, automated refresh, interactive charts, and a loud paper/live safety model.

This is a **re-organisation and re-skin** of an existing surface — **no new engine features**.
Engine modules under `src/cryptrink/{backtest,portfolio,execution,data,exchange,strategies,risk,
notifications,...}` are **not touched**. `web/live_loop.py` and `web/live_setup.py` are treated as
engine-adjacent and left intact (only consumed, never re-shaped).

## 2. Confirmed scope

- **All 7 screens** are redesigned in this PR: Portfolio, Live, Dashboard (new), Backtest,
  Suggest, Data, Settings (new) — plus the full workspace shell.
- **Plotly** is added as a `[web]` extra dependency for interactive equity + candlestick charts.
- **Carbon** theme fully implemented; all 3 theme variable sets (Carbon/Slate/Daylight) wired with
  a client-side header switch. Slate/Daylight visual polish and chart-colour-repaint-on-switch are
  acceptable follow-ups.
- The app must remain **fully functional** and **all 795 currently-passing tests must stay green**
  (13 are skipped live-API integration tests).

## 3. Hard guardrails (test-pinned — must NOT change)

Six test files exercise the web layer (`tests/unit/test_web_app.py`, `test_state_symbols.py`,
`test_backtest_tab.py`, `test_data_tab.py`, `test_live_loop.py`, `test_live_setup.py`).

Preserve exactly:

- `web/app.py`: `build_demo() -> gr.Blocks` (must render every screen without raising; calls
  `get_runtime()` first), `log_credential_status(settings)`, `_classify_db_url` tag outputs,
  `__all__ = ["build_demo", "log_credential_status"]`.
- `web/state.py`: `get_runtime`, `reset_runtime`, `get_symbol_choices`, `set_cached_symbols`,
  `default_symbol`, `list_datasets`, `list_datasets_sync`, `flush_runtime`, `WebRuntime`
  (dataclass; existing fields `settings`, `session_factory`, `cached_symbols` keep their positions
  + defaults), `Dataset` (`.label`/`.value`/`parse`), and the module global `_runtime`.
  Tests set `web_state._runtime` directly and read `runtime.session_factory.kw["bind"]`.
- `web/tabs/data.py`: `_LOG`, `_LOG_MAX_LINES == 200`, `_render_terminal()`, `_emit(msg)` (returns a
  ```fenced``` block), `clear_log()`, `_format_db_size(url)`, and the async handlers
  `refresh_counts`, `database_overview`, `reset_database`, `db_diagnostics`, `force_checkpoint`,
  `wipe`, `refresh_symbols`, `backfill` (async generator) — **including their many exact log-marker
  strings** (e.g. `count: starting`, `reset: COMPLETE`, `PRAGMA wal_checkpoint(FULL)`,
  `stopped because Revolut X has no data older than`, …).
- `web/tabs/backtest.py`: `_PLOT_MAX_POINTS == 200`, `_subsample`, `_format_date_axis`,
  `autofill_dates`, and the module globals `_emit`, `_emit_failure`, `_format_elapsed`,
  `_render_terminal`, `_manual_panels`, `_tuning_panels` that `backtest_tuning.py` imports at
  runtime. `run_backtest` keeps its streamed output arity.
- `web/live_loop.py`: `LiveLoop` ctor kwargs, `LiveLoopState`, `get/set/reset_active_loop`, private
  `_task`/`_heartbeat_task`. Untouched.
- `web/live_setup.py`: `LiveMode.PAPER/.LIVE`, `has_revolutx_credentials`, `build_live_components`
  signature, `LiveComponents.mode/.data_feed/.notifier/.cleanup`. Untouched. (Tests patch
  `cryptrink.execution.engine.TradingEngine` and `cryptrink.exchange.revolutx.RevolutXExchange` at
  their definition modules — keep those import paths.)
- Any **new** module-level mutable web state must have a reset hook (autouse fixture friendly),
  because the suite runs under `pytest-xdist -n=auto` with `asyncio_mode=auto`.

`web/tabs/portfolio.py` and `web/tabs/live.py` have **no behavioural tests** (only the `build_demo`
smoke test guards them) — these are the low-risk rebuild targets.

## 4. Environment notes (not repo changes)

- Effective Gradio is **6.14.0** (pyproject ceiling `<7.0`). APIs must match Gradio 6.
- Python is **3.13–3.14** (`requires-python >=3.13,<3.15`). The dev box only has 3.14, whose env
  needs `greenlet` pip-installed for SQLAlchemy async — a local quirk, **not** a dependency change
  (greenlet is transitive and ships 3.13 wheels for CI/HF).
- Lint/type gates: ruff (line-length 100, double quotes, broad rule set) and **mypy strict**
  (`mypy src/`, pydantic plugin). New web code must pass both. plotly may need a documented
  `# type: ignore[import-untyped]`.

## 5. Architecture

One `gr.Blocks` workspace with persistent chrome and a single swappable main panel.

```
#ck-root  (root container; theme class ck-theme-carbon|slate|daylight)
├─ Header        logo · exchange-connection pill · account balance · "synced" stamp · 3 theme swatches
├─ Mode banner   PAPER (amber, static dot) / LIVE (red, pulsing dot) + Go-live / Switch-to-paper
├─ Body (CSS grid 212px · 1fr · 296px)
│  ├─ Sidebar    workflow groups: Research(Backtest,Portfolio) · Trade(Suggest,Live) ·
│  │             Monitor(Dashboard) · System(Data,Settings); active item highlighted, live badge ●
│  ├─ Main       sticky screen header (title+subtitle+auto-synced stamp) + 7 visibility-toggled panels
│  └─ Rail       Live-loop card · Today (P&L) · Positions · Watchlist (auto-refresh)
├─ Docked terminal   single shared log stream + source filter chips (all/sys/data/backtest/live) + clear
└─ Confirm overlay   blocking red modal (paper→live, start-LIVE-loop)
```

### New / changed modules
- `web/app.py` — `build_demo()` stays the entrypoint; delegates chrome to `web/shell.py`.
- `web/shell.py` (new) — header, mode banner, sidebar, rail, docked terminal, confirm overlay,
  screen-switching wiring, startup-sync + focus-refresh automation, theme CSS + switch JS.
- `web/charts.py` (new) — Plotly figure builders: `equity_curve_figure(...)`,
  `candlestick_figure(...)`, both theme-colour-aware (Carbon now; param for later repaint).
- `web/theme.py` (new) — the 3 token sets + CSS string + fonts `<head>` + theme-switch JS.
- `web/screens/dashboard.py` (new) — thin read-only monitoring view.
- `web/screens/settings.py` (new) — connection + risk defaults + appearance.
- `web/tabs/{portfolio,live,backtest,suggest,data,status}.py` — `render()` refactored to build a
  **screen panel** (no `gr.Tab` wrapper) styled with `elem_classes`. Status content is folded into
  the new Dashboard; the `status.py` dataframe builders are reused.

### State (`web/state.py` extension)
Add to `WebRuntime` (after existing fields, with defaults, so the dataclass shape stays
test-compatible):
- `mode: str = "paper"` → `get_mode()` / `set_mode(mode)` (thread-safe).
- shared log buffer: `collections.deque[LogEvent]` (`maxlen=500`) guarded by a `threading.Lock`;
  helpers `log_event(source, level, message)`, `get_log_events(source_filter=None)`,
  `clear_log_events()`. `LogEvent` = `(time, source, level, message)`.
- cached read-snapshots with `last_synced` timestamps (connection status, dataset list, positions,
  orders, balance, watchlist) + `mark_synced(key)` / accessor helpers. `cached_symbols` stays.

`live_running` is **derived** from the existing `get_active_loop()` (no new flag).
Per-session `screen` and `theme` live in `gr.State` / client-side, **not** the global singleton
(the singleton is process-global across all browser sessions; this is a single-operator Space, so
`mode`/log/snapshots living globally is acceptable and matches the existing live-loop singleton).

`reset_runtime()` already nulls the whole singleton, so it clears the new fields too.

## 6. Screen specs

1. **Portfolio** (priority) — left 300px: Portfolios picker + Allocations card (coin badge, symbol,
   strategy, weight bar) + Run-backtest / Edit-YAML; right: 4 metrics (Total return, Sharpe, Max
   drawdown, Win rate) + interactive Plotly equity curve + per-allocation breakdown table. Reuses
   `PortfolioBacktestEngine.run`, the YAML round-trip, and existing handlers; swaps the matplotlib
   equity PNG for `gr.Plot`+Plotly.
2. **Live** (priority) — mode callout; left: Plotly candlestick (1h, from **stored OHLCV** for the
   selected dataset) + Loop-activity stats (Iterations/Signals/Executions/Errors); right: Loop
   configuration card (Strategy, Dataset, Interval, Paper balance; `Advanced` details for risk +
   Discord heartbeat) with Start/Stop + Test-connection / Pre-flight, and a Loop-status card
   (Symbol, Strategy, Interval, Mode, Engine ID, Last signal). Start routes through the confirm
   dialog when mode == live. Keeps the creds-conditional render branches.
3. **Dashboard** (new) — 4 metrics (Account equity, Open P&L, Realised 30d, Active engines) + Open
   positions table + Recent orders table. Read-only aggregation of `status.py`'s data
   (`PositionRepository`/`OrderRepository`/`EngineState`). Auto-loads on focus.
4. **Backtest** — left config card (Strategy, Dataset, Start, Capital; two collapsed `details`:
   Strategy parameters, Auto-tuning grid/TPE); right 4 metrics + Plotly equity. Preserves all
   pinned helpers + `backtest_tuning` coupling; charts move to Plotly while the matplotlib helpers
   (`_subsample`, `_format_date_axis`) are kept for tests.
5. **Suggest** — single input row (Strategy, Dataset, Suggest) + result card (big BUY/SELL/HOLD
   verdict, strength badge, key/value grid). Preserves `run_suggest` returning its dict.
6. **Data** — backfill row (Symbol, Timeframe, Start, Backfill) + Stored-datasets table (auto-loads
   on focus) + maintenance ops (wipe/reset/checkpoint) behind an `Advanced` disclosure. Preserves
   every pinned handler + `_emit`/`_LOG`/`_render_terminal`/`_format_db_size` and exact strings.
7. **Settings** (new) — Revolut X connection card (API key masked, private-key status, base URL,
   webhook), Risk defaults card (from config), Appearance card (the 3 theme swatches). Read-only
   display of config.

## 7. Cross-cutting behaviour

- **Safety model:** `mode` is authoritative server-side. paper→live and start-LIVE-loop open the
  confirm overlay with the prototype's verbatim copy; live→paper and paper-start are immediate.
  Live Start button is teal (paper) / red "Start LIVE loop" (live) / red "Stop" (running).
- **Global terminal:** one `gr.HTML` renders `get_log_events(filter)`; `gr.Timer` auto-refreshes;
  filter chips drive a `gr.State`; `clear` empties the buffer. Line = `time · source · message`,
  monospace, message coloured by level (ok/info/warn/err), source-tag coloured per source. Every
  action calls `log_event(...)`. Data's tested `_emit`/`_LOG` are retained and **also** mirrored
  into the shared buffer so Data logs appear globally.
- **Automation:** `demo.load` runs startup sync (connection, symbol vocabulary, dataset list) →
  logs each + sets last-synced stamps; screen-focus refreshes that screen's read-only data; rail +
  terminal auto-refresh via `gr.Timer`. User-facing manual **read**-refresh buttons are removed
  (the handlers stay and are re-wired to auto-triggers / focus / timer). Destructive actions
  (backfill, wipe, reset, order placement) keep explicit buttons + confirms.
- **Charts:** Plotly via `gr.Plot`. Equity = line + area gradient + `hovermode="x unified"` + axis
  spikes (crosshair + date/€value/% tooltip). Candlestick = `go.Candlestick` (green up/red down) +
  spikes (O/H/L/C tooltip). Carbon colours now; a `theme_colors` param leaves room for repaint.
- **Theming:** `gr.Blocks(css=..., head=<IBM Plex fonts>)` carries all 3 token sets, component
  classes, and `@keyframes` (`ck-pulse`, `ck-blink`, `ck-fadein`). Header swatches swap the
  `ck-theme-*` class on `#ck-root` via `js=` (client-side, no Python round-trip).

## 8. Design tokens (Carbon default)

```
--bg #14171c  --surface #1b1f25  --surface2 #232830  --border #2e343d
--text #e7e9ec  --dim #9aa1ab  --faint #6b7280
--accent #3fd9a8  --accent-dim #1f6b56  --accent-soft #16302a
--pos #3fd98a  --neg #f0616d  --paper #f0b54a  --live #ef4658
--live-glow rgba(239,70,88,0.5)  --shadow rgba(0,0,0,0.4)
```
Slate and Daylight token sets are captured from `Cryptrink.dc.html`'s `THEMES` object.
Type: IBM Plex Sans (UI) + IBM Plex Mono (numbers/IDs/log). Radius: cards 11px, buttons/inputs 8px,
chips 4–6px, dialog 14px. Base font 13px; metric values 19–22px; screen title 20px. Desktop-width
(min ~1180px), not responsive.

## 9. Build order (phased; verify between each)

1. **Foundation** — add `plotly` to `[web]`/`[all]` extras + `poetry lock` + `requirements.txt`;
   `web/theme.py` (CSS + tokens + fonts + switch JS); `web/state.py` extensions (mode, log buffer,
   snapshots) with new unit tests + reset hook.
2. **Shell + Portfolio + Live** — `web/shell.py` chrome, screen switching, automation, confirm
   overlay; rebuild Portfolio + Live screens incl. Plotly charts + safety confirm.
3. **Dashboard + Settings** — new read-only screens.
4. **Backtest / Suggest / Data** — restyle into the shell, preserving every pinned contract.
5. **Verify + polish** — full `pytest` + `ruff` + `mypy`; launch the app and screenshot each screen,
   the theme switch, the paper/live banner + confirm dialogs, the terminal filters, the charts;
   Slate/Daylight polish; open the PR.

## 10. Risks & mitigations

- *Gradio fighting custom CSS* → launch the real app and screenshot every screen; iterate on CSS.
- *mypy-strict on plotly* → documented `# type: ignore[import-untyped]` per project convention.
- *Breaking exact strings while restyling Data/Backtest* → keep handler bodies/strings; only change
  layout + where outputs are wired; re-run the pinned tests after each edit.
- *xdist parallelism vs new global state* → add reset hooks; keep new state inside `WebRuntime` so
  `reset_runtime()` clears it.
- *Large PR* → one branch, five reviewable phases, green tests at each boundary.
