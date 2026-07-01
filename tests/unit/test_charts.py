"""Tests for the Plotly figure builders used by the web UI charts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import plotly.graph_objects as go

from cryptrink.web import charts


def _equity_points() -> list[tuple[datetime, Decimal]]:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return [(base.replace(day=1 + i), Decimal(str(10000 + i * 100))) for i in range(5)]


def _candles() -> list[dict[str, object]]:
    base = datetime(2026, 6, 20, tzinfo=UTC)
    return [
        {
            "time": base.replace(hour=i),
            "open": 100.0 + i,
            "high": 102.0 + i,
            "low": 99.0 + i,
            "close": 101.0 + i,
        }
        for i in range(6)
    ]


class TestThemeColors:
    def test_carbon_accent(self):
        assert charts.CARBON_COLORS.accent == "#3fd9a8"


class TestFixedHeightPreventsRunaway:
    """Every figure must pin a fixed height with autosize OFF.

    A responsive Plotly plot (autosize=True) measures its container every frame and,
    inside the flex/fill web shell, forms a ResizeObserver feedback loop that grows the
    page without bound and hangs the tab (gradio #9068; only visible once the plot has
    data, so it was invisible locally but fatal on the deployed Space). These assertions
    are the regression guard: do NOT drop the height/autosize from ``_base_layout``.
    """

    def test_equity_figure_has_fixed_height_and_autosize_off(self):
        fig = charts.equity_curve_figure(_equity_points())
        assert fig.layout.height == charts.CHART_HEIGHT_PX
        assert fig.layout.autosize is False

    def test_empty_equity_figure_also_fixed(self):
        fig = charts.equity_curve_figure([])
        assert fig.layout.height == charts.CHART_HEIGHT_PX
        assert fig.layout.autosize is False

    def test_candlestick_figure_has_fixed_height_and_autosize_off(self):
        fig = charts.candlestick_figure(_candles())
        assert fig.layout.height == charts.CHART_HEIGHT_PX
        assert fig.layout.autosize is False

    def test_empty_candlestick_figure_also_fixed(self):
        fig = charts.candlestick_figure([])
        assert fig.layout.height == charts.CHART_HEIGHT_PX
        assert fig.layout.autosize is False


class TestEquityCurveFigure:
    def test_returns_figure(self):
        fig = charts.equity_curve_figure(_equity_points())
        assert isinstance(fig, go.Figure)

    def test_empty_points_returns_empty_figure(self):
        fig = charts.equity_curve_figure([])
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_has_a_trace(self):
        fig = charts.equity_curve_figure(_equity_points())
        assert len(fig.data) >= 1

    def test_uses_unified_hover_for_crosshair(self):
        fig = charts.equity_curve_figure(_equity_points())
        assert fig.layout.hovermode == "x unified"


class TestCandlestickFigure:
    def test_returns_candlestick_figure(self):
        fig = charts.candlestick_figure(_candles())
        assert isinstance(fig, go.Figure)
        assert any(isinstance(trace, go.Candlestick) for trace in fig.data)

    def test_empty_is_safe(self):
        fig = charts.candlestick_figure([])
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_rangeslider_hidden(self):
        fig = charts.candlestick_figure(_candles())
        assert fig.layout.xaxis.rangeslider.visible is False
