"""Unit tests for RiskMetrics and RiskMetricsTracker."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptrink.execution.models import Position
from cryptrink.risk.metrics import RiskMetrics, RiskMetricsTracker


@pytest.fixture
def initial_balance():
    """Initial account balance for tests."""
    return Decimal("10000")


@pytest.fixture
def tracker(initial_balance):
    """Create RiskMetricsTracker with initial balance."""
    return RiskMetricsTracker(initial_balance)


@pytest.fixture
def sample_position():
    """Create sample position for testing."""
    position = Position(
        position_id="test-pos-1",
        symbol="BTC-USD",
        side="long",
        status="open",
        quantity="0.1",
        entry_price="50000",
        realized_pnl="0",
        unrealized_pnl="100",
        total_fees="0",
        opened_at=int(datetime.now(UTC).timestamp() * 1000),
        entry_order_id="order-1",
    )
    return position


class TestRiskMetricsDataclass:
    """Tests for RiskMetrics dataclass."""

    def test_initialization_defaults(self):
        """Test RiskMetrics initializes with correct defaults."""
        metrics = RiskMetrics()

        assert metrics.daily_realized_pnl == Decimal("0")
        assert metrics.daily_unrealized_pnl == Decimal("0")
        assert metrics.total_realized_pnl == Decimal("0")
        assert metrics.peak_equity == Decimal("0")
        assert metrics.current_drawdown == Decimal("0")
        assert metrics.max_drawdown == Decimal("0")
        assert metrics.win_count == 0
        assert metrics.loss_count == 0
        assert metrics.total_trades == 0
        assert metrics.total_win_amount == Decimal("0")
        assert metrics.total_loss_amount == Decimal("0")
        assert metrics.circuit_breaker_active is False
        assert metrics.circuit_breaker_reason is None
        assert metrics.circuit_breaker_triggered_at is None

    def test_win_rate_with_no_trades(self):
        """Test win rate returns 0 when no trades."""
        metrics = RiskMetrics()

        assert metrics.win_rate == Decimal("0")

    def test_win_rate_calculation(self):
        """Test win rate calculation with trades."""
        metrics = RiskMetrics(
            win_count=7,
            loss_count=3,
            total_trades=10,
        )

        assert metrics.win_rate == Decimal("0.7")

    def test_win_rate_all_wins(self):
        """Test win rate with all winning trades."""
        metrics = RiskMetrics(
            win_count=10,
            loss_count=0,
            total_trades=10,
        )

        assert metrics.win_rate == Decimal("1.0")

    def test_win_rate_all_losses(self):
        """Test win rate with all losing trades."""
        metrics = RiskMetrics(
            win_count=0,
            loss_count=10,
            total_trades=10,
        )

        assert metrics.win_rate == Decimal("0")

    def test_avg_win_with_no_wins(self):
        """Test average win returns 0 when no wins."""
        metrics = RiskMetrics()

        assert metrics.avg_win == Decimal("0")

    def test_avg_win_calculation(self):
        """Test average win calculation."""
        metrics = RiskMetrics(
            win_count=5,
            total_win_amount=Decimal("1000"),
        )

        assert metrics.avg_win == Decimal("200")

    def test_avg_loss_with_no_losses(self):
        """Test average loss returns 0 when no losses."""
        metrics = RiskMetrics()

        assert metrics.avg_loss == Decimal("0")

    def test_avg_loss_calculation(self):
        """Test average loss calculation."""
        metrics = RiskMetrics(
            loss_count=4,
            total_loss_amount=Decimal("800"),
        )

        assert metrics.avg_loss == Decimal("200")


class TestRiskMetricsTrackerInitialization:
    """Tests for RiskMetricsTracker initialization."""

    def test_initialization(self, initial_balance):
        """Test tracker initializes with correct state."""
        tracker = RiskMetricsTracker(initial_balance)

        assert tracker.metrics.peak_equity == initial_balance
        assert tracker.metrics.daily_realized_pnl == Decimal("0")
        assert tracker.metrics.current_drawdown == Decimal("0")

    def test_initial_win_rate(self, tracker):
        """Test initial win rate is 0."""
        assert tracker.win_rate == Decimal("0")

    def test_initial_avg_win(self, tracker):
        """Test initial avg win is 0."""
        assert tracker.avg_win == Decimal("0")

    def test_initial_avg_loss(self, tracker):
        """Test initial avg loss is 0."""
        assert tracker.avg_loss == Decimal("0")

    def test_repr(self, tracker):
        """Test string representation."""
        repr_str = repr(tracker)

        assert "RiskMetricsTracker" in repr_str
        assert "daily_pnl" in repr_str
        assert "drawdown" in repr_str
        assert "win_rate" in repr_str
        assert "circuit_breaker" in repr_str


class TestTradeCloseUpdates:
    """Tests for update_on_trade_close method."""

    def test_winning_trade_updates_metrics(self, tracker, sample_position):
        """Test winning trade updates all relevant metrics."""
        realized_pnl = Decimal("500")
        current_equity = Decimal("10500")

        tracker.update_on_trade_close(sample_position, realized_pnl, current_equity)

        assert tracker.metrics.daily_realized_pnl == realized_pnl
        assert tracker.metrics.total_realized_pnl == realized_pnl
        assert tracker.metrics.total_trades == 1
        assert tracker.metrics.win_count == 1
        assert tracker.metrics.loss_count == 0
        assert tracker.metrics.total_win_amount == realized_pnl
        assert tracker.metrics.total_loss_amount == Decimal("0")

    def test_losing_trade_updates_metrics(self, tracker, sample_position):
        """Test losing trade updates all relevant metrics."""
        realized_pnl = Decimal("-300")
        current_equity = Decimal("9700")

        tracker.update_on_trade_close(sample_position, realized_pnl, current_equity)

        assert tracker.metrics.daily_realized_pnl == realized_pnl
        assert tracker.metrics.total_realized_pnl == realized_pnl
        assert tracker.metrics.total_trades == 1
        assert tracker.metrics.win_count == 0
        assert tracker.metrics.loss_count == 1
        assert tracker.metrics.total_win_amount == Decimal("0")
        assert tracker.metrics.total_loss_amount == Decimal("300")  # Absolute value

    def test_breakeven_trade(self, tracker, sample_position):
        """Test breakeven trade (zero P&L) is not counted as win or loss."""
        realized_pnl = Decimal("0")
        current_equity = Decimal("10000")

        tracker.update_on_trade_close(sample_position, realized_pnl, current_equity)

        assert tracker.metrics.total_trades == 1
        assert tracker.metrics.win_count == 0
        assert tracker.metrics.loss_count == 0

    def test_multiple_trades_update_correctly(self, tracker, sample_position):
        """Test multiple trades update metrics correctly."""
        # First trade: Win $500
        tracker.update_on_trade_close(sample_position, Decimal("500"), Decimal("10500"))

        # Second trade: Loss $200
        tracker.update_on_trade_close(sample_position, Decimal("-200"), Decimal("10300"))

        # Third trade: Win $300
        tracker.update_on_trade_close(sample_position, Decimal("300"), Decimal("10600"))

        assert tracker.metrics.total_trades == 3
        assert tracker.metrics.win_count == 2
        assert tracker.metrics.loss_count == 1
        assert tracker.metrics.daily_realized_pnl == Decimal("600")  # 500 - 200 + 300
        assert tracker.metrics.total_realized_pnl == Decimal("600")
        assert tracker.metrics.total_win_amount == Decimal("800")  # 500 + 300
        assert tracker.metrics.total_loss_amount == Decimal("200")

    def test_win_rate_after_trades(self, tracker, sample_position):
        """Test win rate calculation after multiple trades."""
        # 3 wins, 2 losses
        tracker.update_on_trade_close(sample_position, Decimal("100"), Decimal("10100"))
        tracker.update_on_trade_close(sample_position, Decimal("-50"), Decimal("10050"))
        tracker.update_on_trade_close(sample_position, Decimal("200"), Decimal("10250"))
        tracker.update_on_trade_close(sample_position, Decimal("-30"), Decimal("10220"))
        tracker.update_on_trade_close(sample_position, Decimal("150"), Decimal("10370"))

        assert tracker.win_rate == Decimal("0.6")  # 3/5

    def test_avg_win_after_trades(self, tracker, sample_position):
        """Test average win calculation after multiple trades."""
        tracker.update_on_trade_close(sample_position, Decimal("100"), Decimal("10100"))
        tracker.update_on_trade_close(sample_position, Decimal("200"), Decimal("10300"))
        tracker.update_on_trade_close(sample_position, Decimal("-50"), Decimal("10250"))

        assert tracker.avg_win == Decimal("150")  # (100 + 200) / 2

    def test_avg_loss_after_trades(self, tracker, sample_position):
        """Test average loss calculation after multiple trades."""
        tracker.update_on_trade_close(sample_position, Decimal("-100"), Decimal("9900"))
        tracker.update_on_trade_close(sample_position, Decimal("200"), Decimal("10100"))
        tracker.update_on_trade_close(sample_position, Decimal("-50"), Decimal("10050"))

        assert tracker.avg_loss == Decimal("75")  # (100 + 50) / 2


class TestDrawdownTracking:
    """Tests for drawdown calculation and tracking."""

    def test_peak_equity_updates_on_new_high(self, tracker, sample_position):
        """Test peak equity updates when equity reaches new high."""
        tracker.update_on_trade_close(sample_position, Decimal("500"), Decimal("10500"))

        assert tracker.metrics.peak_equity == Decimal("10500")
        assert tracker.metrics.current_drawdown == Decimal("0")

    def test_drawdown_calculation_after_loss(self, tracker, sample_position):
        """Test drawdown calculation after losing trade."""
        # Start at $10,000 peak
        # Lose $2,000 -> $8,000 equity
        current_equity = Decimal("8000")
        tracker.update_on_trade_close(sample_position, Decimal("-2000"), current_equity)

        # Drawdown = (10000 - 8000) / 10000 = 0.2 (20%)
        assert tracker.metrics.current_drawdown == Decimal("0.2")

    def test_drawdown_resets_on_new_peak(self, tracker, sample_position):
        """Test drawdown resets to 0 when reaching new peak."""
        # First: Lose money, create drawdown
        tracker.update_on_trade_close(sample_position, Decimal("-1000"), Decimal("9000"))
        assert tracker.metrics.current_drawdown == Decimal("0.1")

        # Then: Make money, reach new peak
        tracker.update_on_trade_close(sample_position, Decimal("2000"), Decimal("11000"))
        assert tracker.metrics.peak_equity == Decimal("11000")
        assert tracker.metrics.current_drawdown == Decimal("0")

    def test_max_drawdown_tracking(self, tracker, sample_position):
        """Test max drawdown tracks historical worst."""
        # First drawdown: 10% loss
        tracker.update_on_trade_close(sample_position, Decimal("-1000"), Decimal("9000"))
        assert tracker.metrics.current_drawdown == Decimal("0.1")
        assert tracker.metrics.max_drawdown == Decimal("0.1")

        # Recover slightly
        tracker.update_on_trade_close(sample_position, Decimal("500"), Decimal("9500"))
        assert tracker.metrics.current_drawdown == Decimal("0.05")
        assert tracker.metrics.max_drawdown == Decimal("0.1")  # Historical worst preserved

        # Worse drawdown: 20% from original peak
        tracker.update_on_trade_close(sample_position, Decimal("-1500"), Decimal("8000"))
        assert tracker.metrics.current_drawdown == Decimal("0.2")
        assert tracker.metrics.max_drawdown == Decimal("0.2")  # New worst

    def test_unrealized_pnl_affects_drawdown(self, tracker):
        """Test unrealized P&L is included in drawdown calculation."""
        # Unrealized loss of $1,500
        unrealized_pnl = Decimal("-1500")
        current_equity = Decimal("8500")  # Balance + unrealized

        tracker.update_unrealized_pnl(unrealized_pnl, current_equity)

        # Drawdown = (10000 - 8500) / 10000 = 0.15 (15%)
        assert tracker.metrics.current_drawdown == Decimal("0.15")
        assert tracker.metrics.daily_unrealized_pnl == unrealized_pnl


class TestUnrealizedPnLUpdates:
    """Tests for update_unrealized_pnl method."""

    def test_positive_unrealized_pnl(self, tracker):
        """Test positive unrealized P&L update."""
        unrealized_pnl = Decimal("500")
        current_equity = Decimal("10500")

        tracker.update_unrealized_pnl(unrealized_pnl, current_equity)

        assert tracker.metrics.daily_unrealized_pnl == unrealized_pnl
        assert tracker.metrics.peak_equity == Decimal("10500")
        assert tracker.metrics.current_drawdown == Decimal("0")

    def test_negative_unrealized_pnl(self, tracker):
        """Test negative unrealized P&L creates drawdown."""
        unrealized_pnl = Decimal("-800")
        current_equity = Decimal("9200")

        tracker.update_unrealized_pnl(unrealized_pnl, current_equity)

        assert tracker.metrics.daily_unrealized_pnl == unrealized_pnl
        assert tracker.metrics.current_drawdown == Decimal("0.08")

    def test_unrealized_pnl_changes_over_time(self, tracker):
        """Test unrealized P&L updates correctly over time."""
        # First update: +$500
        tracker.update_unrealized_pnl(Decimal("500"), Decimal("10500"))
        assert tracker.metrics.daily_unrealized_pnl == Decimal("500")

        # Second update: +$300 (replaces previous, not adds)
        tracker.update_unrealized_pnl(Decimal("300"), Decimal("10300"))
        assert tracker.metrics.daily_unrealized_pnl == Decimal("300")

        # Third update: -$200
        tracker.update_unrealized_pnl(Decimal("-200"), Decimal("9800"))
        assert tracker.metrics.daily_unrealized_pnl == Decimal("-200")


class TestDailyMetricsReset:
    """Tests for reset_daily_metrics method."""

    def test_reset_clears_daily_pnl(self, tracker, sample_position):
        """Test reset clears daily realized and unrealized P&L."""
        # Build up some daily P&L
        tracker.update_on_trade_close(sample_position, Decimal("500"), Decimal("10500"))
        tracker.update_unrealized_pnl(Decimal("200"), Decimal("10700"))

        assert tracker.metrics.daily_realized_pnl == Decimal("500")
        assert tracker.metrics.daily_unrealized_pnl == Decimal("200")

        # Reset
        tracker.reset_daily_metrics()

        assert tracker.metrics.daily_realized_pnl == Decimal("0")
        assert tracker.metrics.daily_unrealized_pnl == Decimal("0")

    def test_reset_preserves_total_pnl(self, tracker, sample_position):
        """Test reset preserves total realized P&L."""
        tracker.update_on_trade_close(sample_position, Decimal("500"), Decimal("10500"))

        total_pnl_before = tracker.metrics.total_realized_pnl

        tracker.reset_daily_metrics()

        assert tracker.metrics.total_realized_pnl == total_pnl_before

    def test_reset_preserves_win_loss_stats(self, tracker, sample_position):
        """Test reset preserves win/loss statistics."""
        tracker.update_on_trade_close(sample_position, Decimal("500"), Decimal("10500"))
        tracker.update_on_trade_close(sample_position, Decimal("-200"), Decimal("10300"))

        win_count_before = tracker.metrics.win_count
        loss_count_before = tracker.metrics.loss_count
        total_trades_before = tracker.metrics.total_trades

        tracker.reset_daily_metrics()

        assert tracker.metrics.win_count == win_count_before
        assert tracker.metrics.loss_count == loss_count_before
        assert tracker.metrics.total_trades == total_trades_before

    def test_reset_preserves_drawdown(self, tracker, sample_position):
        """Test reset preserves current and max drawdown."""
        tracker.update_on_trade_close(sample_position, Decimal("-1000"), Decimal("9000"))

        drawdown_before = tracker.metrics.current_drawdown
        max_drawdown_before = tracker.metrics.max_drawdown

        tracker.reset_daily_metrics()

        assert tracker.metrics.current_drawdown == drawdown_before
        assert tracker.metrics.max_drawdown == max_drawdown_before

    def test_reset_clears_daily_loss_circuit_breaker(self, tracker):
        """Test reset clears daily loss circuit breaker."""
        # Activate circuit breaker with daily loss reason
        tracker.activate_circuit_breaker("Daily loss limit (5%) exceeded")

        assert tracker.metrics.circuit_breaker_active is True

        # Reset should clear it
        tracker.reset_daily_metrics()

        assert tracker.metrics.circuit_breaker_active is False
        assert tracker.metrics.circuit_breaker_reason is None

    def test_reset_preserves_drawdown_circuit_breaker(self, tracker):
        """Test reset does NOT clear drawdown circuit breaker."""
        # Activate circuit breaker with drawdown reason
        tracker.activate_circuit_breaker("Maximum drawdown (15.00%) exceeded")

        assert tracker.metrics.circuit_breaker_active is True

        # Reset should NOT clear drawdown circuit breaker
        tracker.reset_daily_metrics()

        assert tracker.metrics.circuit_breaker_active is True
        assert "drawdown" in tracker.metrics.circuit_breaker_reason.lower()


class TestCircuitBreakerManagement:
    """Tests for circuit breaker activation and deactivation."""

    def test_activate_circuit_breaker(self, tracker):
        """Test circuit breaker activation."""
        reason = "Daily loss limit exceeded"

        tracker.activate_circuit_breaker(reason)

        assert tracker.metrics.circuit_breaker_active is True
        assert tracker.metrics.circuit_breaker_reason == reason
        assert tracker.metrics.circuit_breaker_triggered_at is not None

    def test_activate_circuit_breaker_only_once(self, tracker):
        """Test circuit breaker doesn't reactivate if already active."""
        tracker.activate_circuit_breaker("First reason")
        first_timestamp = tracker.metrics.circuit_breaker_triggered_at

        # Try to activate again
        tracker.activate_circuit_breaker("Second reason")

        # Should keep first activation
        assert tracker.metrics.circuit_breaker_reason == "First reason"
        assert tracker.metrics.circuit_breaker_triggered_at == first_timestamp

    def test_deactivate_circuit_breaker(self, tracker):
        """Test manual circuit breaker deactivation."""
        tracker.activate_circuit_breaker("Test reason")
        assert tracker.metrics.circuit_breaker_active is True

        tracker.deactivate_circuit_breaker()

        assert tracker.metrics.circuit_breaker_active is False
        assert tracker.metrics.circuit_breaker_reason is None
        assert tracker.metrics.circuit_breaker_triggered_at is None

    def test_deactivate_when_not_active(self, tracker):
        """Test deactivating circuit breaker when not active."""
        # Should not raise error
        tracker.deactivate_circuit_breaker()

        assert tracker.metrics.circuit_breaker_active is False


