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

if TYPE_CHECKING:
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
