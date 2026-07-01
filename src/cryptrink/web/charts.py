"""Plotly figure builders for the web UI (interactive equity + candlestick charts).

These return :class:`plotly.graph_objects.Figure` objects fed to ``gr.Plot``. Plotly's
``hovermode="x unified"`` plus axis spike lines reproduce the prototype's crosshair +
tooltip without custom canvas JS. Colours are the fixed Carbon theme tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import plotly.graph_objects as go  # type: ignore[import-untyped]  # plotly ships no stubs

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


@dataclass(frozen=True)
class ThemeColors:
    """The handful of Carbon-theme tokens the charts need, resolved to hex strings."""

    accent: str
    pos: str
    neg: str
    border: str
    faint: str
    surface: str
    text: str
    bg: str


# Fixed plot height (px). Charts live in bounded, internally-scrolling columns, so a
# fixed height (rather than autosize) both looks right and prevents the Plotly
# ResizeObserver runaway described in ``_base_layout``.
CHART_HEIGHT_PX = 320


# The fixed Carbon palette (mirrors the CSS custom properties on ``#ck-root``).
CARBON_COLORS = ThemeColors(
    accent="#3fd9a8",
    pos="#3fd98a",
    neg="#f0616d",
    border="#2e343d",
    faint="#6b7280",
    surface="#1b1f25",
    text="#e7e9ec",
    bg="#14171c",
)


def _base_layout(colors: ThemeColors) -> dict[str, object]:
    """Shared transparent layout with a crosshair-style x spike and faint gridlines."""
    return {
        # A FIXED pixel height with autosize off is load-bearing, not cosmetic. A
        # responsive Plotly plot (autosize=True, the default) measures its container
        # every frame; inside our flex/100vh shell the container height is derived
        # from content, so plot->container->plot forms a ResizeObserver feedback loop
        # that grows the page without bound and pins the main thread. This only fires
        # once the plot has data (so it was invisible locally, fatal on the deployed
        # Space). Pinning the height breaks the loop. Callers may override ``height``.
        "height": CHART_HEIGHT_PX,
        "autosize": False,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "margin": {"l": 8, "r": 8, "t": 10, "b": 24},
        "font": {
            "color": colors.faint,
            "family": "IBM Plex Mono, monospace",
            "size": 11,
        },
        "hovermode": "x unified",
        "showlegend": False,
        "xaxis": {
            "showgrid": False,
            "showspikes": True,
            "spikethickness": 1,
            "spikedash": "dot",
            "spikecolor": colors.faint,
            "spikemode": "across",
            "color": colors.faint,
        },
        "yaxis": {
            "gridcolor": colors.border,
            "nticks": 4,
            "color": colors.faint,
        },
    }


def equity_curve_figure(
    points: list[tuple[datetime, Decimal]],
) -> go.Figure:
    """Return an equity-curve line + area figure with a crosshair tooltip.

    Args:
        points: ``(timestamp, equity)`` samples in chronological order.
    """
    colors = CARBON_COLORS
    fig = go.Figure(layout=_base_layout(colors))
    if not points:
        return fig
    xs = [point[0] for point in points]
    ys = [float(point[1]) for point in points]
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            line={"color": colors.accent, "width": 1.8, "shape": "spline"},
            fill="tozeroy",
            fillcolor=_alpha(colors.accent, 0.18),
            hovertemplate="€%{y:,.0f}<extra></extra>",
        )
    )
    low, high = min(ys), max(ys)
    pad = (high - low) * 0.08 or 1.0
    fig.update_yaxes(range=[low - pad, high + pad])
    return fig


def candlestick_figure(
    candles: list[dict[str, object]],
) -> go.Figure:
    """Return an OHLC candlestick figure (green up / red down) with a crosshair.

    Args:
        candles: dicts with ``time``, ``open``, ``high``, ``low``, ``close`` keys.
    """
    colors = CARBON_COLORS
    fig = go.Figure(layout=_base_layout(colors))
    if not candles:
        fig.update_layout(xaxis_rangeslider_visible=False)
        return fig
    fig.add_trace(
        go.Candlestick(
            x=[candle["time"] for candle in candles],
            open=[candle["open"] for candle in candles],
            high=[candle["high"] for candle in candles],
            low=[candle["low"] for candle in candles],
            close=[candle["close"] for candle in candles],
            increasing={"line": {"color": colors.pos}, "fillcolor": colors.pos},
            decreasing={"line": {"color": colors.neg}, "fillcolor": colors.neg},
        )
    )
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


def _alpha(hex_color: str, alpha: float) -> str:
    """Convert ``#rrggbb`` to an ``rgba(...)`` string with the given alpha."""
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha})"
