"""Unit tests for CLI formatters."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

from rich.panel import Panel
from rich.table import Table

from cryptrink.backtest.metrics import BacktestMetrics
from cryptrink.backtest.result import BacktestResult
from cryptrink.cli.formatters import (
    format_backtest_results_table,
    format_engine_status_panel,
    format_order_history_table,
    format_trade_history_table,
    format_trade_suggestions_table,
)
from cryptrink.strategies.base import Signal, SignalStrength, SignalType


class TestFormatBacktestResultsTable:
    """Tests for format_backtest_results_table."""

    def test_format_backtest_results_basic(self):
        """Test formatting basic backtest results."""
        metrics = BacktestMetrics(
            total_return=Decimal("1500.0"),
            total_return_pct=Decimal("0.15"),
            annualized_return=Decimal("25.0"),
            sharpe_ratio=Decimal("1.5"),
            sortino_ratio=Decimal("2.0"),
            max_drawdown=Decimal("0.10"),
            max_drawdown_duration=10,
            total_trades=50,
            winning_trades=30,
            losing_trades=20,
            win_rate=Decimal("0.60"),
            profit_factor=Decimal("1.8"),
            avg_win=Decimal("100.0"),
            avg_loss=Decimal("-50.0"),
            avg_trade=Decimal("30.0"),
            best_trade=Decimal("500.0"),
            worst_trade=Decimal("-200.0"),
            max_win_streak=5,
            max_loss_streak=3,
            current_streak=2,
            total_days=365,
            trading_days=250,
            starting_equity=Decimal("10000.0"),
            ending_equity=Decimal("11500.0"),
            peak_equity=Decimal("12000.0"),
        )

        result = BacktestResult(
            strategy_name="test_strategy",
            symbol="BTC-EUR",
            timeframe="1h",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 12, 31, tzinfo=UTC),
            initial_balance=Decimal("10000.0"),
            metrics=metrics,
            equity_curve=[],
            trades=[],
            orders=[],
            drawdown_curve=[],
        )

        table = format_backtest_results_table(result)

        assert isinstance(table, Table)
        assert table.title == "Backtest Results: test_strategy"
        assert len(table.columns) == 2


class TestFormatTradeSuggestionsTable:
    """Tests for format_trade_suggestions_table."""

    def test_format_trade_suggestions_long(self):
        """Test formatting LONG signal."""
        signal = Signal(
            symbol="BTC-EUR",
            signal_type=SignalType.ENTRY_LONG,
            price=Decimal("50000.0"),
            strength=SignalStrength.STRONG,
            stop_loss=Decimal("48000.0"),
            take_profit=Decimal("55000.0"),
            timestamp=datetime.now(UTC),
        )

        table = format_trade_suggestions_table([signal])

        assert isinstance(table, Table)
        assert table.title == "Trade Suggestions"
        assert len(table.columns) == 6

    def test_format_trade_suggestions_short(self):
        """Test formatting SHORT signal."""
        signal = Signal(
            symbol="ETH-EUR",
            signal_type=SignalType.ENTRY_SHORT,
            price=Decimal("3000.0"),
            strength=SignalStrength.MODERATE,
            stop_loss=Decimal("3100.0"),
            take_profit=Decimal("2800.0"),
            timestamp=datetime.now(UTC),
        )

        table = format_trade_suggestions_table([signal])

        assert isinstance(table, Table)

    def test_format_trade_suggestions_no_stops(self):
        """Test formatting signal without stop loss / take profit."""
        signal = Signal(
            symbol="BTC-EUR",
            signal_type=SignalType.ENTRY_LONG,
            price=Decimal("50000.0"),
            strength=SignalStrength.WEAK,
            timestamp=datetime.now(UTC),
        )

        table = format_trade_suggestions_table([signal])

        assert isinstance(table, Table)


class TestFormatTradeHistoryTable:
    """Tests for format_trade_history_table."""

    def test_format_trade_history_closed_position(self):
        """Test formatting closed position."""
        # Create mock position with required attributes
        # opened_at and closed_at are Unix timestamps in milliseconds
        position = Mock()
        position.symbol = "BTC-EUR"
        position.side = "long"
        position.entry_price = "50000.0"
        position.exit_price = "55000.0"
        position.realized_pnl = "500.0"
        position.total_fees = "10.0"
        position.opened_at = 1704103200000  # 2024-01-01 10:00 UTC
        position.closed_at = 1704189600000  # 2024-01-02 10:00 UTC

        table = format_trade_history_table([position])

        assert isinstance(table, Table)
        assert table.title == "Trade History"
        assert len(table.columns) == 8

    def test_format_trade_history_open_position(self):
        """Test formatting open position."""
        position = Mock()
        position.symbol = "BTC-EUR"
        position.side = "long"
        position.entry_price = "50000.0"
        position.exit_price = None
        position.realized_pnl = None
        position.total_fees = "5.0"
        position.opened_at = 1704103200000  # 2024-01-01 10:00 UTC
        position.closed_at = None

        table = format_trade_history_table([position])

        assert isinstance(table, Table)


class TestFormatOrderHistoryTable:
    """Tests for format_order_history_table."""

    def test_format_order_history_filled(self):
        """Test formatting filled order."""
        # created_at is Unix timestamp in milliseconds
        order = Mock()
        order.symbol = "BTC-EUR"
        order.side = "buy"
        order.order_type = "market"
        order.quantity = "0.1"
        order.price = "50000.0"
        order.status = "filled"
        order.created_at = 1704103200000  # 2024-01-01 10:00 UTC

        table = format_order_history_table([order])

        assert isinstance(table, Table)
        assert table.title == "Order History"
        assert len(table.columns) == 7

    def test_format_order_history_market_order(self):
        """Test formatting market order without price."""
        # created_at is Unix timestamp in milliseconds
        order = Mock()
        order.symbol = "BTC-EUR"
        order.side = "buy"
        order.order_type = "market"
        order.quantity = "0.1"
        order.price = None
        order.status = "filled"
        order.created_at = 1704103200000  # 2024-01-01 10:00 UTC

        table = format_order_history_table([order])

        assert isinstance(table, Table)


class TestFormatEngineStatusPanel:
    """Tests for format_engine_status_panel."""

    def test_format_engine_status_running(self):
        """Test formatting running engine status."""
        status = {
            "engine_id": "engine_123",
            "strategy": "sma_crossover",
            "mode": "paper",
            "is_running": True,
            "balance": 10500.0,
            "realized_pnl": 500.0,
            "unrealized_pnl": 50.0,
            "open_positions": 2,
            "signal_count": 100,
            "execution_count": 50,
        }

        panel = format_engine_status_panel(status)

        assert isinstance(panel, Panel)
        assert panel.title == "Trading Engine Status"
        assert "engine_123" in panel.renderable

    def test_format_engine_status_stopped(self):
        """Test formatting stopped engine status."""
        status = {
            "engine_id": "engine_123",
            "strategy": "sma_crossover",
            "mode": "paper",
            "is_running": False,
            "balance": 10000.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "open_positions": 0,
            "signal_count": 0,
            "execution_count": 0,
        }

        panel = format_engine_status_panel(status)

        assert isinstance(panel, Panel)
        assert "❌ No" in panel.renderable
