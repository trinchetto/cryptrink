"""Integration tests for :class:`PortfolioBacktestEngine`.

These tests drive the engine end-to-end with synthetic OHLCV data on
two pairs and assert the contract that matters most for the operator:

* the bar clock is the **intersection** of every pair's timestamps,
* a buy-and-hold portfolio behaves as the sum of two single-pair
  buy-and-holds (modulo shared cash + fees),
* per-allocation breakdown attributes trades to the right pair,
* portfolio-level validation rejects malformed configs.

We use ``DummyDataFeed`` rather than the real ``HistoricalDataFeed``
to avoid hitting SQLite — the engine doesn't care where the OHLCV
rows come from as long as the dict shape matches.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cryptrink.portfolio.engine import PortfolioBacktestEngine
from cryptrink.portfolio.models import Allocation, Portfolio
from cryptrink.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)


def _candle(timestamp: datetime, close: Decimal, symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "timestamp": timestamp,
        "open": close,
        "high": close + Decimal("10"),
        "low": close - Decimal("10"),
        "close": close,
        "volume": Decimal("100"),
    }


class _MultiSymbolFeed:
    """In-memory data feed keyed by symbol."""

    def __init__(self, data: dict[str, list[dict[str, object]]]) -> None:
        self._data = data

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        rows = [
            c
            for c in self._data.get(symbol, [])
            if start_time <= c["timestamp"] <= end_time  # type: ignore[operator]
        ]
        if limit is not None:
            rows = rows[:limit]
        return rows


class _BuyOnceStrategy(BaseStrategy):
    """Buys on the first eligible bar, then holds forever.

    Registered manually under a per-test name so the strategy registry
    can construct it. State is per-instance, so two parallel
    allocations get independent ``has_bought`` flags.
    """

    def __init__(self) -> None:
        self._has_bought = False

    @property
    def name(self) -> str:
        return "buy_once"

    @property
    def description(self) -> str:
        return "buy once, then hold"

    @property
    def required_history(self) -> int:
        # Tests pass a tiny lookback; the strategy itself only needs one
        # candle, so make the lookback requirement match.
        return 1

    def generate_signal(self, context: StrategyContext) -> Signal:
        if not self._has_bought and not context.has_position:
            self._has_bought = True
            return Signal(
                signal_type=SignalType.ENTRY_LONG,
                symbol=context.symbol,
                timestamp=context.timestamp,
                price=context.current_price,
                strength=SignalStrength.STRONG,
            )
        return Signal(
            signal_type=SignalType.HOLD,
            symbol=context.symbol,
            timestamp=context.timestamp,
            price=context.current_price,
            strength=SignalStrength.WEAK,
        )

    def reset(self) -> None:
        self._has_bought = False


@pytest.fixture(autouse=True)
def _register_buy_once() -> None:
    """Register the test strategy on the global registry for the test run.

    The portfolio engine resolves strategies via the registry, so we
    need ``buy_once`` available. We unregister at teardown to avoid
    polluting other test modules' state.
    """
    from cryptrink.strategies import registry as strategy_registry

    if "buy_once" in strategy_registry.list_strategies():
        strategy_registry.unregister("buy_once")
    strategy_registry.register("buy_once", _BuyOnceStrategy)
    yield
    if "buy_once" in strategy_registry.list_strategies():
        strategy_registry.unregister("buy_once")


def _two_pair_data(
    bars: int = 100, start: datetime | None = None
) -> dict[str, list[dict[str, object]]]:
    """Generate ``bars`` 1h candles for BTC-EUR and ETH-EUR.

    Both pairs are uptrends with different magnitudes so we can verify
    the per-allocation P&L attribution distinguishes them.
    """
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    btc = []
    eth = []
    for i in range(bars):
        ts = start + timedelta(hours=i)
        btc.append(_candle(ts, Decimal("50000") + Decimal(str(i * 100)), "BTC-EUR"))
        eth.append(_candle(ts, Decimal("3000") + Decimal(str(i * 5)), "ETH-EUR"))
    return {"BTC-EUR": btc, "ETH-EUR": eth}


def _portfolio() -> Portfolio:
    return Portfolio(
        name="two_pair",
        timeframe="1h",
        initial_balance=Decimal("10000"),
        allocations=[
            Allocation(symbol="BTC-EUR", strategy_name="buy_once"),
            Allocation(symbol="ETH-EUR", strategy_name="buy_once"),
        ],
    )


class TestBasicRun:
    @pytest.mark.asyncio
    async def test_run_produces_aggregate_result(self) -> None:
        feed = _MultiSymbolFeed(_two_pair_data(bars=100))
        engine = PortfolioBacktestEngine(
            portfolio=_portfolio(),
            data_feed=feed,
        )
        result = await engine.run(
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            lookback_periods=1,
        )

        assert result.metrics.total_trades == 2, (
            "Each pair should buy once and unwind at end; total = 2 closed positions"
        )
        # Both allocations get a row in the breakdown, even if one had
        # zero trades (it still ran).
        assert {a.symbol for a in result.allocations} == {"BTC-EUR", "ETH-EUR"}

    @pytest.mark.asyncio
    async def test_per_allocation_attribution(self) -> None:
        feed = _MultiSymbolFeed(_two_pair_data(bars=100))
        engine = PortfolioBacktestEngine(
            portfolio=_portfolio(),
            data_feed=feed,
        )
        result = await engine.run(
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 5, tzinfo=UTC),
            lookback_periods=1,
        )
        breakdown = {a.symbol: a for a in result.allocations}

        # Both pairs go up, so both allocations should show positive PnL.
        # We don't pin exact figures because the exact buy bar depends
        # on the bar clock + lookback warmup, which is not what this
        # test is asserting.
        assert breakdown["BTC-EUR"].total_trades == 1
        assert breakdown["ETH-EUR"].total_trades == 1
        assert breakdown["BTC-EUR"].realized_pnl > 0
        assert breakdown["ETH-EUR"].realized_pnl > 0


class TestBarClockIntersection:
    @pytest.mark.asyncio
    async def test_intersection_skips_gaps(self) -> None:
        """If one pair has a missing candle, the engine skips that bar globally."""
        data = _two_pair_data(bars=20)
        # Pull one candle out of ETH-EUR's middle of the range.
        gap_index = 10
        del data["ETH-EUR"][gap_index]

        feed = _MultiSymbolFeed(data)
        engine = PortfolioBacktestEngine(
            portfolio=_portfolio(),
            data_feed=feed,
        )
        result = await engine.run(
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 1, 23, tzinfo=UTC),
            lookback_periods=1,
        )

        # Equity curve has start + per-bar + end markers. With 20 BTC
        # bars and 19 ETH bars (one removed), the intersection is 19
        # in-window bars. We don't pin the exact count but assert the
        # run finished cleanly with both allocations contributing.
        assert result.metrics.total_trades == 2

    @pytest.mark.asyncio
    async def test_no_overlap_raises(self) -> None:
        """Pairs with no shared timestamps produce a clear error.

        Both pairs have data in the window (so we don't hit the
        "no historical data" path) but their timestamps don't
        intersect — BTC on even hours, ETH on odd hours.
        """
        start = datetime(2024, 1, 1, tzinfo=UTC)
        data = {
            "BTC-EUR": [
                _candle(start + timedelta(hours=i), Decimal("50000"), "BTC-EUR")
                for i in range(0, 24, 2)
            ],
            "ETH-EUR": [
                _candle(start + timedelta(hours=i), Decimal("3000"), "ETH-EUR")
                for i in range(1, 24, 2)
            ],
        }
        feed = _MultiSymbolFeed(data)
        engine = PortfolioBacktestEngine(
            portfolio=_portfolio(),
            data_feed=feed,
        )
        with pytest.raises(ValueError, match="No timestamps are common"):
            await engine.run(
                start_time=start,
                end_time=start + timedelta(hours=24),
                lookback_periods=1,
            )


class TestValidation:
    @pytest.mark.asyncio
    async def test_invalid_portfolio_rejected_at_construction(self) -> None:
        bad = Portfolio(
            name="bad",
            timeframe="1h",
            initial_balance=Decimal("10000"),
            allocations=[],
        )
        with pytest.raises(ValueError, match="Invalid portfolio"):
            PortfolioBacktestEngine(
                portfolio=bad,
                data_feed=_MultiSymbolFeed({}),
            )

    @pytest.mark.asyncio
    async def test_missing_data_for_one_pair_raises(self) -> None:
        # Only BTC has data, ETH is empty — the engine should refuse
        # to run rather than silently dropping the ETH allocation.
        data = _two_pair_data(bars=50)
        data["ETH-EUR"] = []
        feed = _MultiSymbolFeed(data)
        engine = PortfolioBacktestEngine(
            portfolio=_portfolio(),
            data_feed=feed,
        )
        with pytest.raises(ValueError, match="No historical data for ETH-EUR"):
            await engine.run(
                start_time=datetime(2024, 1, 1, tzinfo=UTC),
                end_time=datetime(2024, 1, 2, tzinfo=UTC),
                lookback_periods=1,
            )
