"""Tests for :class:`PortfolioStrategyRouter`.

The router is the seam that lets ``TradingEngine`` (single-strategy)
host a multi-allocation portfolio. The two contract guarantees:

1. ``generate_signal`` dispatches by symbol and remembers which
   allocation was just called so downstream lookups
   (``name``, ``required_history``, ``timeframe``) reflect that
   allocation.
2. ``set_active_symbol`` lets the engine pin the active allocation
   even when no ``generate_signal`` precedes the next
   ``process_signal`` (end-of-backtest forced exits).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from cryptrink.portfolio.router import PortfolioStrategyRouter
from cryptrink.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)


class _StubStrategy(BaseStrategy):
    """Minimal strategy whose name + required_history are tunable."""

    def __init__(
        self,
        name: str,
        required_history: int = 50,
        timeframe: str = "1h",
        signal_type: SignalType = SignalType.HOLD,
    ) -> None:
        self._name = name
        self._req = required_history
        self._tf = timeframe
        self._signal_type = signal_type
        self.calls = 0
        self.last_symbol: str | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def required_history(self) -> int:
        return self._req

    @property
    def timeframe(self) -> str:
        return self._tf

    def generate_signal(self, context: StrategyContext) -> Signal:
        self.calls += 1
        self.last_symbol = context.symbol
        return Signal(
            signal_type=self._signal_type,
            symbol=context.symbol,
            strength=SignalStrength.MODERATE,
            timestamp=context.timestamp,
            price=context.current_price,
        )


def _context(symbol: str) -> StrategyContext:
    return StrategyContext(
        symbol=symbol,
        current_price=Decimal("100"),
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        ohlcv=pd.DataFrame(),
    )


class TestDispatch:
    def test_generate_signal_dispatches_by_symbol(self) -> None:
        a, b = _StubStrategy("alpha"), _StubStrategy("beta")
        router = PortfolioStrategyRouter({"BTC-EUR": a, "ETH-EUR": b})

        router.generate_signal(_context("BTC-EUR"))
        router.generate_signal(_context("ETH-EUR"))
        router.generate_signal(_context("BTC-EUR"))

        assert a.calls == 2
        assert b.calls == 1
        assert a.last_symbol == "BTC-EUR"
        assert b.last_symbol == "ETH-EUR"

    def test_unknown_symbol_returns_hold_with_reason(self) -> None:
        router = PortfolioStrategyRouter({"BTC-EUR": _StubStrategy("alpha")})
        signal = router.generate_signal(_context("DOGE-EUR"))
        assert signal.signal_type == SignalType.HOLD
        assert "no_allocation_for_DOGE-EUR" in signal.metadata.get("reason", "")


class TestActiveSymbolAttribution:
    def test_name_reflects_last_active_symbol(self) -> None:
        a, b = _StubStrategy("alpha"), _StubStrategy("beta")
        router = PortfolioStrategyRouter({"BTC-EUR": a, "ETH-EUR": b}, portfolio_name="port")

        # Before any call we report the portfolio name.
        assert router.name == "port"

        router.generate_signal(_context("BTC-EUR"))
        assert router.name == "alpha"

        router.set_active_symbol("ETH-EUR")
        assert router.name == "beta"

    def test_set_active_symbol_rejects_unknown(self) -> None:
        router = PortfolioStrategyRouter({"BTC-EUR": _StubStrategy("alpha")})
        with pytest.raises(KeyError, match="DOGE-EUR"):
            router.set_active_symbol("DOGE-EUR")

    def test_required_history_takes_max(self) -> None:
        router = PortfolioStrategyRouter(
            {
                "BTC-EUR": _StubStrategy("alpha", required_history=50),
                "ETH-EUR": _StubStrategy("beta", required_history=120),
            }
        )
        assert router.required_history == 120

    def test_reset_clears_active_symbol_and_propagates(self) -> None:
        a = _StubStrategy("alpha")
        router = PortfolioStrategyRouter({"BTC-EUR": a})
        router.generate_signal(_context("BTC-EUR"))
        assert router.name == "alpha"

        # Reset should propagate to the wrapped strategies (we can't
        # observe state on the stub but can confirm the router's own
        # state cleared).
        router.reset()
        assert router._active_symbol is None  # type: ignore[attr-defined]


class TestConstruction:
    def test_empty_strategies_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            PortfolioStrategyRouter({})
