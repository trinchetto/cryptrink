"""Shared HTML builders for the workspace screens.

Small, pure string helpers (metric cards, key/value rows, stat cells, euro
formatting) used across Portfolio / Dashboard / Live / Settings / Suggest so the
markup + CSS classes live in one place. No gradio import — pure functions.
"""

from __future__ import annotations

import html

# Maps a semantic tone to the value's colour class. ``ok`` is an alias for ``pos``
# (used by Settings); ``dim`` / unknown tones render with no colour class.
TONE_CLASS = {"pos": "ck-pos", "neg": "ck-neg", "ok": "ck-pos", "dim": ""}


def euro(value: float, signed: bool = False) -> str:
    """Format a number as euros (e.g. ``€1,234.00``); ``signed`` adds +/- for deltas."""
    sign = "+" if (signed and value >= 0) else ("-" if (signed and value < 0) else "")
    return f"{sign}€{abs(value):,.2f}"


def metric_card(label: str, value: str, sub: str = "", tone: str = "") -> str:
    """Render a metric card (label, large mono value, sub-label). ``tone`` colours value."""
    value_cls = f"ck-metric-value {TONE_CLASS.get(tone, '')}".strip()
    return (
        '<div class="ck-metric">'
        f'<div class="ck-metric-label">{html.escape(label)}</div>'
        f'<div class="{value_cls}">{html.escape(value)}</div>'
        f'<div class="ck-metric-sub">{html.escape(sub)}</div></div>'
    )


def kv_row(label: str, value: str, tone: str = "") -> str:
    """Render a label/value row (faint label, mono value). ``tone`` colours value."""
    value_cls = f"ck-mono {TONE_CLASS.get(tone, '')}".strip()
    return (
        f'<div class="ck-kv-row"><span style="color:var(--faint)">{html.escape(label)}</span>'
        f'<span class="{value_cls}">{html.escape(value)}</span></div>'
    )


def stat_cell(label: str, value: str) -> str:
    """Render a compact stat cell (label + mono value) for activity rows."""
    return (
        f'<div><div class="ck-metric-label">{html.escape(label)}</div>'
        f'<div class="ck-stat-value">{html.escape(value)}</div></div>'
    )
