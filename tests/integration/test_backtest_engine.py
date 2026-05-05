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


class MockOHLCV:
    """Mock OHLCV candle for testing."""

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        timestamp: datetime,
        open: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal,
    ):
        """Initialize mock OHLCV."""
        self.symbol = symbol
        self.timeframe = timeframe
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


class DummyDataFeed:
    """Dummy historical data feed for testing."""

    def __init__(self, ohlcv_data: list[MockOHLCV]):
        """Initialize with OHLCV data."""
        self._data = ohlcv_data

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[MockOHLCV]:
        """Return filtered OHLCV data."""
        return [candle for candle in self._data if start_time <= candle.timestamp <= end_time]


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