class TestSerialization:
    """Tests for to_dict and from_dict serialization."""

    def test_to_dict_with_clean_state(self, tracker):
        """Test serialization of clean tracker state."""
        data = tracker.to_dict()

        assert data["daily_realized_pnl"] == "0"
        assert data["daily_unrealized_pnl"] == "0"
        assert data["total_realized_pnl"] == "0"
        assert data["peak_equity"] == "10000"
        assert data["current_drawdown"] == "0"
        assert data["max_drawdown"] == "0"
        assert data["win_count"] == 0
        assert data["loss_count"] == 0
        assert data["total_trades"] == 0
        assert data["circuit_breaker_active"] is False
        assert data["circuit_breaker_reason"] is None
        assert data["circuit_breaker_triggered_at"] is None
        assert "last_reset_at" in data
        assert "last_updated_at" in data

    def test_to_dict_with_active_state(self, tracker, sample_position):
        """Test serialization of tracker with active trades."""
        tracker.update_on_trade_close(sample_position, Decimal("500"), Decimal("10500"))
        tracker.activate_circuit_breaker("Test reason")

        data = tracker.to_dict()

        assert data["daily_realized_pnl"] == "500"
        assert data["total_realized_pnl"] == "500"
        assert data["peak_equity"] == "10500"
        assert data["win_count"] == 1
        assert data["total_trades"] == 1
        assert data["circuit_breaker_active"] is True
        assert data["circuit_breaker_reason"] == "Test reason"
        assert data["circuit_breaker_triggered_at"] is not None

    def test_from_dict_restores_state(self, initial_balance):
        """Test deserialization restores tracker state."""
        # Create original tracker with some state
        original = RiskMetricsTracker(initial_balance)
        original.metrics.daily_realized_pnl = Decimal("300")
        original.metrics.total_realized_pnl = Decimal("1500")
        original.metrics.peak_equity = Decimal("11000")
        original.metrics.current_drawdown = Decimal("0.05")
        original.metrics.max_drawdown = Decimal("0.15")
        original.metrics.win_count = 7
        original.metrics.loss_count = 3
        original.metrics.total_trades = 10
        original.metrics.total_win_amount = Decimal("2000")
        original.metrics.total_loss_amount = Decimal("500")
        original.activate_circuit_breaker("Test")

        # Serialize and deserialize
        data = original.to_dict()
        restored = RiskMetricsTracker.from_dict(data, initial_balance)

        # Verify all state restored
        assert restored.metrics.daily_realized_pnl == Decimal("300")
        assert restored.metrics.total_realized_pnl == Decimal("1500")
        assert restored.metrics.peak_equity == Decimal("11000")
        assert restored.metrics.current_drawdown == Decimal("0.05")
        assert restored.metrics.max_drawdown == Decimal("0.15")
        assert restored.metrics.win_count == 7
        assert restored.metrics.loss_count == 3
        assert restored.metrics.total_trades == 10
        assert restored.metrics.circuit_breaker_active is True
        assert restored.metrics.circuit_breaker_reason == "Test"
        assert restored.win_rate == Decimal("0.7")

    def test_round_trip_serialization(self, tracker, sample_position):
        """Test serialization round trip preserves all data."""
        # Build up complex state
        tracker.update_on_trade_close(sample_position, Decimal("500"), Decimal("10500"))
        tracker.update_on_trade_close(sample_position, Decimal("-200"), Decimal("10300"))
        tracker.update_unrealized_pnl(Decimal("150"), Decimal("10450"))
        tracker.activate_circuit_breaker("Daily loss")

        # Round trip
        data = tracker.to_dict()
        restored = RiskMetricsTracker.from_dict(data, Decimal("10000"))

        # Compare all fields
        assert restored.metrics.daily_realized_pnl == tracker.metrics.daily_realized_pnl
        assert restored.metrics.daily_unrealized_pnl == tracker.metrics.daily_unrealized_pnl
        assert restored.metrics.total_realized_pnl == tracker.metrics.total_realized_pnl
        assert restored.metrics.peak_equity == tracker.metrics.peak_equity
        assert restored.metrics.current_drawdown == tracker.metrics.current_drawdown
        assert restored.metrics.win_count == tracker.metrics.win_count
        assert restored.metrics.loss_count == tracker.metrics.loss_count
        assert restored.win_rate == tracker.win_rate
        assert restored.avg_win == tracker.avg_win
        assert restored.avg_loss == tracker.avg_loss
