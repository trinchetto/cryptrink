"""Unit tests for BacktestResult."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cryptrink.backtest.metrics import BacktestMetrics
from cryptrink.backtest.result import BacktestResult
from cryptrink.execution.models import Order, Position


@pytest.fixture
def sample_metrics():
    """Create sample BacktestMetrics."""
    return BacktestMetrics(
        total_return=Decimal("250"),
        total_return_pct=Decimal("0.025"),
        annualized_return=Decimal("0.30"),
        sharpe_ratio=Decimal("1.5"),
        sortino_ratio=Decimal("2.0"),
        max_drawdown=Decimal("0.1"),
        max_drawdown_duration=10,
        total_trades=10,
        winning_trades=6,
        losing_trades=4,
        win_rate=Decimal("0.6"),
        profit_factor=Decimal("2.0"),
        avg_win=Decimal("50"),
        avg_loss=Decimal("25"),
        avg_trade=Decimal("25"),
        best_trade=Decimal("100"),
        worst_trade=Decimal("-50"),
        max_win_streak=3,
        max_loss_streak=2,
        current_streak=1,
        total_days=30,
        trading_days=15,
        starting_equity=Decimal("10000"),
        ending_equity=Decimal("10250"),
        peak_equity=Decimal("10500"),
    )


@pytest.fixture
def sample_equity_curve():
    """Create sample equity curve."""
    start_time = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        (start_time, Decimal("10000")),
        (start_time + timedelta(days=10), Decimal("10100")),
        (start_time + timedelta(days=20), Decimal("10200")),
        (start_time + timedelta(days=30), Decimal("10250")),
    ]


@pytest.fixture
def sample_drawdown_curve():
    """Create sample drawdown curve."""
    start_time = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        (start_time, Decimal("0")),
        (start_time + timedelta(days=10), Decimal("0.05")),
        (start_time + timedelta(days=20), Decimal("0.1")),
        (start_time + timedelta(days=30), Decimal("0.02")),
    ]


@pytest.fixture
def sample_positions():
    """Create sample closed positions."""
    base_time = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)

    return [
        Position(
            position_id="pos-1",
            symbol="BTC-USD",
            side="long",
            status="closed",
            quantity="0.01",
            entry_price="50000",
            exit_price="51000",
            realized_pnl="10",
            unrealized_pnl="0",
            total_fees="1",
            opened_at=base_time,
            closed_at=base_time + 86400000,
            entry_order_id="order-1",
            exit_order_id="order-2",
        ),
        Position(
            position_id="pos-2",
            symbol="BTC-USD",
            side="long",
            status="closed",
            quantity="0.02",
            entry_price="50000",
            exit_price="49000",
            realized_pnl="-20",
            unrealized_pnl="0",
            total_fees="1",
            opened_at=base_time + 86400000 * 2,
            closed_at=base_time + 86400000 * 3,
            entry_order_id="order-3",
            exit_order_id="order-4",
        ),
    ]


@pytest.fixture
def sample_orders():
    """Create sample orders."""
    return [
        Order(
            order_id="order-1",
            symbol="BTC-USD",
            side="buy",
            order_type="market",
            quantity="0.01",
            price="50000",
            status="filled",
            created_at=int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000),
        ),
        Order(
            order_id="order-2",
            symbol="BTC-USD",
            side="sell",
            order_type="market",
            quantity="0.01",
            price="51000",
            status="filled",
            created_at=int(datetime(2024, 1, 2, tzinfo=UTC).timestamp() * 1000),
        ),
    ]


@pytest.fixture
def sample_backtest_result(
    sample_metrics,
    sample_equity_curve,
    sample_drawdown_curve,
    sample_positions,
    sample_orders,
):
    """Create sample BacktestResult."""
    return BacktestResult(
        strategy_name="SMACrossoverStrategy",
        symbol="BTC-USD",
        timeframe="1h",
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 1, 31, tzinfo=UTC),
        initial_balance=Decimal("10000"),
        metrics=sample_metrics,
        equity_curve=sample_equity_curve,
        trades=sample_positions,
        orders=sample_orders,
        drawdown_curve=sample_drawdown_curve,
    )


class TestBacktestResultCreation:
    """Tests for BacktestResult dataclass creation."""

    def test_dataclass_creation(self, sample_backtest_result):
        """Test BacktestResult can be created."""
        assert sample_backtest_result.strategy_name == "SMACrossoverStrategy"
        assert sample_backtest_result.symbol == "BTC-USD"
        assert sample_backtest_result.timeframe == "1h"
        assert sample_backtest_result.initial_balance == Decimal("10000")
        assert len(sample_backtest_result.equity_curve) == 4
        assert len(sample_backtest_result.trades) == 2
        assert len(sample_backtest_result.orders) == 2

    def test_metrics_included(self, sample_backtest_result):
        """Test metrics are properly included."""
        assert sample_backtest_result.metrics.total_return == Decimal("250")
        assert sample_backtest_result.metrics.sharpe_ratio == Decimal("1.5")
        assert sample_backtest_result.metrics.total_trades == 10


class TestToDictSerialization:
    """Tests for to_dict() serialization."""

    def test_to_dict_structure(self, sample_backtest_result):
        """Test to_dict returns proper structure."""
        result_dict = sample_backtest_result.to_dict()

        assert isinstance(result_dict, dict)
        assert "strategy" in result_dict
        assert "symbol" in result_dict
        assert "timeframe" in result_dict
        assert "metrics" in result_dict
        assert "equity_curve" in result_dict
        assert "drawdown_curve" in result_dict

    def test_to_dict_metrics_serialization(self, sample_backtest_result):
        """Test metrics are properly serialized to strings."""
        result_dict = sample_backtest_result.to_dict()
        metrics = result_dict["metrics"]

        assert isinstance(metrics, dict)
        assert metrics["total_return"] == "250"
        assert metrics["sharpe_ratio"] == "1.5"
        assert metrics["win_rate"] == "0.6"
        assert metrics["total_trades"] == 10
        assert metrics["max_drawdown_duration"] == 10

    def test_to_dict_equity_curve_serialization(self, sample_backtest_result):
        """Test equity curve is properly serialized."""
        result_dict = sample_backtest_result.to_dict()
        equity_curve = result_dict["equity_curve"]

        assert isinstance(equity_curve, list)
        assert len(equity_curve) == 4
        assert "timestamp" in equity_curve[0]
        assert "equity" in equity_curve[0]
        assert equity_curve[0]["equity"] == "10000"

    def test_to_dict_drawdown_curve_serialization(self, sample_backtest_result):
        """Test drawdown curve is properly serialized."""
        result_dict = sample_backtest_result.to_dict()
        drawdown_curve = result_dict["drawdown_curve"]

        assert isinstance(drawdown_curve, list)
        assert len(drawdown_curve) == 4
        assert "timestamp" in drawdown_curve[0]
        assert "drawdown" in drawdown_curve[0]

    def test_to_dict_timestamps_are_iso_format(self, sample_backtest_result):
        """Test timestamps are ISO formatted strings."""
        result_dict = sample_backtest_result.to_dict()

        assert isinstance(result_dict["start_time"], str)
        assert isinstance(result_dict["end_time"], str)
        assert "2024-01-01" in result_dict["start_time"]


class TestPrintSummary:
    """Tests for print_summary() method."""

    def test_print_summary_no_error(self, sample_backtest_result, capsys):
        """Test print_summary runs without error."""
        sample_backtest_result.print_summary()

        captured = capsys.readouterr()
        output = captured.out

        assert "Backtest Results" in output
        assert "SMACrossoverStrategy" in output
        assert "BTC-USD" in output
        assert "RETURNS" in output
        assert "RISK METRICS" in output
        assert "TRADE STATISTICS" in output

    def test_print_summary_includes_key_metrics(self, sample_backtest_result, capsys):
        """Test print_summary includes all key metrics."""
        sample_backtest_result.print_summary()

        captured = capsys.readouterr()
        output = captured.out

        # Check for return metrics
        assert "Initial Balance" in output
        assert "Final Balance" in output
        assert "Total Return" in output
        assert "Annualized Return" in output

        # Check for risk metrics
        assert "Sharpe Ratio" in output
        assert "Sortino Ratio" in output
        assert "Max Drawdown" in output

        # Check for trade statistics
        assert "Total Trades" in output
        assert "Win Rate" in output
        assert "Profit Factor" in output

    def test_print_summary_formatting(self, sample_backtest_result, capsys):
        """Test print_summary has proper formatting."""
        sample_backtest_result.print_summary()

        captured = capsys.readouterr()
        output = captured.out

        # Check for section separators
        assert "=" * 70 in output
        assert "-" * 70 in output


class TestPlotEquityCurve:
    """Tests for plot_equity_curve() method."""

    def test_plot_equity_curve_requires_matplotlib(self, sample_backtest_result):
        """Test plot requires matplotlib."""
        # This will only fail if matplotlib is not installed
        # In our CI, matplotlib is installed, so this should pass
        try:
            # Just test that the method exists and can be called
            # We won't actually display the plot
            import matplotlib

            matplotlib.use("Agg")  # Use non-GUI backend
            sample_backtest_result.plot_equity_curve(show_drawdown=False)
            import matplotlib.pyplot as plt

            plt.close("all")  # Clean up
        except ImportError:
            # If matplotlib is not installed, we expect ImportError
            with pytest.raises(ImportError):
                sample_backtest_result.plot_equity_curve()

    def test_plot_equity_curve_with_drawdown(self, sample_backtest_result):
        """Test plot with drawdown overlay."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            sample_backtest_result.plot_equity_curve(show_drawdown=True)
            import matplotlib.pyplot as plt

            plt.close("all")
        except ImportError:
            pytest.skip("matplotlib not installed")

    def test_plot_equity_curve_save_to_file(self, sample_backtest_result, tmp_path):
        """Test saving plot to file."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            save_path = tmp_path / "equity_curve.png"
            sample_backtest_result.plot_equity_curve(save_path=str(save_path))

            assert save_path.exists()
            assert save_path.stat().st_size > 0
        except ImportError:
            pytest.skip("matplotlib not installed")


class TestPlotTradeDistribution:
    """Tests for plot_trade_distribution() method."""

    def test_plot_trade_distribution(self, sample_backtest_result):
        """Test trade distribution plot."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            sample_backtest_result.plot_trade_distribution()
            import matplotlib.pyplot as plt

            plt.close("all")
        except ImportError:
            pytest.skip("matplotlib not installed")

    def test_plot_trade_distribution_save_to_file(self, sample_backtest_result, tmp_path):
        """Test saving trade distribution to file."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            save_path = tmp_path / "trade_dist.png"
            sample_backtest_result.plot_trade_distribution(save_path=str(save_path))

            assert save_path.exists()
            assert save_path.stat().st_size > 0
        except ImportError:
            pytest.skip("matplotlib not installed")

    def test_plot_trade_distribution_no_trades(self, sample_backtest_result):
        """Test plot with no trades."""
        # Create result with no trades
        sample_backtest_result.trades = []

        try:
            import matplotlib

            matplotlib.use("Agg")
            # Should handle gracefully (log warning but not crash)
            sample_backtest_result.plot_trade_distribution()
            import matplotlib.pyplot as plt

            plt.close("all")
        except ImportError:
            pytest.skip("matplotlib not installed")


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_equity_curve(self, sample_metrics, sample_positions, sample_orders):
        """Test result with empty equity curve."""
        result = BacktestResult(
            strategy_name="Test",
            symbol="BTC-USD",
            timeframe="1h",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 31, tzinfo=UTC),
            initial_balance=Decimal("10000"),
            metrics=sample_metrics,
            equity_curve=[],
            trades=sample_positions,
            orders=sample_orders,
            drawdown_curve=[],
        )

        assert len(result.equity_curve) == 0
        # to_dict should still work
        result_dict = result.to_dict()
        assert result_dict["equity_curve"] == []

    def test_empty_trades(
        self, sample_metrics, sample_equity_curve, sample_drawdown_curve, sample_orders
    ):
        """Test result with no trades."""
        result = BacktestResult(
            strategy_name="Test",
            symbol="BTC-USD",
            timeframe="1h",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 1, 31, tzinfo=UTC),
            initial_balance=Decimal("10000"),
            metrics=sample_metrics,
            equity_curve=sample_equity_curve,
            trades=[],
            orders=sample_orders,
            drawdown_curve=sample_drawdown_curve,
        )

        assert len(result.trades) == 0
        result_dict = result.to_dict()
        assert result_dict["total_positions"] == 0
