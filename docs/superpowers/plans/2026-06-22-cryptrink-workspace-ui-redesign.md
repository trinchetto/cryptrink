# Cryptrink Workspace UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Cryptrink Gradio web UI (`src/cryptrink/web/`) as a single workspace — header + mode banner + workflow sidebar + status rail + docked global terminal + paper/live safety model + interactive Plotly charts — matching `design_handoff_ui_redesign/Cryptrink.dc.html`, with all 7 screens redesigned, engine modules untouched, and all 795 tests staying green.

**Architecture:** One `gr.Blocks` workspace. Persistent chrome (header/banner/sidebar/rail/terminal/confirm-overlay) built by a new `web/shell.py`; a single main area holds 7 visibility-toggled screen panels. Theming via a big `css=` string + 3 CSS-variable token sets swapped client-side. Charts via Plotly in `gr.Plot`. Cross-screen state (mode, shared log buffer, cached snapshots) added to the existing `WebRuntime` singleton in `web/state.py`.

**Tech Stack:** Python 3.13/3.14, Gradio 6.14, Plotly (new dep), pandas, SQLAlchemy async, pytest + pytest-xdist + pytest-asyncio, ruff (line 100), mypy strict.

---

## Reference material (read before starting)

- Spec: `docs/superpowers/specs/2026-06-22-cryptrink-workspace-ui-redesign-design.md` — esp. §3 Guardrails and §8 tokens.
- Prototype: `design_handoff_ui_redesign/Cryptrink.dc.html` — verbatim styles, copy text, the `THEMES` object (3 token sets), screen layouts. When a step says "use prototype styling", the exact hex/px values are in there and in spec §8.
- Handoff README: `design_handoff_ui_redesign/README.md`.

## Environment (one-time, already done in this worktree; redo if env missing)

```bash
poetry env use /opt/homebrew/opt/python@3.14/bin/python3.14
poetry install --with dev --all-extras
poetry run pip install greenlet   # local 3.14 quirk; transitive elsewhere
```

Test/lint/type commands used throughout:
```bash
poetry run pytest -q                       # full suite (≈70s)
poetry run pytest tests/unit/test_web_app.py tests/unit/test_state_symbols.py -q   # fast web subset
poetry run ruff check src tests
poetry run ruff format --check src tests
poetry run mypy src/
```

Launch the app for visual verification:
```bash
poetry run python app.py    # serves on http://127.0.0.1:7860
```

---

## File Structure

**New files**
- `src/cryptrink/web/theme.py` — 3 token sets, the global CSS string, fonts `<head>` HTML, theme-switch JS, button/style class names.
- `src/cryptrink/web/charts.py` — Plotly figure builders (`equity_curve_figure`, `candlestick_figure`) + a `ThemeColors` value object.
- `src/cryptrink/web/shell.py` — chrome (header, banner, sidebar, rail, docked terminal, confirm overlay), screen-switch wiring, startup-sync + focus-refresh automation.
- `src/cryptrink/web/screens/__init__.py` — package marker.
- `src/cryptrink/web/screens/dashboard.py` — new read-only monitoring screen + its data builders.
- `src/cryptrink/web/screens/settings.py` — new connection/risk/appearance screen.
- `tests/unit/test_state_runtime_ui.py` — tests for the new `state.py` UI state (mode, log buffer, snapshots).
- `tests/unit/test_charts.py` — tests for `charts.py` figure builders.
- `tests/unit/test_dashboard_screen.py` — tests for dashboard data builders.
- `tests/unit/test_settings_screen.py` — tests for settings data builders.
- `tests/unit/test_shell.py` — tests for shell pure helpers (nav model, terminal HTML render, banner HTML).

**Modified files**
- `src/cryptrink/web/state.py` — extend `WebRuntime` + add UI-state helpers (mode/log/snapshots).
- `src/cryptrink/web/app.py` — `build_demo()` builds the workspace via `shell.py` (still returns `gr.Blocks`, still calls `get_runtime()` + `log_credential_status()`).
- `src/cryptrink/web/tabs/portfolio.py` — `render()` builds the new Portfolio **panel** (no `gr.Tab`), Plotly equity.
- `src/cryptrink/web/tabs/live.py` — `render()` builds the new Live **panel**, Plotly candlestick from stored OHLCV, safety confirm hooks.
- `src/cryptrink/web/tabs/backtest.py` — `render()` builds the new Backtest **panel**; charts → Plotly; keep all pinned helpers.
- `src/cryptrink/web/tabs/suggest.py` — `render()` builds the new Suggest **panel**; keep `run_suggest`.
- `src/cryptrink/web/tabs/data.py` — `render()` builds the new Data **panel**; keep all pinned handlers/strings; mirror `_emit` into the shared buffer.
- `src/cryptrink/web/tabs/status.py` — keep `refresh()` + dataframe builders (reused by Dashboard); `render()` no longer mounts a tab (Dashboard replaces it). Keep functions importable.
- `pyproject.toml` — add `plotly` to `[web]`/`[all]` extras.
- `requirements.txt` — add `plotly==<locked>` (HF Space build).

**Conventions for every task**
- Money stays `Decimal` in engine calls; convert to float/str only at the display boundary.
- `from __future__ import annotations`; `TYPE_CHECKING` imports per CLAUDE.md.
- ruff line length 100, double quotes. mypy strict; document any `# type: ignore`.
- After any change touching a pinned module, run the relevant pinned test file before committing.

---

## Phase 1 — Foundation

### Task 1: Add Plotly dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`

- [ ] **Step 1: Add plotly to extras in `pyproject.toml`**

In `[tool.poetry.extras]` (or the PEP 621 `[project.optional-dependencies]` block this repo uses), add `plotly` to both the `web` and `all` extra lists, and add the dependency declaration alongside gradio:

```toml
# in the dependency table that holds gradio:
plotly = { version = ">=5.24,<7.0", optional = true }
# and append "plotly" to extras.web and extras.all
```
(Match the exact table style already used for `gradio`/`requests` in this file.)

- [ ] **Step 2: Re-lock**

Run: `poetry lock`
Expected: `poetry.lock` updated, no resolution errors.

- [ ] **Step 3: Install the new dep**

Run: `poetry install --with dev --all-extras`
Expected: plotly installed.

- [ ] **Step 4: Pin plotly in `requirements.txt`**

