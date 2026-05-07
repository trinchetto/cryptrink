"""Integration tests for BacktestEngine.

These tests verify the full backtest flow including:
- Historical data loading
- Event-driven replay
- Strategy integration (placeholder until TradingEngine supports it)
- Equity curve tracking
- Metrics calculation
- Result generation

Note: These tests use mock OHLCV data since the full data layer is not yet implemented.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cryptrink.backtest.engine import BacktestEngine
from cryptrink.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)


def MockOHLCV(
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    open: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal,
) -> dict[str, object]:
    """Build a dict-shaped OHLCV candle that matches HistoricalDataFeed output."""
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "open": open,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class DummyDataFeed:
    """Dummy historical data feed for testing."""

    def __init__(self, ohlcv_data: list[dict[str, object]]):
        """Initialize with OHLCV data."""
        self._data = ohlcv_data

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        """Return filtered OHLCV data."""
        rows = [c for c in self._data if start_time <= c["timestamp"] <= end_time]
        if limit is not None:
            rows = rows[:limit]
        return rows


class AlwaysHoldStrategy(BaseStrategy):
    """Strategy that always holds (no trades)."""

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "AlwaysHoldStrategy"

    @property
    def description(self) -> str:
        """Return strategy description."""
        return "Test strategy that never trades"

    def generate_signal(self, context: StrategyContext) -> Signal:
        """Generate HOLD signal."""
        return Signal(
            signal_type=SignalType.HOLD,
            symbol=context.symbol,
            timestamp=context.timestamp,
            price=context.current_price,
            strength=SignalStrength.WEAK,
        )


class SimpleBuyHoldStrategy(BaseStrategy):
    """Strategy that buys on first candle and holds."""

    def __init__(self):
        """Initialize strategy."""
        self._has_bought = False

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "SimpleBuyHoldStrategy"

    @property
    def description(self) -> str:
        """Return strategy description."""
        return "Test strategy that buys once and holds"

    def generate_signal(self, context: StrategyContext) -> Signal:
        """Buy once, then hold."""
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


@pytest.fixture
def sample_ohlcv_data():
    """Create sample OHLCV data for testing (30 days of 1h candles)."""
    start_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = []

    for i in range(30 * 24):  # 30 days * 24 hours
        timestamp = start_time + timedelta(hours=i)
        # Simple uptrend: price increases slightly each hour
        base_price = Decimal("50000") + Decimal(str(i * 10))

        candles.append(
            MockOHLCV(
                symbol="BTC-USD",
                timeframe="1h",
                timestamp=timestamp,
                open=base_price,
                high=base_price + Decimal("100"),
                low=base_price - Decimal("50"),
                close=base_price + Decimal("50"),
                volume=Decimal("100"),
            )
        )

    return candles


@pytest.fixture
def dummy_data_feed(sample_ohlcv_data):
    """Create dummy data feed with sample data."""
    return DummyDataFeed(sample_ohlcv_data)


class TestBacktestEngineBasicFlow:
    """Tests for basic backtest engine functionality."""

    @pytest.mark.asyncio
    async def test_engine_initialization(self, dummy_data_feed):
        """Test BacktestEngine can be initialized."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        assert engine is not None
        assert engine._initial_balance == Decimal("10000")

    @pytest.mark.asyncio
    async def test_run_with_no_trades(self, dummy_data_feed):
        """Test backtest run with strategy that makes no trades."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 7, tzinfo=UTC),  # 7 days
            timeframe="1h",
            lookback_periods=50,
        )

        # Verify result structure
        assert result is not None
        assert result.strategy_name == "AlwaysHoldStrategy"
        assert result.symbol == "BTC-USD"
        assert result.timeframe == "1h"
        assert result.initial_balance == Decimal("10000")

        # With no trades, balance should be unchanged
        assert result.metrics.ending_equity == Decimal("10000")
        assert result.metrics.total_trades == 0
        assert len(result.trades) == 0

        # Equity curve should exist
        assert len(result.equity_curve) > 0

    @pytest.mark.asyncio
    async def test_equity_curve_tracking(self, dummy_data_feed):
        """Test equity curve is tracked throughout backtest."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),  # 3 days
            timeframe="1h",
            lookback_periods=10,
        )

        # Equity curve should have entries for each candle in the backtest period
        # 3 days * 24 hours = 72 candles, but start/end are inclusive so might be less
        # With lookback of 10, the actual backtest period is shorter
        assert len(result.equity_curve) >= 48  # At least 2 days worth

        # All equity values should be Decimal
        for timestamp, equity in result.equity_curve:
            assert isinstance(timestamp, datetime)
            assert isinstance(equity, Decimal)

    @pytest.mark.asyncio
    async def test_lookback_period_handling(self, dummy_data_feed):
        """Test lookback period is properly handled."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        # Request backtest with lookback
        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 2, tzinfo=UTC),  # Start on day 2
            end_time=datetime(2024, 1, 4, tzinfo=UTC),  # End on day 4
            timeframe="1h",
            lookback_periods=24,  # 1 day of lookback
        )

        # Data feed should have been queried from day 1 (lookback) to day 4
        # Result should only include day 2-4
        assert result.start_time == datetime(2024, 1, 2, tzinfo=UTC)
        assert result.end_time == datetime(2024, 1, 4, tzinfo=UTC)


class TestBacktestEngineWithTrades:
    """Tests for backtest with actual trading.

    Strategy signals are now routed from BacktestEngine into TradingEngine,
    so these tests assert that trades actually execute end-to-end.
    """

    @pytest.mark.asyncio
    async def test_run_with_buy_hold_strategy(self, dummy_data_feed):
        """Test backtest with strategy that attempts to buy and hold."""
        strategy = SimpleBuyHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 7, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=50,
        )

        # Verify basic result structure
        assert result.strategy_name == "SimpleBuyHoldStrategy"
        assert result.initial_balance == Decimal("10000")

        # Strategy signals are now executed: SimpleBuyHoldStrategy emits an
        # ENTRY_LONG on the first in-window candle, the executor opens a
        # position, and end-of-backtest forces it closed -- so the ending
        # balance must differ from the initial deposit.
        # NOTE: result.metrics.total_trades is read from the engine's
        # PositionTracker, which BacktestExecutor does not yet sync to;
        # ending_equity is the unambiguous signal that trades executed.
        assert result.metrics.ending_equity != Decimal("10000")


class TestBacktestEngineMetrics:
    """Tests for metrics calculation in backtest results."""

    @pytest.mark.asyncio
    async def test_metrics_calculation(self, dummy_data_feed):
        """Test comprehensive metrics are calculated."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 7, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=50,
        )

        # Verify metrics structure
        metrics = result.metrics
        assert metrics.starting_equity == Decimal("10000")
        assert metrics.ending_equity >= Decimal("0")
        assert metrics.total_days >= 6  # At least 6 days
        assert metrics.total_trades >= 0
        assert metrics.winning_trades >= 0
        assert metrics.losing_trades >= 0

        # Sharpe and Sortino should be calculated
        assert isinstance(metrics.sharpe_ratio, Decimal)
        assert isinstance(metrics.sortino_ratio, Decimal)

    @pytest.mark.asyncio
    async def test_drawdown_curve_calculated(self, dummy_data_feed):
        """Test drawdown curve is calculated."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 7, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=50,
        )

        # Drawdown curve should exist and match equity curve length
        assert len(result.drawdown_curve) > 0
        assert len(result.drawdown_curve) == len(result.equity_curve)

        # All drawdown values should be Decimal
        for timestamp, drawdown in result.drawdown_curve:
            assert isinstance(timestamp, datetime)
            assert isinstance(drawdown, Decimal)
            assert drawdown >= Decimal("0")  # Drawdown is always non-negative


class TestBacktestEngineSlippageAndFees:
    """Tests for slippage and fee integration."""

    @pytest.mark.asyncio
    async def test_custom_slippage_model(self, dummy_data_feed):
        """Test backtest with custom slippage model."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
            slippage_bps=Decimal("0.002"),  # 20 bps (higher than default)
            fee_pct=Decimal("0.001"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=10,
        )

        # Verify result is generated
        assert result is not None

    @pytest.mark.asyncio
    async def test_custom_fee_model(self, dummy_data_feed):
        """Test backtest with custom fee model."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
            slippage_bps=Decimal("0.0005"),
            fee_pct=Decimal("0.002"),  # 0.2% (higher than default)
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=10,
        )

        # Verify result is generated
        assert result is not None

    @pytest.mark.asyncio
    async def test_zero_fees_and_slippage(self, dummy_data_feed):
        """Test backtest with zero fees and slippage."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
            slippage_bps=Decimal("0"),
            fee_pct=Decimal("0"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=10,
        )

        # Verify result is generated
        assert result is not None


class TestBacktestEngineEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_historical_data(self, dummy_data_feed):
        """Test backtest with no historical data raises error."""
        # Create data feed with no data
        empty_feed = DummyDataFeed([])

        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=empty_feed,
            initial_balance=Decimal("10000"),
        )

        with pytest.raises(ValueError, match="No historical data found"):
            await engine.run(
                symbol="BTC-USD",
                start_time=datetime(2024, 1, 1, tzinfo=UTC),
                end_time=datetime(2024, 1, 7, tzinfo=UTC),
                timeframe="1h",
                lookback_periods=50,
            )

    @pytest.mark.asyncio
    async def test_invalid_timeframe(self, dummy_data_feed):
        """Test backtest with invalid timeframe raises error."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        with pytest.raises(ValueError, match="Unsupported timeframe"):
            await engine.run(
                symbol="BTC-USD",
                start_time=datetime(2024, 1, 1, tzinfo=UTC),
                end_time=datetime(2024, 1, 7, tzinfo=UTC),
                timeframe="invalid",  # Invalid timeframe
                lookback_periods=50,
            )

    @pytest.mark.asyncio
    async def test_single_candle_backtest(self, dummy_data_feed):
        """Test backtest with only a single candle."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
            end_time=datetime(2024, 1, 1, 1, 0, 0, tzinfo=UTC),  # 1 hour
            timeframe="1h",
            lookback_periods=10,
        )

        # Should still generate valid result
        assert result is not None
        assert len(result.equity_curve) >= 1


