"""Plotly figure builders for the web UI (interactive equity + candlestick charts).

These return :class:`plotly.graph_objects.Figure` objects fed to ``gr.Plot``. Plotly's
``hovermode="x unified"`` plus axis spike lines reproduce the prototype's crosshair +
tooltip without custom canvas JS. Colours are pulled from a theme's CSS-variable token
set so a future theme switch can repaint the charts by re-rendering with a new
``theme_name``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import plotly.graph_objects as go  # type: ignore[import-untyped]  # plotly ships no stubs

from cryptrink.web import theme

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


@dataclass(frozen=True)
class ThemeColors:
    """The handful of theme tokens the charts need, resolved to hex strings."""

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
        """Build colours from a named theme, falling back to the default."""
        tokens = theme.THEMES.get(name, theme.THEMES[theme.DEFAULT_THEME])
        return cls(
            accent=tokens["--accent"],
            pos=tokens["--pos"],
            neg=tokens["--neg"],
            border=tokens["--border"],
            faint=tokens["--faint"],
            surface=tokens["--surface"],
            text=tokens["--text"],
            bg=tokens["--bg"],
        )


def _base_layout(colors: ThemeColors) -> dict[str, object]:
    """Shared transparent layout with a crosshair-style x spike and faint gridlines."""
    return {
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
    theme_name: str = theme.DEFAULT_THEME,
) -> go.Figure:
    """Return an equity-curve line + area figure with a crosshair tooltip.

    Args:
        points: ``(timestamp, equity)`` samples in chronological order.
        theme_name: Theme whose colours the figure uses.
    """
    colors = ThemeColors.for_theme(theme_name)
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
    theme_name: str = theme.DEFAULT_THEME,
) -> go.Figure:
    """Return an OHLC candlestick figure (green up / red down) with a crosshair.

    Args:
        candles: dicts with ``time``, ``open``, ``high``, ``low``, ``close`` keys.
        theme_name: Theme whose colours the figure uses.
    """
    colors = ThemeColors.for_theme(theme_name)
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