Find the locked version: `poetry run python -c "import plotly; print(plotly.__version__)"`. Add a line `plotly==<that version>` to `requirements.txt` near `gradio==6.14.0` (alphabetical-ish, matching the file's existing format).

- [ ] **Step 5: Verify import + nothing broke**

Run: `poetry run python -c "import plotly.graph_objects as go; print('plotly ok', go.Figure)"`
Run: `poetry run pytest tests/unit/test_web_app.py -q`
Expected: import ok; web app tests pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml poetry.lock requirements.txt
git commit -m "build(deps): add plotly for interactive web charts"
```

---

### Task 2: Theme tokens, CSS, fonts, switch JS (`web/theme.py`)

**Files:**
- Create: `src/cryptrink/web/theme.py`
- Test: `tests/unit/test_shell.py` (theme portion)

`theme.py` is pure data + string constants (no gradio import), so it is unit-testable.

- [ ] **Step 1: Write failing tests** (`tests/unit/test_shell.py`)

```python
from __future__ import annotations

from cryptrink.web import theme


class TestThemeTokens:
    def test_three_themes_present(self):
        assert set(theme.THEMES) == {"carbon", "slate", "daylight"}

    def test_carbon_is_default(self):
        assert theme.DEFAULT_THEME == "carbon"

    def test_every_theme_defines_the_same_token_keys(self):
        keys = [set(t) for t in theme.THEMES.values()]
        assert all(k == keys[0] for k in keys)
        assert "--accent" in keys[0] and "--bg" in keys[0] and "--live" in keys[0]

    def test_carbon_accent_value(self):
        assert theme.THEMES["carbon"]["--accent"] == "#3fd9a8"

    def test_css_contains_root_and_theme_classes(self):
        css = theme.build_css()
        assert "#ck-root" in css
        assert ".ck-theme-carbon" in css
        assert "@keyframes ck-pulse" in css

    def test_theme_switch_js_is_callable_string(self):
        js = theme.theme_switch_js("slate")
        assert "ck-theme-slate" in js and "ck-root" in js
```

- [ ] **Step 2: Run, verify fail**

Run: `poetry run pytest tests/unit/test_shell.py -q`
Expected: FAIL (module/attrs missing).

- [ ] **Step 3: Implement `theme.py`**

Define `THEMES: dict[str, dict[str, str]]` with the three token sets **verbatim from spec §8 / the prototype `THEMES` object** (carbon, slate, daylight — every `--token`). `DEFAULT_THEME = "carbon"`. Then:

```python
def build_css() -> str:
    """Return the global CSS string passed to gr.Blocks(css=...)."""
    theme_blocks = "\n".join(
        ".ck-theme-%s{%s}" % (name, "".join(f"{k}:{v};" for k, v in tokens.items()))
        for name, tokens in THEMES.items()
    )
    return _BASE_CSS + theme_blocks  # _BASE_CSS holds layout/components/animations


def fonts_head() -> str:
    """<link> tags for IBM Plex Sans + Mono, for gr.Blocks(head=...)."""
    return _FONTS_HEAD


def theme_switch_js(name: str) -> str:
    """JS snippet (for Button.click(js=...)) that swaps the root theme class."""
    return (
        "() => { const r = document.getElementById('ck-root'); if (r) {"
        "['carbon','slate','daylight'].forEach(t => r.classList.remove('ck-theme-'+t));"
        f"r.classList.add('ck-theme-{name}');"
        f"try {{ localStorage.setItem('ck-theme','{name}'); }} catch (e) {{}} }} }}"
    )
```

`_BASE_CSS` contains: `#ck-root` grid (`grid-template-rows:auto auto 1fr auto`), body columns `212px 1fr 296px`, component classes (`.ck-card`, `.ck-metric`, `.ck-nav-item`, `.ck-banner`, `.ck-term`, `.ck-modal`, `.ck-rail`, tooltips, chips, badges), Gradio-neutralising overrides (`gradio-app`, `.gap`, `.form` padding/background resets), and `@keyframes ck-pulse / ck-blink / ck-fadein` — all using the px/colour values from the prototype. Use CSS `var(--token)` everywhere so themes apply.

- [ ] **Step 4: Run tests, verify pass**

Run: `poetry run pytest tests/unit/test_shell.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + type**

Run: `poetry run ruff check src/cryptrink/web/theme.py && poetry run mypy src/cryptrink/web/theme.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/cryptrink/web/theme.py tests/unit/test_shell.py
git commit -m "feat(web): add theme tokens, global CSS, and theme-switch JS"
```

---

### Task 3: Extend `state.py` with mode, shared log buffer, snapshots

**Files:**
- Modify: `src/cryptrink/web/state.py`
- Test: `tests/unit/test_state_runtime_ui.py`

Keep `WebRuntime`'s existing 3 fields and positions; add new fields with defaults. Add free helpers mirroring the `get_symbol_choices`/`set_cached_symbols` pattern. Guard mutable state with a `threading.Lock`.

- [ ] **Step 1: Write failing tests** (`tests/unit/test_state_runtime_ui.py`)

```python
from __future__ import annotations

import pytest

from cryptrink.web import state as web_state


@pytest.fixture(autouse=True)
def _reset():
    web_state.reset_runtime()
    yield
    web_state.reset_runtime()


class TestMode:
    def test_default_mode_is_paper(self):
        assert web_state.get_mode() == "paper"

    def test_set_mode_roundtrips(self):
        web_state.set_mode("live")
        assert web_state.get_mode() == "live"

    def test_set_mode_rejects_unknown(self):
        with pytest.raises(ValueError, match="mode"):
            web_state.set_mode("bogus")


class TestLogBuffer:
    def test_starts_empty(self):
        assert web_state.get_log_events() == []

    def test_log_event_appends_with_fields(self):
        web_state.log_event("sys", "ok", "boot done")
        events = web_state.get_log_events()
        assert len(events) == 1
        e = events[0]
        assert e.source == "sys" and e.level == "ok" and e.message == "boot done"
        assert isinstance(e.time, str) and len(e.time) == 8  # HH:MM:SS

    def test_filter_by_source(self):
        web_state.log_event("sys", "ok", "a")
        web_state.log_event("data", "info", "b")
        assert [e.message for e in web_state.get_log_events("data")] == ["b"]
        assert len(web_state.get_log_events("all")) == 2

    def test_clear(self):
        web_state.log_event("sys", "ok", "a")
        web_state.clear_log_events()
        assert web_state.get_log_events() == []

    def test_buffer_is_bounded(self):
        for i in range(600):
            web_state.log_event("sys", "info", str(i))
        events = web_state.get_log_events()
        assert len(events) == web_state.LOG_BUFFER_MAX
        assert events[-1].message == "599"


class TestSnapshots:
    def test_mark_and_read_last_synced(self):
        assert web_state.get_last_synced("datasets") is None
        web_state.mark_synced("datasets")
        stamp = web_state.get_last_synced("datasets")
        assert isinstance(stamp, str) and len(stamp) == 8
```

- [ ] **Step 2: Run, verify fail**

Run: `poetry run pytest tests/unit/test_state_runtime_ui.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement in `state.py`**

Add near the top:

```python
import threading
from collections import deque

LOG_BUFFER_MAX = 500
_VALID_MODES = ("paper", "live")
_lock = threading.Lock()


class LogEvent(NamedTuple):
    time: str       # HH:MM:SS
    source: str     # sys|data|backtest|portfolio|live|...
    level: str      # ok|info|warn|err
    message: str
```

Add fields to `WebRuntime` (after `cached_symbols`, all defaulted):

```python
    mode: str = "paper"
    log_buffer: deque[LogEvent] = field(default_factory=lambda: deque(maxlen=LOG_BUFFER_MAX))
    last_synced: dict[str, str] = field(default_factory=dict)
```

Add free helpers (use `datetime.now(UTC).strftime("%H:%M:%S")` for timestamps):

```python
def get_mode() -> str:
    return get_runtime().mode


def set_mode(mode: str) -> None:
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
    with _lock:
        get_runtime().mode = mode


def log_event(source: str, level: str, message: str) -> None:
    event = LogEvent(datetime.now(UTC).strftime("%H:%M:%S"), source, level, message)
    with _lock:
        get_runtime().log_buffer.append(event)


def get_log_events(source_filter: str | None = None) -> list[LogEvent]:
    with _lock:
        events = list(get_runtime().log_buffer)
    if source_filter in (None, "all"):
        return events
    if source_filter == "live":
        return [e for e in events if e.source == "live"]
    return [e for e in events if e.source == source_filter]


def clear_log_events() -> None:
    with _lock:
        get_runtime().log_buffer.clear()


def mark_synced(key: str) -> None:
    with _lock:
        get_runtime().last_synced[key] = datetime.now(UTC).strftime("%H:%M:%S")


def get_last_synced(key: str) -> str | None:
    return get_runtime().last_synced.get(key)
```

Confirm `datetime`, `UTC`, `NamedTuple`, `field` are already imported (they are).

- [ ] **Step 4: Run new tests + the pinned state tests**

Run: `poetry run pytest tests/unit/test_state_runtime_ui.py tests/unit/test_state_symbols.py -q`
Expected: PASS (both — existing state contract preserved).

- [ ] **Step 5: Lint + type**

Run: `poetry run ruff check src/cryptrink/web/state.py && poetry run mypy src/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/cryptrink/web/state.py tests/unit/test_state_runtime_ui.py
git commit -m "feat(web): add mode, shared log buffer, and sync snapshots to runtime state"
```

---

### Task 4: Plotly chart builders (`web/charts.py`)

**Files:**
- Create: `src/cryptrink/web/charts.py`
- Test: `tests/unit/test_charts.py`

- [ ] **Step 1: Write failing tests** (`tests/unit/test_charts.py`)

```python
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import plotly.graph_objects as go

from cryptrink.web import charts


def _equity_points():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return [(base.replace(day=1 + i), Decimal(str(10000 + i * 100))) for i in range(5)]


class TestEquityCurveFigure:
    def test_returns_figure(self):
        fig = charts.equity_curve_figure(_equity_points())
        assert isinstance(fig, go.Figure)

    def test_empty_points_returns_empty_figure(self):
        fig = charts.equity_curve_figure([])
        assert isinstance(fig, go.Figure)

    def test_has_a_trace_per_data(self):
        fig = charts.equity_curve_figure(_equity_points())
        assert len(fig.data) >= 1

    def test_uses_unified_hover_for_crosshair(self):
        fig = charts.equity_curve_figure(_equity_points())
        assert fig.layout.hovermode == "x unified"


class TestCandlestickFigure:
    def _candles(self):
        base = datetime(2026, 6, 20, tzinfo=UTC)
        return [
            {"time": base.replace(hour=i), "open": 100.0 + i, "high": 102.0 + i,
             "low": 99.0 + i, "close": 101.0 + i}
            for i in range(6)
        ]

    def test_returns_candlestick_figure(self):
        fig = charts.candlestick_figure(self._candles())
        assert isinstance(fig, go.Figure)
        assert any(isinstance(t, go.Candlestick) for t in fig.data)

    def test_empty_is_safe(self):
        fig = charts.candlestick_figure([])
        assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: Run, verify fail**

Run: `poetry run pytest tests/unit/test_charts.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `charts.py`**

```python
"""Plotly figure builders for the web UI (interactive equity + candlestick)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import plotly.graph_objects as go  # type: ignore[import-untyped]

from cryptrink.web import theme

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


@dataclass(frozen=True)
class ThemeColors:
    accent: str
    pos: str
    neg: str
    border: str
    faint: str
    surface: str
    text: str
    bg: str

    @classmethod
    def for_theme(cls, name: str = theme.DEFAULT_THEME) -> ThemeColors:
        t = theme.THEMES.get(name, theme.THEMES[theme.DEFAULT_THEME])
        return cls(
            accent=t["--accent"], pos=t["--pos"], neg=t["--neg"], border=t["--border"],
            faint=t["--faint"], surface=t["--surface"], text=t["--text"], bg=t["--bg"],
        )


def _base_layout(colors: ThemeColors) -> dict[str, object]:
    return {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "margin": {"l": 8, "r": 8, "t": 10, "b": 24},
        "font": {"color": colors.dim if hasattr(colors, "dim") else colors.faint,
                 "family": "IBM Plex Mono, monospace", "size": 11},
        "hovermode": "x unified",
        "showlegend": False,
        "xaxis": {"showgrid": False, "showspikes": True, "spikethickness": 1,
                  "spikedash": "dot", "spikecolor": colors.faint, "spikemode": "across",
                  "color": colors.faint},
        "yaxis": {"gridcolor": colors.border, "griddash": "solid", "nticks": 4,
                  "color": colors.faint},
    }


def equity_curve_figure(
    points: list[tuple[datetime, Decimal]], theme_name: str = theme.DEFAULT_THEME
) -> go.Figure:
    colors = ThemeColors.for_theme(theme_name)
    fig = go.Figure(layout=_base_layout(colors))
    if not points:
        return fig
    xs = [p[0] for p in points]
    ys = [float(p[1]) for p in points]
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines", line={"color": colors.accent, "width": 1.8},
        fill="tozeroy", fillcolor=_alpha(colors.accent, 0.18),
        hovertemplate="€%{y:,.0f}<extra></extra>",
    ))
    # tighten y range to the data so the area fill reads like the prototype
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.08 or 1.0
    fig.update_yaxes(range=[lo - pad, hi + pad])
    return fig


def candlestick_figure(
    candles: list[dict[str, object]], theme_name: str = theme.DEFAULT_THEME
) -> go.Figure:
    colors = ThemeColors.for_theme(theme_name)
    fig = go.Figure(layout=_base_layout(colors))
    if not candles:
        return fig
    fig.add_trace(go.Candlestick(
        x=[c["time"] for c in candles],
        open=[c["open"] for c in candles], high=[c["high"] for c in candles],
        low=[c["low"] for c in candles], close=[c["close"] for c in candles],
        increasing={"line": {"color": colors.pos}, "fillcolor": colors.pos},
        decreasing={"line": {"color": colors.neg}, "fillcolor": colors.neg},
    ))
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


def _alpha(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"
```
Note: drop the `colors.dim` ref in `_base_layout` (ThemeColors has no `dim`) — use `colors.faint`. Fix during implementation.

- [ ] **Step 4: Run tests, verify pass**

Run: `poetry run pytest tests/unit/test_charts.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + type**

Run: `poetry run ruff check src/cryptrink/web/charts.py && poetry run mypy src/`
Expected: clean (the documented `# type: ignore[import-untyped]` on plotly import is acceptable per CLAUDE.md).

- [ ] **Step 6: Commit**

```bash
git add src/cryptrink/web/charts.py tests/unit/test_charts.py
git commit -m "feat(web): add Plotly equity-curve and candlestick figure builders"
```

---

## Phase 2 — Shell + Portfolio + Live

### Task 5: Shell pure helpers (nav model, terminal/banner/rail HTML)

**Files:**
- Create: `src/cryptrink/web/shell.py` (helpers first; gradio assembly in Task 6)
- Test: `tests/unit/test_shell.py` (append)

Build the testable pure functions before the gradio wiring.

- [ ] **Step 1: Write failing tests** (append to `tests/unit/test_shell.py`)

```python
from cryptrink.web import shell
from cryptrink.web.state import LogEvent


class TestNavModel:
    def test_groups_and_screens(self):
        groups = shell.NAV_GROUPS
        labels = [g.label for g in groups]
        assert labels == ["Research", "Trade", "Monitor", "System"]
        keys = [item.key for g in groups for item in g.items]
        assert keys == ["backtest", "portfolio", "suggest", "live", "dashboard", "data", "settings"]

    def test_screen_meta_has_title_and_subtitle(self):
        title, sub = shell.SCREEN_META["portfolio"]
        assert "Portfolio" in title and sub


class TestTerminalHtml:
    def test_renders_lines_with_classes(self):
        events = [LogEvent("09:14:02", "sys", "ok", "boot done")]
        html = shell.terminal_html(events)
        assert "boot done" in html and "09:14:02" in html and "sys" in html

    def test_empty_shows_placeholder_cursor(self):
        html = shell.terminal_html([])
        assert "ck-term" in html or "›" in html  # blinking cursor row always present


class TestBannerHtml:
    def test_paper_banner(self):
        html = shell.banner_html("paper")
        assert "PAPER" in html and "no real orders" in html.lower()

    def test_live_banner_is_pulsing_red(self):
        html = shell.banner_html("live")
        assert "LIVE" in html and "ck-pulse" in html
```

- [ ] **Step 2: Run, verify fail**

Run: `poetry run pytest tests/unit/test_shell.py -q`
Expected: FAIL (shell helpers missing).

- [ ] **Step 3: Implement helpers in `shell.py`**

Define dataclasses + constants + pure render functions:

```python
@dataclass(frozen=True)
class NavItem:
    key: str       # screen id
    tag: str       # 2-letter mono chip, e.g. "PF"
    label: str

@dataclass(frozen=True)
class NavGroup:
    label: str
    items: tuple[NavItem, ...]

NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup("Research", (NavItem("backtest", "BT", "Backtest"), NavItem("portfolio", "PF", "Portfolio"))),
    NavGroup("Trade", (NavItem("suggest", "SG", "Suggest"), NavItem("live", "LV", "Live"))),
    NavGroup("Monitor", (NavItem("dashboard", "DB", "Dashboard"),)),
    NavGroup("System", (NavItem("data", "DT", "Data"), NavItem("settings", "ST", "Settings"))),
)

SCREEN_ORDER = [item.key for g in NAV_GROUPS for item in g.items]

SCREEN_META: dict[str, tuple[str, str]] = {
    "dashboard": ("Dashboard", "Engine state, open positions, and order history across paper and live sessions."),
    "backtest": ("Backtest", "Replay a single strategy over a stored dataset. Tune by hand or sweep with the optimizer."),
    "portfolio": ("Portfolio", "Build a multi-pair portfolio sharing one cash pool, then backtest the whole allocation in one run."),
    "suggest": ("Suggest", "Generate a one-shot trade suggestion from the latest stored candle. No order is placed."),
    "live": ("Live trading", "Run a strategy on a periodic interval against Revolut X. Paper replays locally; live places real orders."),
    "data": ("Data", "Historical OHLCV the research and trading engines read from. Backfilled from Revolut X and auto-synced on startup."),
    "settings": ("Settings", "Connection, default risk limits, and appearance. The knobs that rarely change live here, out of the workflow."),
}

_SRC_CLASS = {"sys": "ck-src-sys", "data": "ck-src-data", "backtest": "ck-src-bt",
              "portfolio": "ck-src-pf", "live": "ck-src-live"}
_LVL_CLASS = {"ok": "ck-lvl-ok", "info": "ck-lvl-info", "warn": "ck-lvl-warn", "err": "ck-lvl-err"}


def terminal_html(events: list[LogEvent]) -> str:
    rows = "".join(
        f'<div class="ck-term-line"><span class="ck-term-tm">{_esc(e.time)}</span>'
        f'<span class="ck-term-src {_SRC_CLASS.get(e.source, "")}">{_esc(e.source)}</span>'
        f'<span class="ck-term-msg {_LVL_CLASS.get(e.level, "")}">{_esc(e.message)}</span></div>'
        for e in events
    )
    cursor = '<div class="ck-term-cursor">›<span class="ck-blink-block"></span></div>'
    return f'<div class="ck-term-body" id="ck-term">{rows}{cursor}</div>'


def banner_html(mode: str) -> str:
    if mode == "live":
        return ('<div class="ck-banner ck-banner-live"><span class="ck-dot ck-pulse"></span>'
                '<b>LIVE TRADING</b><span>Real orders are placed on Revolut X with account funds.</span></div>')
    return ('<div class="ck-banner ck-banner-paper"><span class="ck-dot"></span>'
            '<b>PAPER TRADING</b><span>Simulated against stored data — no real orders.</span></div>')


def _esc(s: str) -> str:
    import html as _h
    return _h.escape(str(s))
```
(Use the exact prototype copy text. Add a `header_*`, `rail_html`, `screen_header_html(screen, synced)` helper in the same style — pure string builders — as needed; mirror their styling classes to the CSS in `theme.py`.)

- [ ] **Step 4: Run tests, verify pass**

Run: `poetry run pytest tests/unit/test_shell.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cryptrink/web/shell.py tests/unit/test_shell.py
git commit -m "feat(web): add shell nav model and terminal/banner HTML renderers"
```

---

### Task 6: Assemble the workspace shell in `build_demo()`

**Files:**
- Modify: `src/cryptrink/web/shell.py` (add `build_workspace(...)`)
- Modify: `src/cryptrink/web/app.py`
- Test: `tests/unit/test_web_app.py` (existing smoke test must still pass)

This task wires the chrome. The screen panels are placeholders here; Tasks 7–13 fill them. Verified by `build_demo()` returning Blocks + a manual launch.

- [ ] **Step 1: Implement `build_workspace()` in `shell.py`**

Signature: `def build_workspace(screen_builders: dict[str, Callable[[], None]]) -> None`. Inside the caller's `gr.Blocks` context it builds:
  - root `gr.Column(elem_id="ck-root", elem_classes=["ck-theme-carbon"])`.
  - header `gr.Row` (logo/pill/balance/synced HTML + 3 theme `gr.Button`s wired with `js=theme.theme_switch_js(name)` and no Python fn).
  - banner: `gr.HTML(banner_html("paper"), elem_id="ck-banner")` + a `gr.Button` ("Go live →") whose click opens the confirm overlay (Task 8 wires the action).
  - body `gr.Row`: sidebar `gr.Column` of nav `gr.Button`s (built from `NAV_GROUPS`), main `gr.Column` with a sticky screen-header `gr.HTML` + one `gr.Group(visible=...)` per screen calling `screen_builders[key]()` inside it, rail `gr.HTML` (+`gr.Timer`).
  - docked terminal: header row (caret toggle button, filter chips `gr.Button`s, clear button) + `gr.HTML(terminal_html(...))` refreshed by `gr.Timer(1.0)`; a `gr.State` holds the active source filter.
  - confirm overlay: `gr.Group(elem_classes=["ck-modal"], visible=False)` with title/body `gr.HTML`, Cancel + Confirm `gr.Button`s; a `gr.State` holds the pending action key (`"go_live"` | `"start_live_loop"`).
  - Screen switching: each nav button `.click` → a handler returning `[gr.update(visible=...) for each screen] + [screen_header_html]` and setting the `screen` `gr.State`; also triggers that screen's focus-refresh (Task 14).
  - `demo.load(...)` → startup sync (Task 14).

Return the components the app needs to reference (or keep them internal; expose via a small dataclass if needed for tests — not required).

- [ ] **Step 2: Rewrite `build_demo()` in `app.py`**

```python
def build_demo() -> gr.Blocks:
    runtime = get_runtime()
    log_credential_status(runtime.settings)
    with gr.Blocks(title="Cryptrink", css=theme.build_css(), head=theme.fonts_head()) as demo:
        shell.build_workspace({
            "backtest": backtest.render,
            "portfolio": portfolio.render,
            "suggest": suggest.render,
            "live": live.render,
            "dashboard": dashboard.render,
            "data": data.render,
            "settings": settings.render,
        })
    return demo  # type: ignore[no-any-return]
```
Update imports: `from cryptrink.web import shell, theme`; `from cryptrink.web.screens import dashboard, settings`; keep `from cryptrink.web.tabs import backtest, data, live, portfolio, suggest` (drop `status` from this import path — but keep `status.py` importable for Dashboard reuse). Keep `__all__` and `log_credential_status` unchanged.

Note: until Tasks 7+ land, point `dashboard.render`/`settings.render` at temporary stubs (a one-line `gr.Markdown`) so `build_demo()` doesn't raise. Create minimal `screens/__init__.py`, `screens/dashboard.py`, `screens/settings.py` with stub `render()` now; flesh out later.

- [ ] **Step 3: Make the existing tab `render()`s panel-safe (temporary)**

Each `tabs/*.render()` still opens `with gr.Tab(...)`. For the shell to mount them inside a `gr.Group`, change each `render()` to **not** open a `gr.Tab` — instead build directly in the current context. Do the minimal mechanical change now (replace `with gr.Tab("X"):` with `with gr.Column():` or no wrapper); full restyle comes in Tasks 7–13. This keeps `build_demo()` working.

- [ ] **Step 4: Run the smoke test**

Run: `poetry run pytest tests/unit/test_web_app.py -q`
Expected: PASS (`build_demo()` returns `gr.Blocks`, renders all screens without raising).

- [ ] **Step 5: Manual launch check**

Run: `poetry run python app.py` (then stop). Confirm it boots without exceptions in the log. (Full visual check in Task 15.)

- [ ] **Step 6: Lint + type + commit**

Run: `poetry run ruff check src && poetry run mypy src/`
```bash
git add src/cryptrink/web/shell.py src/cryptrink/web/app.py src/cryptrink/web/screens src/cryptrink/web/tabs
git commit -m "feat(web): assemble workspace shell (header, sidebar, rail, terminal, overlay)"
```

---

### Task 7: Wire global terminal + screen switching behaviour

**Files:**
- Modify: `src/cryptrink/web/shell.py`
- Test: manual + `tests/unit/test_shell.py` for any new pure helper

- [ ] **Step 1:** Implement `_render_terminal_component()` handler that reads `state.get_log_events(active_filter)` and returns `terminal_html(...)`; wire it to the terminal `gr.Timer.tick` and to each filter chip `.click` (chip sets the `gr.State` filter then re-renders; active chip styling via returned HTML/classes). Wire `clear` → `state.clear_log_events()` then re-render.
- [ ] **Step 2:** Implement the screen-switch handler `_select_screen(key)` returning visibility updates for all screens + the new screen-header HTML (`screen_header_html(key, get_last_synced(key))`) + setting `screen` state; log `state.log_event("sys","info",f"view: {key}")` is optional (skip to avoid noise).
- [ ] **Step 3:** Caret toggle for the terminal: a `gr.State("open")` + button that toggles a CSS class on the terminal body (via `js=` or by returning updated HTML with a collapsed class).
- [ ] **Step 4: Manual check** — launch, click between screens, click filter chips, push a log via an action and watch it appear. Confirm autoscroll via CSS (`scroll-behavior` + JS in `theme.fonts_head()` or a small `Blocks(js=...)` that pins `#ck-term` scrollTop).
- [ ] **Step 5: Commit**

```bash
git add src/cryptrink/web/shell.py tests/unit/test_shell.py
git commit -m "feat(web): wire global terminal filtering and screen switching"
```

---

### Task 8: Safety model — mode banner + confirm overlay

**Files:**
- Modify: `src/cryptrink/web/shell.py`
- Test: manual (mode is pinned indirectly; add a pure-helper test if a new helper appears)

- [ ] **Step 1:** "Go live →" button `.click` → open overlay with the verbatim "Switch to LIVE trading?" copy, set pending=`"go_live"`. Confirm `.click` → `state.set_mode("live")`, `state.log_event("sys","warn","mode: switched to LIVE — real orders enabled")`, update banner HTML (`banner_html("live")`), update the banner toggle button label to "Switch to paper", close overlay, refresh rail. Cancel → close overlay only.
- [ ] **Step 2:** When mode is live, the banner toggle is "Switch to paper" and `.click` → immediate `state.set_mode("paper")` + `banner_html("paper")` + log + rail refresh (no confirm).
- [ ] **Step 3:** Expose hooks so the Live screen Start button (Task 10) can open the overlay with pending=`"start_live_loop"` and bind the actual start action through Confirm. Use a single Confirm handler that dispatches on the pending `gr.State`.
- [ ] **Step 4: Manual check** — paper→live shows the modal; confirming flips the banner to pulsing red and logs it; live→paper is immediate.
- [ ] **Step 5: Commit**

```bash
git add src/cryptrink/web/shell.py
git commit -m "feat(web): paper/live mode banner with blocking confirm dialog"
```

---

### Task 9: Rebuild the Portfolio screen

**Files:**
- Modify: `src/cryptrink/web/tabs/portfolio.py`
- Test: `tests/unit/test_web_app.py` smoke; manual visual

Preserve handler functions + engine calls; restyle layout to the 300px-left / fluid-right design; replace the matplotlib equity figure with `charts.equity_curve_figure`.

- [ ] **Step 1:** Refactor `render()` to build (inside the current context, no `gr.Tab`):
  - Left `gr.Column(elem_classes=["ck-col-300"])`: Portfolios picker (the saved-portfolio `gr.Dropdown` restyled as a list, + "New") and an Allocations card; Run-backtest (primary) + Edit-YAML buttons; the YAML `gr.Code` editor lives behind the Edit-YAML toggle (a `gr.Group(visible=False)`).
  - Right `gr.Column`: 4-up metrics `gr.HTML`/`gr.Markdown` row (Total return, Sharpe, Max drawdown, Win rate), the equity `gr.Plot(elem_classes=["ck-card"])`, and the per-allocation breakdown `gr.Dataframe`.
- [ ] **Step 2:** Change `run_portfolio_backtest` to yield a Plotly figure (via `charts.equity_curve_figure(result.equity_curve, theme_name=...)`) instead of the matplotlib Figure for the equity output. Keep the rest of the streamed tuple shape; update the metrics output to feed the 4-up HTML (build a small `_metrics_html(result.metrics)` helper). Map breakdown into the existing `gr.Dataframe`.
- [ ] **Step 3:** Route the portfolio terminal lines through `state.log_event("portfolio", level, msg)` (in addition to / instead of the old `_LOG`). Remove the on-screen per-tab terminal markdown from the panel (the docked global terminal shows it).
- [ ] **Step 4: Smoke + manual** — `poetry run pytest tests/unit/test_web_app.py -q` passes; launch, run a portfolio backtest against a stored dataset (or with empty DB see graceful empty states), confirm the equity chart renders with crosshair hover and metrics populate.
- [ ] **Step 5: Lint + type + commit**

```bash
git add src/cryptrink/web/tabs/portfolio.py
git commit -m "feat(web): rebuild Portfolio screen with Plotly equity and metrics cards"
```

---

### Task 10: Rebuild the Live screen (+ candlestick + safety start)

**Files:**
- Modify: `src/cryptrink/web/tabs/live.py`
- Test: `tests/unit/test_web_app.py` smoke + `tests/unit/test_live_loop.py`/`test_live_setup.py` must stay green; manual visual

Preserve `start_loop`/`stop_loop`/`refresh_status`/`test_connection`/`preflight_order`/`test_discord` and the creds-conditional branches. Add a candlestick fed by stored OHLCV.

- [ ] **Step 1:** Refactor `render()` to the new layout (no `gr.Tab`): a mode callout `gr.HTML` mirroring the banner; left `gr.Column`: candlestick `gr.Plot` + a Loop-activity stats row (`gr.HTML` built from `LiveLoopState`); right `gr.Column(elem_classes=["ck-col-320"])`: Loop configuration card (Strategy, Dataset, Interval, Paper balance; `gr.Accordion("Advanced · risk & notifications", open=False)` holding the Discord heartbeat inputs) with Start/Stop + Test-connection / Pre-flight, and a Loop-status card (`gr.HTML` of Symbol/Strategy/Interval/Mode/Engine ID/Last signal).
- [ ] **Step 2:** Add `_load_candles(dataset_value) -> list[dict]` reading stored OHLCV (`OHLCVRepository(session_factory).get(symbol, timeframe, limit=...)` → list of `{time, open, high, low, close}`), and feed `charts.candlestick_figure(...)`. Wire it to `demo.load`/screen-focus and to dataset change (not a manual button).
- [ ] **Step 3:** Start button styling/behaviour: teal in paper, red in live; in live mode the click opens the confirm overlay (pending=`"start_live_loop"`) per Task 8, and only Confirm calls `start_loop(...)`; paper start calls it immediately. Stop button shows when running. Route loop log lines through `state.log_event("live", level, msg)`.
- [ ] **Step 4:** Keep `mode_input`/creds-conditional sections; the global `mode` (state.get_mode) drives the callout + Start colour. (The `gr.Radio` mode input can be kept hidden/secondary or replaced by reading `state.get_mode()`; preserve `LiveMode` usage in `start_loop`.)
- [ ] **Step 5: Tests + manual** — `poetry run pytest tests/unit/test_web_app.py tests/unit/test_live_loop.py tests/unit/test_live_setup.py -q` green; launch, confirm candlestick renders for a stored dataset, paper start works immediately, (with no creds) live is unavailable, status card populates.
- [ ] **Step 6: Lint + type + commit**

```bash
git add src/cryptrink/web/tabs/live.py
git commit -m "feat(web): rebuild Live screen with candlestick chart and safe start flow"
```

---

## Phase 3 — Dashboard + Settings

### Task 11: Dashboard screen + data builders

**Files:**
- Modify: `src/cryptrink/web/screens/dashboard.py`
- Modify: `src/cryptrink/web/tabs/status.py` (keep `refresh()` + `_engines_dataframe`/`_orders_dataframe`/`_positions_dataframe` importable)
- Test: `tests/unit/test_dashboard_screen.py`

- [ ] **Step 1: Write failing tests** for the pure pieces (e.g. a `dashboard_metrics_html(...)` helper given engines/positions/orders DataFrames returns HTML containing the metric labels; and that `dashboard.render` is callable). Example:

```python
from cryptrink.web.screens import dashboard

def test_metrics_html_has_labels():
    html = dashboard.metrics_html(account_equity="€0.00", open_pnl="€0.00",
                                  realised_30d="€0.00", active_engines="0")
    for label in ("Account equity", "Open P&L", "Realised", "Active engines"):
        assert label in html
```

- [ ] **Step 2:** Run, verify fail.
- [ ] **Step 3:** Implement `dashboard.py`: `render()` builds 4-up metrics `gr.HTML` + Open-positions `gr.Dataframe` + Recent-orders `gr.Dataframe`. An async `refresh()` reuses `status.refresh()` (returns engines/orders/positions DataFrames), derives the 4 metric values, and returns `(metrics_html, positions_df, orders_df)`. Wire to `demo.load` + screen focus + a `gr.Timer`. Pure `metrics_html(...)` builds the cards.
- [ ] **Step 4:** Run tests, verify pass; smoke `test_web_app.py`.
- [ ] **Step 5: Lint + type + commit**

```bash
git add src/cryptrink/web/screens/dashboard.py src/cryptrink/web/tabs/status.py tests/unit/test_dashboard_screen.py
git commit -m "feat(web): add Dashboard monitoring screen"
```

---

### Task 12: Settings screen

**Files:**
- Modify: `src/cryptrink/web/screens/settings.py`
- Test: `tests/unit/test_settings_screen.py`

- [ ] **Step 1: Write failing tests** for `mask_secret(value) -> str` (e.g. `"abcd1234ef" -> "••••••34ef"`, empty -> "not set") and `connection_rows(settings) -> list[tuple[str,str,str]]`, and that `settings.render` is callable.
- [ ] **Step 2:** Run, verify fail.
- [ ] **Step 3:** Implement `settings.py`: `render()` builds a Revolut X connection card (API key masked via `mask_secret`, private-key status, base URL, webhook), a Risk-defaults card (from `runtime.settings.risk`), and an Appearance card with the 3 theme swatches (buttons wired with `theme.theme_switch_js`). All read-only display. Add `mask_secret`, `connection_rows`, `risk_rows` pure helpers.
- [ ] **Step 4:** Run tests, verify pass; smoke `test_web_app.py`.
- [ ] **Step 5: Lint + type + commit**

```bash
git add src/cryptrink/web/screens/settings.py tests/unit/test_settings_screen.py
git commit -m "feat(web): add Settings screen (connection, risk defaults, appearance)"
```

---

## Phase 4 — Restyle Backtest / Suggest / Data

### Task 13: Restyle Backtest, Suggest, Data into the shell

**Files:**
- Modify: `src/cryptrink/web/tabs/backtest.py`, `tabs/suggest.py`, `tabs/data.py`
- Test: `tests/unit/test_backtest_tab.py`, `tests/unit/test_data_tab.py` must stay green; smoke

Do these one module at a time, committing each. **Preserve every pinned symbol/string** (spec §3).

- [ ] **Step 1 (Backtest):** Refactor `render()` to the config-card-left / metrics+chart-right layout; move Strategy parameters + Auto-tuning into `gr.Accordion(open=False)`s (already accordions — restyle). Replace the matplotlib equity/price `gr.Plot`s with `charts.equity_curve_figure` / `charts.candlestick_figure`, adapting `run_backtest`'s yielded figures. **Keep** `_PLOT_MAX_POINTS`, `_subsample`, `_format_date_axis`, `autofill_dates`, `_emit`, `_render_terminal`, `_manual_panels`, `_tuning_panels` and the `backtest_tuning` import coupling. Route logs to `state.log_event("backtest", ...)` additionally. Run `poetry run pytest tests/unit/test_backtest_tab.py -q` → green. Commit.
- [ ] **Step 2 (Suggest):** Refactor `render()` to a single input row + a result card. Replace the raw `gr.JSON` with a `gr.HTML` verdict card built from `run_suggest`'s dict (big BUY/SELL/HOLD, strength badge, key/value grid) — keep `run_suggest` returning its dict unchanged; add a pure `suggestion_card_html(result: dict) -> str`. Remove the manual "Refresh datasets" button (wire to focus). Commit.
- [ ] **Step 3 (Data):** Refactor `render()` to a backfill row + a Stored-datasets `gr.Dataframe` (auto-loaded from `list_datasets()` on focus/load) + an `gr.Accordion("Advanced", open=False)` holding wipe/reset/checkpoint/diagnostics. **Keep** `_LOG`, `_LOG_MAX_LINES`, `_emit`, `_render_terminal`, `clear_log`, `_format_db_size`, all async handlers and their exact strings; mirror `_emit` into `state.log_event("data", "info", msg)` so logs reach the global terminal. Keep the `js=` confirm on wipe/reset (or route through the shared overlay — keeping `js=` is lower-risk). Run `poetry run pytest tests/unit/test_data_tab.py -q` → green. Commit.

```bash
# after each sub-step, e.g.:
git add src/cryptrink/web/tabs/backtest.py
git commit -m "feat(web): restyle Backtest screen into workspace shell"
```

---

## Phase 5 — Automation, Verify, Polish, PR

### Task 14: Startup sync + focus-refresh automation

**Files:**
- Modify: `src/cryptrink/web/shell.py` (+ small hooks in screens)

- [ ] **Step 1:** Implement an async `startup_sync()` wired to `demo.load`: refresh symbol vocabulary (best-effort; on failure log a warn), `mark_synced("symbols")`; list datasets, `mark_synced("datasets")`; probe connection status (cheap; reuse existing live `test_connection` plumbing only if creds present, else log "paper sandbox"); `state.log_event(...)` one line per step (mirror the prototype's first terminal lines). Populate the rail + header "synced" stamp.
- [ ] **Step 2:** Wire each screen's read-only refresh to its nav-button `.click` (focus) and to `demo.load`, and the rail/terminal/dashboard/live-status to `gr.Timer`. Remove remaining user-facing manual read-refresh buttons (keep the handler functions; they're test-pinned in Data).
- [ ] **Step 3: Manual check** — boot the app; the terminal shows startup-sync lines; opening a screen refreshes its data; "synced" stamps appear; no manual read-refresh buttons remain.
- [ ] **Step 4: Commit**

```bash
git add src/cryptrink/web/shell.py src/cryptrink/web/tabs src/cryptrink/web/screens
git commit -m "feat(web): startup sync, focus-refresh, and last-synced stamps"
```

---

### Task 15: Full verification + visual screenshots

**Files:** none (verification)

- [ ] **Step 1:** `poetry run pytest -q` → expect **795 passed, 13 skipped** (same as baseline).
- [ ] **Step 2:** `poetry run ruff check src tests && poetry run ruff format --check src tests` → clean.
- [ ] **Step 3:** `poetry run mypy src/` → clean.
- [ ] **Step 4:** Launch `poetry run python app.py`; using the Claude_Preview / preview MCP (or a browser), screenshot: Portfolio, Live (paper + the live confirm modal), Dashboard, Backtest, Suggest, Data, Settings; the theme switch (Carbon→Slate→Daylight); the docked terminal with filters; the equity crosshair + candlestick hover. Fix any CSS/layout regressions found.
- [ ] **Step 5:** Commit any fixes.

```bash
git add -A
git commit -m "fix(web): visual polish from screenshot review"
```

---

### Task 16: Slate + Daylight polish + chart repaint (optional within scope)

**Files:** `src/cryptrink/web/theme.py`, `src/cryptrink/web/charts.py`, `shell.py`

- [ ] **Step 1:** Verify Slate/Daylight render correctly (already wired client-side); fix any token contrast issues.
- [ ] **Step 2:** Make charts repaint on theme switch: on theme change, re-render the visible `gr.Plot`(s) server-side with the new `theme_name` (a `gr.State("theme")` updated by the swatch buttons drives a re-render of the active screen's charts). If time-boxed, document as a follow-up instead.
- [ ] **Step 3:** Commit.

```bash
git add src/cryptrink/web/theme.py src/cryptrink/web/charts.py src/cryptrink/web/shell.py
git commit -m "feat(web): polish Slate/Daylight themes and chart repaint on switch"
```

---

### Task 17: Open the PR

- [ ] **Step 1:** `git push -u origin claude/sweet-lamarr-0c23d1`.
- [ ] **Step 2:** Open a PR against `main` with a summary (what changed, screenshots, "all 795 tests green", scope notes), using the project's PR conventions. Run `superpowers:requesting-code-review` before/with the PR.

---

## Self-Review

**Spec coverage:** shell (T5–T8,T14) ✓; Portfolio (T9) ✓; Live (T10) ✓; Dashboard (T11) ✓; Settings (T12) ✓; Backtest/Suggest/Data (T13) ✓; charts/plotly (T1,T4,T9,T10,T13) ✓; themes (T2,T16) ✓; state/log buffer/mode/snapshots (T3) ✓; safety model (T8,T10) ✓; global terminal (T5,T7,T13) ✓; automation (T14) ✓; guardrails verified by re-running pinned tests in T3,T9,T10,T13,T15 ✓; PR (T17) ✓.

**Placeholder scan:** charts `_base_layout` references a non-existent `colors.dim` — flagged inline in T4 Step 3 to use `colors.faint`. No other TODO/TBD.

**Type consistency:** `state.log_event(source, level, message)` / `LogEvent(time, source, level, message)` / `get_log_events(source_filter)` consistent across T3,T5,T7,T9,T10,T13,T14. `charts.equity_curve_figure(points, theme_name)` / `candlestick_figure(candles, theme_name)` consistent across T4,T9,T10,T13. `theme.THEMES`/`build_css`/`fonts_head`/`theme_switch_js`/`DEFAULT_THEME` consistent across T2,T4,T6,T12,T16. `shell.NAV_GROUPS`/`SCREEN_META`/`terminal_html`/`banner_html`/`build_workspace` consistent across T5,T6,T7,T8.
