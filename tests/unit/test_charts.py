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
