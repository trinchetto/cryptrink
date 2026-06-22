"""Workspace shell: nav model, persistent-chrome HTML renderers, and (later) the
Gradio assembly that wires the header, sidebar, status rail, docked terminal, and
confirm overlay around the swappable screen panels.

This module is split so the pure pieces (nav model + HTML string builders) are unit
testable without importing gradio. ``build_workspace`` (added in the shell-assembly
task) is the only part that touches gradio.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass
from typing import TYPE_CHECKING

import gradio as gr

from cryptrink.web import state as web_state
from cryptrink.web import theme
from cryptrink.web.live_loop import get_active_loop
from cryptrink.web.live_setup import has_revolutx_credentials

if TYPE_CHECKING:
    from collections.abc import Callable

    from cryptrink.web.state import LogEvent


# ---------------------------------------------------------------------------
# Navigation model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NavItem:
    """One sidebar entry. ``key`` is the screen id; ``tag`` is the 2-letter chip."""

    key: str
    tag: str
    label: str


@dataclass(frozen=True)
class NavGroup:
    """A labelled workflow group of sidebar items."""

    label: str
    items: tuple[NavItem, ...]


NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup(
        "Research",
        (NavItem("backtest", "BT", "Backtest"), NavItem("portfolio", "PF", "Portfolio")),
    ),
    NavGroup(
        "Trade",
        (NavItem("suggest", "SG", "Suggest"), NavItem("live", "LV", "Live")),
    ),
    NavGroup("Monitor", (NavItem("dashboard", "DB", "Dashboard"),)),
    NavGroup(
        "System",
        (NavItem("data", "DT", "Data"), NavItem("settings", "ST", "Settings")),
    ),
)

# Flattened screen order (sidebar top-to-bottom). Drives visibility-toggle lists.
SCREEN_ORDER: list[str] = [item.key for group in NAV_GROUPS for item in group.items]

# Default screen shown on boot (matches the prototype).
DEFAULT_SCREEN = "portfolio"

# title + subtitle for the sticky screen header, verbatim from the prototype.
SCREEN_META: dict[str, tuple[str, str]] = {
    "dashboard": (
        "Dashboard",
        "Engine state, open positions, and order history across paper and live sessions.",
    ),
    "backtest": (
        "Backtest",
        "Replay a single strategy over a stored dataset. Tune by hand or sweep with the optimizer.",
    ),
    "portfolio": (
        "Portfolio",
        "Build a multi-pair portfolio sharing one cash pool, then backtest the whole "
        "allocation in one run.",
    ),
    "suggest": (
        "Suggest",
        "Generate a one-shot trade suggestion from the latest stored candle. No order is placed.",
    ),
    "live": (
        "Live trading",
        "Run a strategy on a periodic interval against Revolut X. Paper replays locally; "
        "live places real orders.",
    ),
    "data": (
        "Data",
        "Historical OHLCV the research and trading engines read from. Backfilled from "
        "Revolut X and auto-synced on startup.",
    ),
    "settings": (
        "Settings",
        "Connection, default risk limits, and appearance. The knobs that rarely change "
        "live here, out of the workflow.",
    ),
}


# ---------------------------------------------------------------------------
# Pure HTML renderers (consumed by gr.HTML components)
# ---------------------------------------------------------------------------
_SRC_CLASS = {
    "sys": "ck-src-sys",
    "data": "ck-src-data",
    "backtest": "ck-src-bt",
    "portfolio": "ck-src-pf",
    "live": "ck-src-live",
}
_LVL_CLASS = {
    "ok": "ck-lvl-ok",
    "info": "ck-lvl-info",
    "warn": "ck-lvl-warn",
    "err": "ck-lvl-err",
}


def _esc(value: object) -> str:
    return _html.escape(str(value))


def terminal_html(events: list[LogEvent]) -> str:
    """Render the docked terminal body from buffered log events.

    Each line is ``time · source · message`` (monospace), the source tag coloured per
    source and the message coloured per level. A blinking cursor row always trails.
    """
    lines = "".join(
        '<div class="ck-term-line">'
        f'<span class="ck-term-tm">{_esc(event.time)}</span>'
        f'<span class="ck-term-src {_SRC_CLASS.get(event.source, "")}">{_esc(event.source)}</span>'
        f'<span class="ck-term-msg {_LVL_CLASS.get(event.level, "")}">{_esc(event.message)}</span>'
        "</div>"
        for event in events
    )
    cursor = '<div class="ck-term-cursor">&rsaquo;<span class="ck-blink-block"></span></div>'
    return f'<div class="ck-term-body" id="ck-term">{lines}{cursor}</div>'


def banner_html(mode: str) -> str:
    """Render the full-width paper/live mode banner."""
    if mode == "live":
        return (
            '<div class="ck-banner ck-banner-live">'
            '<span class="ck-dot ck-pulse"></span>'
            "<b>LIVE TRADING</b>"
            '<span class="ck-banner-sub">Real orders are placed on Revolut X with '
            "account funds.</span></div>"
        )
    return (
        '<div class="ck-banner ck-banner-paper">'
        '<span class="ck-dot"></span>'
        "<b>PAPER TRADING</b>"
        '<span class="ck-banner-sub">Simulated against stored data — no real orders.</span>'
        "</div>"
    )


def modal_body_html(title: str, body: str) -> str:
    """Render the confirm-dialog inner content (warning icon + title + body)."""
    return (
        '<div style="display:flex;align-items:center;gap:11px;margin-bottom:13px">'
        '<span class="ck-modal-icon">!</span>'
        f'<span class="ck-modal-title">{_esc(title)}</span></div>'
        f'<div class="ck-modal-body">{_esc(body)}</div>'
    )


def screen_header_html(screen: str, synced: str | None) -> str:
    """Render the sticky per-screen header (title + subtitle + auto-synced stamp)."""
    title, subtitle = SCREEN_META.get(screen, (screen.title(), ""))
    synced_html = (
        f'<div class="ck-screen-synced"><span class="ck-dot ck-dot-pos"></span>'
        f"auto-synced {_esc(synced)}</div>"
        if synced
        else ""
    )
    return (
        '<div class="ck-screen-header">'
        f'<div><div class="ck-screen-title">{_esc(title)}</div>'
        f'<div class="ck-screen-sub">{_esc(subtitle)}</div></div>'
        '<div style="flex:1"></div>'
        f"{synced_html}</div>"
    )


def header_html(balance: str, synced: str | None, connected: bool) -> str:
    """Render the persistent header (logo, exchange pill, balance, synced stamp)."""
    conn_dot = "ck-dot-pos" if connected else "ck-dot-faint"
    conn_label = "connected" if connected else "offline"
    conn_color = "var(--pos)" if connected else "var(--faint)"
    synced_txt = _esc(synced) if synced else "—"
    return (
        '<div class="ck-header-left" style="display:flex;align-items:center;gap:18px;flex:1">'
        '<div style="display:flex;align-items:center;gap:9px">'
        '<span class="ck-logo-sq">c</span>'
        '<span class="ck-wordmark">cryptrink</span>'
        '<span class="ck-pill">Revolut X</span></div>'
        f'<div class="ck-conn-chip"><span class="ck-dot {conn_dot}"></span>'
        f'<span style="color:var(--dim)">Exchange</span>'
        f'<span style="color:{conn_color};font-weight:600">{conn_label}</span></div>'
        '<div style="flex:1"></div>'
        '<div style="text-align:right;line-height:1.25">'
        '<div class="ck-balance-l">Account balance</div>'
        f'<div class="ck-balance-v">{_esc(balance)}</div></div>'
        '<div class="ck-synced"><span class="ck-balance-l">Synced</span>'
        '<span class="ck-dot ck-dot-pos" style="animation:ck-blink 2s infinite"></span>'
        f'<span class="ck-mono">{synced_txt}</span></div>'
    )


def _rail_section(label: str, body: str) -> str:
    return f'<div><div class="ck-rail-label">{_esc(label)}</div>{body}</div>'


def rail_html(
    *,
    running: bool,
    loop_sub: str,
    today_rows: list[tuple[str, str, str]],
    positions: list[tuple[str, str, str]],
    watchlist: list[tuple[str, str, str]],
) -> str:
    """Render the right status rail (live loop, today's P&L, positions, watchlist).

    ``today_rows``/``positions``/``watchlist`` are ``(label, value, css_class)`` rows;
    ``css_class`` is ``""`` | ``"ck-pos"`` | ``"ck-neg"`` to colour the value.
    """
    state_word = "Running" if running else "Idle"
    dot = "ck-dot-pos" if running else "ck-dot-faint"
    card_cls = "ck-rail-card ck-running" if running else "ck-rail-card"
    loop = (
        f'<div class="{card_cls}"><div style="display:flex;align-items:center;gap:8px">'
        f'<span class="ck-dot {dot}"></span><b>{state_word}</b></div>'
        f'<div style="color:var(--faint);font-size:11px;margin-top:4px">{_esc(loop_sub)}</div></div>'
    )

    def _rows(rows: list[tuple[str, str, str]]) -> str:
        return "".join(
            f'<div class="ck-rail-row"><span style="color:var(--faint)">{_esc(k)}</span>'
            f'<span class="ck-mono {cls}">{_esc(v)}</span></div>'
            for k, v, cls in rows
        )

    return (
        _rail_section("Live loop", loop)
        + _rail_section("Today", _rows(today_rows))
        + _rail_section("Positions", _rows(positions))
        + _rail_section("Watchlist", _rows(watchlist))
    )


# ---------------------------------------------------------------------------
# Gradio assembly
# ---------------------------------------------------------------------------
TERM_FILTERS = ("all", "sys", "data", "backtest", "live")


def _nav_classes(active: bool) -> list[str]:
    return ["ck-nav-item", "ck-nav-active"] if active else ["ck-nav-item"]


def _chip_classes(active: bool) -> list[str]:
    return ["ck-chip", "ck-chip-active"] if active else ["ck-chip"]


def _header_now() -> str:
    """Current header HTML from runtime state (connection + last-synced stamp)."""
    runtime = web_state.get_runtime()
    connected = has_revolutx_credentials(runtime.settings)
    return header_html("—", web_state.get_last_synced("datasets"), connected=connected)


def _rail_now() -> str:
    """Current status-rail HTML (live-loop state + mode)."""
    loop = get_active_loop()
    running = bool(loop is not None and loop.is_running)
    mode = web_state.get_mode()
    if running and loop is not None:
        snap = loop.snapshot()
        loop_sub = f"{mode} · {snap.symbol} · {snap.interval_seconds:.0f}s"
    else:
        loop_sub = "No active loop"
    return rail_html(
        running=running,
        loop_sub=loop_sub,
        today_rows=[("Mode", mode.upper(), ""), ("Unrealised P&L", "—", "")],
        positions=[("—", "", "")],
        watchlist=[("—", "", "")],
    )


async def startup_sync() -> tuple[str, str]:
    """Auto-sync on app load: probe connection, symbols, datasets; log each + stamp.

    Returns updated (header_html, rail_html). The docked terminal renders the logged
    lines on its own timer.
    """
    runtime = web_state.get_runtime()
    if has_revolutx_credentials(runtime.settings):
        web_state.log_event("sys", "ok", "revolutx: credentials present")
    else:
        web_state.log_event("sys", "info", "paper sandbox — no live exchange connection")
    web_state.mark_synced("connection")

    symbols = web_state.get_symbol_choices()
    web_state.log_event("sys", "info", f"symbol vocabulary: {len(symbols)} symbols")
    web_state.mark_synced("symbols")

    try:
        datasets = await web_state.list_datasets()
        web_state.log_event(
            "data", "ok", f"auto-sync: {len(datasets)} (symbol, timeframe) datasets loaded"
        )
    except Exception as exc:  # best-effort startup sync
        web_state.log_event("data", "warn", f"dataset sync failed: {exc}")
    web_state.mark_synced("datasets")

    return _header_now(), _rail_now()


def build_workspace(demo: gr.Blocks, screen_builders: dict[str, Callable[[], None]]) -> None:
    """Build the whole workspace inside an open ``gr.Blocks`` context.

    ``screen_builders`` maps a screen key (see :data:`SCREEN_ORDER`) to the function
    that renders that screen's panel. The shell mounts each inside a visibility-toggled
    group, wires the sidebar navigation, theme switch, and docked global terminal.
    """
    mode = web_state.get_mode()
    screen_state = gr.State(DEFAULT_SCREEN)
    term_filter = gr.State("all")

    with gr.Column(elem_id="ck-root", elem_classes=["ck-theme-carbon"]):
        # ---- header ----
        with gr.Row(elem_classes=["ck-header"]):
            header_left = gr.HTML(_header_now(), elem_id="ck-header-left")
            theme_btns = {
                name: gr.Button(glyph, elem_classes=["ck-theme-btn"], scale=0)
                for name, glyph in (("carbon", "◐"), ("slate", "◑"), ("daylight", "☀"))
            }
        for name, btn in theme_btns.items():
            btn.click(fn=None, js=theme.theme_switch_js(name))

        # ---- mode banner ----
        with gr.Row(elem_id="ck-banner-row"):
            banner = gr.HTML(banner_html(mode), elem_id="ck-banner")
            banner_btn = gr.Button(
                "Switch to paper" if mode == "live" else "Go live →",
                elem_classes=["ck-btn-secondary", "ck-banner-btn"],
                scale=0,
            )

        # ---- body: sidebar | main | rail ----
        nav_buttons: dict[str, gr.Button] = {}
        panels: dict[str, gr.Group] = {}
        with gr.Row(elem_classes=["ck-body"]):
            with gr.Column(elem_classes=["ck-sidebar"], scale=0):
                for group in NAV_GROUPS:
                    gr.HTML(f'<div class="ck-nav-group-label">{group.label}</div>')
                    for item in group.items:
                        nav_buttons[item.key] = gr.Button(
                            item.label,
                            elem_id=f"ck-nav-{item.key}",
                            elem_classes=_nav_classes(item.key == DEFAULT_SCREEN),
                        )
            with gr.Column(elem_classes=["ck-main"]):
                screen_header = gr.HTML(
                    screen_header_html(DEFAULT_SCREEN, None), elem_id="ck-screen-header"
                )
                for key in SCREEN_ORDER:
                    with gr.Group(
                        visible=(key == DEFAULT_SCREEN), elem_classes=["ck-screen-body"]
                    ) as panel:
                        screen_builders[key]()
                    panels[key] = panel
            with gr.Column(elem_classes=["ck-rail"], scale=0):
                rail = gr.HTML(_rail_now(), elem_id="ck-rail")

        # ---- docked terminal ----
        with gr.Column(elem_classes=["ck-term"]):
            with gr.Row(elem_classes=["ck-term-head"]):
                gr.HTML(
                    '<span class="ck-term-title">Terminal</span>'
                    '<span class="ck-dot ck-dot-pos" style="animation:ck-blink 1.4s infinite"></span>'
                    '<span class="ck-term-meta">streaming</span>'
                )
                chip_btns = {
                    name: gr.Button(name, elem_classes=_chip_classes(name == "all"), scale=0)
                    for name in TERM_FILTERS
                }
                clear_btn = gr.Button("clear", elem_classes=["ck-chip"], scale=0)
            term_body = gr.HTML(
                terminal_html(web_state.get_log_events("all")), elem_classes=["ck-term-shell"]
            )
            term_timer = gr.Timer(1.0)

        # ---- confirm dialog overlay (paper -> live) ----
        # Standard Gradio modal: a Group toggled with gr.update(visible=...). This modal
        # is exclusively the paper -> live confirm, so Confirm always means "go live".
        with (
            gr.Group(visible=False, elem_classes=["ck-modal"]) as modal,
            gr.Column(elem_classes=["ck-modal-card"]),
        ):
            gr.HTML(
                modal_body_html(
                    "Switch to LIVE trading?",
                    "Live mode places real orders on Revolut X using your account funds. "
                    "Every Start in this session will trade real money. Make sure you have "
                    "run a pre-flight check.",
                )
            )
            with gr.Row():
                modal_cancel = gr.Button("Cancel", elem_classes=["ck-btn-secondary"])
                modal_confirm = gr.Button("Enable LIVE mode", elem_classes=["ck-btn-live"])

    # ---- wiring: safety model (paper <-> live) ----
    # Open via gr.update(visible=True) (renders the card); close via a js display toggle
    # (gr.update(visible=False) does not close a shown Group). The banner js shows the
    # dialog in paper mode and force-hides it in live mode (where the click is immediate).
    banner_modal_js = (
        "() => { const b = document.querySelector('button.ck-banner-btn');"
        " const m = document.querySelector('.ck-modal'); if (!b || !m) return;"
        " if (b.textContent.indexOf('Go live') !== -1) m.classList.remove('ck-force-hidden');"
        " else m.classList.add('ck-force-hidden'); }"
    )
    hide_modal_js = (
        "() => { const m = document.querySelector('.ck-modal');"
        " if (m) m.classList.add('ck-force-hidden'); }"
    )

    def _on_banner_toggle() -> list[object]:
        # paper -> live opens the confirm dialog (js reveals it); live -> paper is immediate.
        if web_state.get_mode() == "paper":
            return [gr.update(visible=True), gr.update(), gr.update()]
        web_state.set_mode("paper")
        web_state.log_event("sys", "info", "mode: switched back to PAPER")
        return [gr.update(), banner_html("paper"), gr.update(value="Go live →")]

    banner_btn.click(
        fn=_on_banner_toggle,
        inputs=None,
        outputs=[modal, banner, banner_btn],
        js=banner_modal_js,
    )

    def _on_modal_confirm() -> list[object]:
        web_state.set_mode("live")
        web_state.log_event("sys", "warn", "mode: switched to LIVE — real orders enabled")
        return [banner_html("live"), gr.update(value="Switch to paper")]

    modal_confirm.click(
        fn=_on_modal_confirm, inputs=None, outputs=[banner, banner_btn], js=hide_modal_js
    )

    modal_cancel.click(fn=None, js=hide_modal_js)

    # ---- wiring: screen switching ----
    switch_outputs = (
        [panels[s] for s in SCREEN_ORDER]
        + [screen_header]
        + [nav_buttons[s] for s in SCREEN_ORDER]
        + [screen_state]
    )

    def _make_select(target: str) -> Callable[[], list[object]]:
        def _select() -> list[object]:
            panel_updates = [gr.update(visible=(s == target)) for s in SCREEN_ORDER]
            nav_updates = [gr.update(elem_classes=_nav_classes(s == target)) for s in SCREEN_ORDER]
            header = screen_header_html(target, web_state.get_last_synced(target))
            return [*panel_updates, header, *nav_updates, target]

        return _select

    for key, btn in nav_buttons.items():
        btn.click(fn=_make_select(key), inputs=None, outputs=switch_outputs)

    # ---- wiring: terminal ----
    def _render_term(active_filter: str) -> str:
        return terminal_html(web_state.get_log_events(active_filter))

    term_timer.tick(fn=_render_term, inputs=[term_filter], outputs=[term_body])

    chip_outputs = [term_body, term_filter, *chip_btns.values()]

    def _make_filter(selected: str) -> Callable[[], list[object]]:
        def _set() -> list[object]:
            chip_updates = [gr.update(elem_classes=_chip_classes(n == selected)) for n in TERM_FILTERS]
            return [terminal_html(web_state.get_log_events(selected)), selected, *chip_updates]

        return _set

    for name, chip in chip_btns.items():
        chip.click(fn=_make_filter(name), inputs=None, outputs=chip_outputs)

    def _clear() -> str:
        web_state.clear_log_events()
        return terminal_html([])

    clear_btn.click(fn=_clear, inputs=None, outputs=[term_body])

    # ---- wiring: automation (startup sync + live chrome refresh) ----
    demo.load(fn=startup_sync, inputs=None, outputs=[header_left, rail])
    chrome_timer = gr.Timer(4.0)
    chrome_timer.tick(
        fn=lambda: (_header_now(), _rail_now()), inputs=None, outputs=[header_left, rail]
    )