class TestBacktestResultOutput:
    """Tests for BacktestResult output methods."""

    @pytest.mark.asyncio
    async def test_result_to_dict(self, dummy_data_feed):
        """Test BacktestResult.to_dict() serialization."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=10,
        )

        # Convert to dict
        result_dict = result.to_dict()

        # Verify structure
        assert isinstance(result_dict, dict)
        assert "strategy" in result_dict
        assert "symbol" in result_dict
        assert "metrics" in result_dict
        assert "equity_curve" in result_dict
        assert "drawdown_curve" in result_dict

        # Verify metrics are serialized
        assert isinstance(result_dict["metrics"], dict)
        assert "total_return" in result_dict["metrics"]
        assert "sharpe_ratio" in result_dict["metrics"]

    @pytest.mark.asyncio
    async def test_result_print_summary(self, dummy_data_feed, capsys):
        """Test BacktestResult.print_summary() output."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=dummy_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=10,
        )

        # Print summary
        result.print_summary()

        # Capture output
        captured = capsys.readouterr()
        output = captured.out

        # Verify key sections are present
        assert "Backtest Results" in output
        assert "AlwaysHoldStrategy" in output
        assert "BTC-USD" in output
        assert "RETURNS" in output
        assert "RISK METRICS" in output
        assert "TRADE STATISTICS" in output


