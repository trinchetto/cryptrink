"""Unit tests for BacktestMetricsCalculator."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cryptrink.backtest.metrics import BacktestMetrics, BacktestMetricsCalculator
from cryptrink.execution.models import Position


@pytest.fixture
def calculator():
    """Create BacktestMetricsCalculator with default settings."""
    return BacktestMetricsCalculator(risk_free_rate=Decimal("0.02"))


@pytest.fixture
def sample_positions():
    """Create sample closed positions for testing."""
    base_time = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)

    positions = [
        # Winning trade 1: +$100
        Position(
            position_id="pos-1",
            symbol="BTC-USD",
            side="long",
            status="closed",
            quantity="0.01",
            entry_price="50000",
            exit_price="60000",
            realized_pnl="100",
            unrealized_pnl="0",
            total_fees="1",
            opened_at=base_time,
            closed_at=base_time + 86400000,  # +1 day
            entry_order_id="order-1",
            exit_order_id="order-2",
        ),
        # Losing trade 1: -$50
        Position(
            position_id="pos-2",
            symbol="BTC-USD",
            side="long",
            status="closed",
            quantity="0.01",
            entry_price="50000",
            exit_price="45000",
            realized_pnl="-50",
            unrealized_pnl="0",
            total_fees="1",
            opened_at=base_time + 86400000 * 2,
            closed_at=base_time + 86400000 * 3,
            entry_order_id="order-3",
            exit_order_id="order-4",
        ),
        # Winning trade 2: +$200
        Position(
            position_id="pos-3",
            symbol="BTC-USD",
            side="long",
            status="closed",
            quantity="0.02",
            entry_price="50000",
            exit_price="60000",
            realized_pnl="200",
            unrealized_pnl="0",
            total_fees="2",
            opened_at=base_time + 86400000 * 4,
            closed_at=base_time + 86400000 * 5,
            entry_order_id="order-5",
            exit_order_id="order-6",
        ),
    ]
    return positions


@pytest.fixture
def sample_equity_curve():
    """Create sample equity curve for testing."""
    start_time = datetime(2024, 1, 1, tzinfo=UTC)
    initial_balance = Decimal("10000")

    curve = [
        (start_time, initial_balance),  # Day 0: $10,000
        (start_time + timedelta(days=1), Decimal("10100")),  # Day 1: +$100
        (start_time + timedelta(days=2), Decimal("10050")),  # Day 2: -$50
        (start_time + timedelta(days=3), Decimal("10250")),  # Day 3: +$200
    ]
    return curve


class TestBacktestMetricsCalculatorInitialization:
    """Tests for calculator initialization."""

    def test_initialization_with_default(self):
        """Test initialization with default risk-free rate."""
        calculator = BacktestMetricsCalculator()
        assert calculator is not None

    def test_initialization_with_custom_rate(self):
        """Test initialization with custom risk-free rate."""
        calculator = BacktestMetricsCalculator(risk_free_rate=Decimal("0.03"))
        assert calculator._risk_free_rate == Decimal("0.03")


class TestReturnsCalculation:
    """Tests for returns calculation."""

    def test_total_return_positive(self, calculator, sample_positions, sample_equity_curve):
        """Test total return calculation with profit."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=sample_positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10250"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=sample_equity_curve,
        )

        assert metrics.total_return == Decimal("250")  # $10,250 - $10,000
        assert metrics.total_return_pct == Decimal("0.025")  # 2.5%

    def test_total_return_negative(self, calculator):
        """Test total return calculation with loss."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=[],
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("9500"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=[(start_time, Decimal("10000")), (end_time, Decimal("9500"))],
        )

        assert metrics.total_return == Decimal("-500")
        assert metrics.total_return_pct == Decimal("-0.05")  # -5%


class TestTradeStatistics:
    """Tests for trade statistics calculation."""

    def test_trade_counts(self, calculator, sample_positions, sample_equity_curve):
        """Test trade count calculations."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=sample_positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10250"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=sample_equity_curve,
        )

        assert metrics.total_trades == 3
        assert metrics.winning_trades == 2
        assert metrics.losing_trades == 1

    def test_win_rate(self, calculator, sample_positions, sample_equity_curve):
        """Test win rate calculation."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=sample_positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10250"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=sample_equity_curve,
        )

        # 2 wins / 3 trades = 0.6666...
        assert abs(metrics.win_rate - Decimal("0.666666666666666666666666666")) < Decimal("0.001")

    def test_profit_factor(self, calculator, sample_positions, sample_equity_curve):
        """Test profit factor calculation."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=sample_positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10250"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=sample_equity_curve,
        )

        # Gross profit = 100 + 200 = 300
        # Gross loss = 50
        # Profit factor = 300 / 50 = 6
        assert metrics.profit_factor == Decimal("6")

    def test_average_trades(self, calculator, sample_positions, sample_equity_curve):
        """Test average trade calculations."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=sample_positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10250"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=sample_equity_curve,
        )

        # Avg win = (100 + 200) / 2 = 150
        assert metrics.avg_win == Decimal("150")
        # Avg loss = 50 / 1 = 50
        assert metrics.avg_loss == Decimal("50")
        # Avg trade = (100 - 50 + 200) / 3 = 83.333...
        assert abs(metrics.avg_trade - Decimal("83.333333333333333333333333333")) < Decimal("0.001")

    def test_best_worst_trades(self, calculator, sample_positions, sample_equity_curve):
        """Test best and worst trade identification."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=sample_positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10250"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=sample_equity_curve,
        )

        assert metrics.best_trade == Decimal("200")
        assert metrics.worst_trade == Decimal("-50")