class TestRealStrategyIntegration:
    """Tests for integration with real implemented strategies.

    Note: These tests verify that real strategies can be instantiated with
    BacktestEngine. Since TradingEngine doesn't yet call strategy.generate_signal()
    (see TODO in engine.py:201-209), the strategies won't execute trades.
    These tests ensure the infrastructure is ready for when that integration is complete.
    """

    @pytest.fixture
    def uptrend_data_feed(self):
        """Create data feed with uptrend for testing strategies."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        candles = []

        # Create strong uptrend to trigger strategy signals
        for i in range(100):
            timestamp = start_time + timedelta(hours=i)
            base_price = Decimal("50000") + Decimal(str(i * 100))  # Strong uptrend

            candles.append(
                MockOHLCV(
                    symbol="BTC-USD",
                    timeframe="1h",
                    timestamp=timestamp,
                    open=base_price,
                    high=base_price + Decimal("200"),
                    low=base_price - Decimal("100"),
                    close=base_price + Decimal("100"),
                    volume=Decimal("100"),
                )
            )

        return DummyDataFeed(candles)

    @pytest.mark.asyncio
    async def test_sma_crossover_strategy_integration(self, uptrend_data_feed):
        """Test BacktestEngine with SmaCrossoverStrategy."""
        from cryptrink.strategies.trend_following import SmaCrossoverStrategy

        strategy = SmaCrossoverStrategy(fast_period=5, slow_period=20)

        engine = BacktestEngine(
            strategy=strategy,
            data_feed=uptrend_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=30,  # Need enough for slow SMA
        )

        # Verify backtest completes successfully
        assert result.strategy_name == "SmaCrossoverStrategy"
        assert result.symbol == "BTC-USD"
        assert result.initial_balance == Decimal("10000")
        assert len(result.equity_curve) > 0

        # Note: No trades expected since TradingEngine doesn't call strategy yet
        # This will change when TODO is implemented

    @pytest.mark.asyncio
    async def test_rsi_mean_reversion_strategy_integration(self, uptrend_data_feed):
        """Test BacktestEngine with RsiMeanReversionStrategy."""
        from cryptrink.strategies.mean_reversion import RsiMeanReversionStrategy

        strategy = RsiMeanReversionStrategy(
            rsi_period=14, oversold_threshold=30, overbought_threshold=70
        )

        engine = BacktestEngine(
            strategy=strategy,
            data_feed=uptrend_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=40,  # Need enough for RSI calculation
        )

        # Verify backtest completes successfully
        assert result.strategy_name == "RsiMeanReversionStrategy"
        assert result.symbol == "BTC-USD"
        assert result.initial_balance == Decimal("10000")
        assert len(result.equity_curve) > 0

    @pytest.mark.asyncio
    async def test_bollinger_bands_strategy_integration(self, uptrend_data_feed):
        """Test BacktestEngine with BollingerBandsStrategy."""
        from cryptrink.strategies.mean_reversion import BollingerBandsStrategy

        strategy = BollingerBandsStrategy(period=20, std_dev=2.0)

        engine = BacktestEngine(
            strategy=strategy,
            data_feed=uptrend_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=35,  # Need enough for Bollinger Bands
        )

        # Verify backtest completes successfully
        assert result.strategy_name == "BollingerBandsStrategy"
        assert result.symbol == "BTC-USD"
        assert result.initial_balance == Decimal("10000")
        assert len(result.equity_curve) > 0


class TestBacktestEngineTimestampHandling:
    """Regression tests for the candle-timestamp coercion.

    The production :class:`HistoricalDataFeed` returns ``timestamp`` as a
    raw int (milliseconds since epoch). The engine must coerce these into
    UTC ``datetime`` objects for the equity curve and for the strategy
    context. A previous bug used ``isinstance(candle_ts, datetime)`` which
    silently failed against ints — every equity curve entry stamped at
    ``datetime.now()`` and rendered as a flat right-edge line.
    """

    @pytest.fixture
    def int_ms_data_feed(self):
        """Build a feed that yields candles with raw int-ms timestamps.

        Mirrors :class:`HistoricalDataFeed` in production, which returns
        ``record.timestamp`` (an int) directly off the OHLCV table.
        """
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = []
        for i in range(72):  # 3 days of 1h candles
            ts = start + timedelta(hours=i)
            base = Decimal("50000") + Decimal(str(i * 10))
            candles.append(
                {
                    "symbol": "BTC-USD",
                    "timeframe": "1h",
                    "timestamp": int(ts.timestamp() * 1000),  # raw int ms
                    "open": base,
                    "high": base + Decimal("100"),
                    "low": base - Decimal("50"),
                    "close": base + Decimal("50"),
                    "volume": Decimal("100"),
                }
            )

        class IntMsDataFeed:
            def __init__(self, data):
                self._data = data

            async def get_ohlcv(
                self,
                symbol: str,
                timeframe: str,
                start_time: datetime,
                end_time: datetime,
                limit: int | None = None,
            ) -> list[dict[str, object]]:
                start_ms = int(start_time.timestamp() * 1000)
                end_ms = int(end_time.timestamp() * 1000)
                rows = [c for c in self._data if start_ms <= int(c["timestamp"]) <= end_ms]
                if limit is not None:
                    rows = rows[:limit]
                return rows

        return IntMsDataFeed(candles)

    @pytest.mark.asyncio
    async def test_equity_curve_uses_real_per_candle_timestamps(self, int_ms_data_feed):
        """Each equity-curve entry must be stamped at its candle, not now."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=int_ms_data_feed,
            initial_balance=Decimal("10000"),
        )

        result = await engine.run(
            symbol="BTC-USD",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=10,
        )

        assert len(result.equity_curve) >= 24  # at least one in-window day
        timestamps = [ts for ts, _ in result.equity_curve]
        # Every entry must be timezone-aware datetime in 2024 — not the
        # fall-back datetime.now() that the previous bug produced.
        for ts in timestamps:
            assert isinstance(ts, datetime)
            assert ts.tzinfo is not None
            assert ts.year == 2024
        # The curve must span more than a few microseconds (the bug compressed
        # all entries to within a few ms of each other).
        span = timestamps[-1] - timestamps[0]
        assert span.total_seconds() > 60 * 60  # > 1 hour

    @pytest.mark.asyncio
    async def test_lookback_skip_works_with_int_ms_timestamps(self, int_ms_data_feed):
        """Lookback candles must be skipped — the equity curve must not
        contain any entries before ``start_time``. Previously the
        ``isinstance(candle_ts, datetime)`` check silently let lookback
        candles through because their timestamps were ints."""
        strategy = AlwaysHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            data_feed=int_ms_data_feed,
            initial_balance=Decimal("10000"),
        )
        start_time = datetime(2024, 1, 2, tzinfo=UTC)
        result = await engine.run(
            symbol="BTC-USD",
            start_time=start_time,
            end_time=datetime(2024, 1, 3, tzinfo=UTC),
            timeframe="1h",
            lookback_periods=10,
        )
        # Only the seed entry at start_time may equal start_time exactly;
        # every other entry must be at or after start_time.
        for ts, _ in result.equity_curve:
            assert ts >= start_time


class TestBacktestEngineDataLimit:
    """Regression: BacktestEngine must request *all* candles in the window.

    :class:`HistoricalDataFeed.get_ohlcv` defaults to ``limit=100``. A
    backtest that asks for "all rows in this window" but doesn't pass a
    larger limit silently truncates to the first 100 candles — usually
    100% lookback, leaving the strategy with no in-window data and the
    user staring at a flat equity curve and a "100 hold" signal log.
    This regression test pins the explicit-limit fix in place.
    """

    @pytest.mark.asyncio
    async def test_engine_requests_more_than_default_100_candles(self):
        """The engine must override the data_feed's default limit so it
        gets the full window, not just the first 100 candles."""
        observed_limits: list[int | None] = []

        class CapturingFeed:
            def __init__(self, candles: list[dict[str, object]]):
                self._candles = candles

            async def get_ohlcv(
                self,
                symbol: str,
                timeframe: str,
                start_time: datetime,
                end_time: datetime,
                limit: int | None = None,
            ) -> list[dict[str, object]]:
                observed_limits.append(limit)
                # Match HistoricalDataFeed's default behaviour: if no limit
                # is passed, cap at 100 to prove the caller MUST pass one.
                effective_limit = limit if limit is not None else 100
                rows = [c for c in self._candles if start_time <= c["timestamp"] <= end_time]
                return rows[:effective_limit]

        # 500 hourly candles — well over the 100-default cap.
        start = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            {
                "symbol": "BTC-USD",
                "timeframe": "1h",
                "timestamp": start + timedelta(hours=i),
                "open": Decimal("100"),
                "high": Decimal("105"),
                "low": Decimal("95"),
                "close": Decimal("100"),
                "volume": Decimal("1"),
            }
            for i in range(500)
        ]
        feed = CapturingFeed(candles)

        engine = BacktestEngine(
            strategy=AlwaysHoldStrategy(),
            data_feed=feed,
            initial_balance=Decimal("10000"),
        )
        result = await engine.run(
            symbol="BTC-USD",
            start_time=start,
            end_time=start + timedelta(hours=499),
            timeframe="1h",
            lookback_periods=50,
        )
        # The engine made exactly one get_ohlcv call and passed an
        # explicit limit large enough to swallow the whole window.
        assert len(observed_limits) == 1
        assert observed_limits[0] is not None
        assert observed_limits[0] > 500
        # And the result reflects the full window — not 100 candles.
        # 500 in-window + initial seed = 501 entries.
        assert len(result.equity_curve) > 100