class TestStreakCalculation:
    """Tests for win/loss streak calculation."""

    def test_win_streak(self, calculator, sample_equity_curve):
        """Test maximum win streak calculation."""
        # Create 3 consecutive winning positions
        base_time = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
        positions = [
            Position(
                position_id=f"pos-{i}",
                symbol="BTC-USD",
                side="long",
                status="closed",
                quantity="0.01",
                entry_price="50000",
                exit_price="51000",
                realized_pnl="10",
                unrealized_pnl="0",
                total_fees="1",
                opened_at=base_time + i * 86400000,
                closed_at=base_time + (i + 1) * 86400000,
                entry_order_id=f"order-{i * 2}",
                exit_order_id=f"order-{i * 2 + 1}",
            )
            for i in range(3)
        ]

        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10030"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=sample_equity_curve,
        )

        assert metrics.max_win_streak == 3
        assert metrics.current_streak == 3


class TestDrawdownCalculation:
    """Tests for drawdown calculation."""

    def test_max_drawdown(self, calculator, sample_positions):
        """Test maximum drawdown calculation."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        # Create equity curve with drawdown
        equity_curve = [
            (start_time, Decimal("10000")),  # Peak
            (start_time + timedelta(days=1), Decimal("9500")),  # -5%
            (start_time + timedelta(days=2), Decimal("9000")),  # -10% (max DD)
            (start_time + timedelta(days=3), Decimal("9500")),  # Recovery
            (start_time + timedelta(days=4), Decimal("10500")),  # New peak
        ]

        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=sample_positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10500"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=equity_curve,
        )

        # Max drawdown = (10000 - 9000) / 10000 = 0.1 (10%)
        assert metrics.max_drawdown == Decimal("0.1")

    def test_drawdown_duration(self, calculator, sample_positions):
        """Test drawdown duration calculation."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        # Create equity curve with extended drawdown
        equity_curve = [
            (start_time, Decimal("10000")),  # Peak at day 0
            (start_time + timedelta(days=1), Decimal("9500")),  # Day 1
            (start_time + timedelta(days=2), Decimal("9000")),  # Day 2
            (start_time + timedelta(days=3), Decimal("9200")),  # Day 3
            (start_time + timedelta(days=4), Decimal("9500")),  # Day 4
            (start_time + timedelta(days=5), Decimal("10100")),  # Day 5: new peak
        ]

        end_time = datetime(2024, 1, 31, tzinfo=UTC)

        metrics = calculator.calculate(
            positions=sample_positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10100"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=equity_curve,
        )

        # Drawdown lasted from day 0 to day 5 (when new peak reached)
        # Max duration during drawdown was 5 days
        assert metrics.max_drawdown_duration >= 2


class TestEdgeCases:
    """Tests for edge cases."""

    def test_no_positions(self, calculator):
        """Test metrics with no positions."""
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)
        equity_curve = [(start_time, Decimal("10000")), (end_time, Decimal("10000"))]

        metrics = calculator.calculate(
            positions=[],
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10000"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=equity_curve,
        )

        assert metrics.total_trades == 0
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 0
        assert metrics.win_rate == Decimal("0")
        assert metrics.total_return == Decimal("0")

    def test_all_winning_positions(self, calculator):
        """Test metrics with all winning trades."""
        base_time = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
        positions = [
            Position(
                position_id=f"pos-{i}",
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
                entry_order_id=f"order-{i * 2}",
                exit_order_id=f"order-{i * 2 + 1}",
            )
            for i in range(3)
        ]

        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)
        # Create equity curve with only positive returns
        equity_curve = [
            (start_time, Decimal("10000")),
            (start_time + timedelta(days=1), Decimal("10010")),
            (start_time + timedelta(days=2), Decimal("10020")),
            (end_time, Decimal("10030")),
        ]

        metrics = calculator.calculate(
            positions=positions,
            orders=[],
            initial_balance=Decimal("10000"),
            final_balance=Decimal("10030"),
            start_time=start_time,
            end_time=end_time,
            equity_curve=equity_curve,
        )

        assert metrics.win_rate == Decimal("1")  # 100%
        assert metrics.losing_trades == 0
        # Sortino should be very high (no negative returns)
        assert metrics.sortino_ratio == Decimal("999")


class TestBacktestMetricsDataclass:
    """Tests for BacktestMetrics dataclass."""

    def test_dataclass_creation(self):
        """Test BacktestMetrics dataclass can be created."""
        metrics = BacktestMetrics(
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

        assert metrics.total_return == Decimal("250")
        assert metrics.win_rate == Decimal("0.6")
        assert metrics.sharpe_ratio == Decimal("1.5")
