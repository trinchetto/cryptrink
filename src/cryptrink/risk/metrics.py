"""Risk metrics tracking for monitoring trading performance and risk exposure.

This module implements RiskMetrics dataclass and RiskMetricsTracker for
tracking P&L, drawdown, win rates, and other risk-related metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from cryptrink.execution.models import Position

logger = get_logger(__name__)


class RiskMetricsDict(TypedDict):
    daily_realized_pnl: str
    daily_unrealized_pnl: str
    total_realized_pnl: str
    peak_equity: str
    current_drawdown: str
    max_drawdown: str
    win_count: int
    loss_count: int
    total_trades: int
    total_win_amount: str
    total_loss_amount: str
    circuit_breaker_active: bool
    circuit_breaker_reason: str | None
    circuit_breaker_triggered_at: str | None
    last_reset_at: str
    last_updated_at: str


@dataclass
class RiskMetrics:
    """Risk and performance metrics.

    Tracks daily P&L, drawdown, win rates, and circuit breaker state.
    These metrics are used by RiskValidator to enforce risk limits.
    """

    # P&L Tracking
    daily_realized_pnl: Decimal = Decimal("0")
    daily_unrealized_pnl: Decimal = Decimal("0")
    total_realized_pnl: Decimal = Decimal("0")

    # Drawdown Tracking
    peak_equity: Decimal = Decimal("0")
    current_drawdown: Decimal = Decimal("0")  # As percentage (0.0 - 1.0)
    max_drawdown: Decimal = Decimal("0")  # Historical worst drawdown

    # Win Rate Tracking (for Kelly Criterion)
    win_count: int = 0
    loss_count: int = 0
    total_trades: int = 0
    total_win_amount: Decimal = Decimal("0")
    total_loss_amount: Decimal = Decimal("0")

    # Circuit Breaker State
    circuit_breaker_active: bool = False
    circuit_breaker_reason: str | None = None
    circuit_breaker_triggered_at: datetime | None = None

    # Timestamp Tracking
    last_reset_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def win_rate(self) -> Decimal:
        """Calculate win rate (0.0 - 1.0)."""
        if self.total_trades == 0:
            return Decimal("0")
        return Decimal(self.win_count) / Decimal(self.total_trades)

    @property
    def avg_win(self) -> Decimal:
        """Calculate average winning trade amount."""
        if self.win_count == 0:
            return Decimal("0")
        return self.total_win_amount / Decimal(self.win_count)

    @property
    def avg_loss(self) -> Decimal:
        """Calculate average losing trade amount (positive value)."""
        if self.loss_count == 0:
            return Decimal("0")
        return self.total_loss_amount / Decimal(self.loss_count)


class RiskMetricsTracker:
    """Tracks and updates risk metrics based on trading activity.

    This class maintains a RiskMetrics instance and provides methods to
    update it based on position changes, price movements, and daily resets.
    """

    def __init__(self, initial_balance: Decimal) -> None:
        """Initialize the risk metrics tracker.

        Args:
            initial_balance: Starting account balance for drawdown calculation.
        """
        self._metrics = RiskMetrics(peak_equity=initial_balance)
        self._initial_balance = initial_balance

        logger.info(
            "risk_metrics_tracker_initialized",
            initial_balance=float(initial_balance),
        )

    def update_on_trade_close(
        self,
        position: Position,
        realized_pnl: Decimal,
        current_equity: Decimal,
    ) -> None:
        """Update metrics when a position is closed.

        Args:
            position: The closed position.
            realized_pnl: Realized P&L from closing the position.
            current_equity: Current account equity after the trade.
        """
        # Update P&L
        self._metrics.daily_realized_pnl += realized_pnl
        self._metrics.total_realized_pnl += realized_pnl

        # Update win/loss tracking
        self._metrics.total_trades += 1

        if realized_pnl > 0:
            self._metrics.win_count += 1
            self._metrics.total_win_amount += realized_pnl
        elif realized_pnl < 0:
            self._metrics.loss_count += 1
            self._metrics.total_loss_amount += abs(realized_pnl)

        # Update drawdown
        self._update_drawdown(current_equity)

        self._metrics.last_updated_at = datetime.now(UTC)

        logger.debug(
            "metrics_updated_on_trade_close",
            symbol=position.symbol,
            realized_pnl=float(realized_pnl),
            daily_pnl=float(self._metrics.daily_realized_pnl),
            total_pnl=float(self._metrics.total_realized_pnl),
            win_rate=float(self.win_rate),
            current_drawdown=float(self._metrics.current_drawdown),
        )

    def update_unrealized_pnl(
        self,
        unrealized_pnl: Decimal,
        current_equity: Decimal,
    ) -> None:
        """Update unrealized P&L and recalculate drawdown.

        This should be called periodically (e.g., on each market data update)
        to track unrealized P&L and drawdown including open positions.

        Args:
            unrealized_pnl: Total unrealized P&L from open positions.
            current_equity: Current account equity (balance + unrealized P&L).
        """
        self._metrics.daily_unrealized_pnl = unrealized_pnl

        # Update drawdown including unrealized P&L
        self._update_drawdown(current_equity)

        self._metrics.last_updated_at = datetime.now(UTC)

    def _update_drawdown(self, current_equity: Decimal) -> None:
        """Update peak equity and current drawdown.

        Args:
            current_equity: Current account equity.
        """
        # Update peak equity
        if current_equity > self._metrics.peak_equity:
            self._metrics.peak_equity = current_equity
            self._metrics.current_drawdown = Decimal("0")
        else:
            # Calculate drawdown as percentage
            if self._metrics.peak_equity > 0:
                drawdown_amount = self._metrics.peak_equity - current_equity
                self._metrics.current_drawdown = drawdown_amount / self._metrics.peak_equity

                # Update max drawdown if this is a new worst
                if self._metrics.current_drawdown > self._metrics.max_drawdown:
                    self._metrics.max_drawdown = self._metrics.current_drawdown

    def reset_daily_metrics(self) -> None:
        """Reset daily P&L metrics at midnight UTC.

        This should be called at the start of each trading day to reset
        daily P&L tracking. Total P&L and win/loss stats are preserved.
        """
        logger.info(
            "resetting_daily_metrics",
            previous_daily_pnl=float(self._metrics.daily_realized_pnl),
            previous_unrealized_pnl=float(self._metrics.daily_unrealized_pnl),
        )

        self._metrics.daily_realized_pnl = Decimal("0")
        self._metrics.daily_unrealized_pnl = Decimal("0")
        self._metrics.last_reset_at = datetime.now(UTC)
        self._metrics.last_updated_at = datetime.now(UTC)

        # Clear daily loss circuit breaker if it was active
        if (
            self._metrics.circuit_breaker_active
            and self._metrics.circuit_breaker_reason
            and "Daily loss" in self._metrics.circuit_breaker_reason
        ):
            logger.info(
                "clearing_daily_loss_circuit_breaker",
                reason="Daily reset",
            )
            self._metrics.circuit_breaker_active = False
            self._metrics.circuit_breaker_reason = None
            self._metrics.circuit_breaker_triggered_at = None

    def activate_circuit_breaker(self, reason: str) -> None:
        """Activate circuit breaker with a reason.

        Args:
            reason: Reason for circuit breaker activation.
        """
        if not self._metrics.circuit_breaker_active:
            logger.error(
                "circuit_breaker_activated",
                reason=reason,
            )
            self._metrics.circuit_breaker_active = True
            self._metrics.circuit_breaker_reason = reason
            self._metrics.circuit_breaker_triggered_at = datetime.now(UTC)

    def deactivate_circuit_breaker(self) -> None:
        """Manually deactivate circuit breaker.

        This should only be called after reviewing the reason for activation
        and confirming it's safe to resume trading.
        """
        if self._metrics.circuit_breaker_active:
            logger.warning(
                "circuit_breaker_manually_deactivated",
                previous_reason=self._metrics.circuit_breaker_reason,
            )
            self._metrics.circuit_breaker_active = False
            self._metrics.circuit_breaker_reason = None
            self._metrics.circuit_breaker_triggered_at = None

    @property
    def metrics(self) -> RiskMetrics:
        """Get current risk metrics."""
        return self._metrics

    @property
    def win_rate(self) -> Decimal:
        """Get current win rate."""
        return self._metrics.win_rate

    @property
    def avg_win(self) -> Decimal:
        """Get average winning trade."""
        return self._metrics.avg_win

    @property
    def avg_loss(self) -> Decimal:
        """Get average losing trade."""
        return self._metrics.avg_loss

    def to_dict(self) -> RiskMetricsDict:
        """Convert metrics to dictionary for serialization.

        Returns:
            Dictionary representation of metrics.
        """
        return {
            "daily_realized_pnl": str(self._metrics.daily_realized_pnl),
            "daily_unrealized_pnl": str(self._metrics.daily_unrealized_pnl),
            "total_realized_pnl": str(self._metrics.total_realized_pnl),
            "peak_equity": str(self._metrics.peak_equity),
            "current_drawdown": str(self._metrics.current_drawdown),
            "max_drawdown": str(self._metrics.max_drawdown),
            "win_count": self._metrics.win_count,
            "loss_count": self._metrics.loss_count,
            "total_trades": self._metrics.total_trades,
            "total_win_amount": str(self._metrics.total_win_amount),
            "total_loss_amount": str(self._metrics.total_loss_amount),
            "circuit_breaker_active": self._metrics.circuit_breaker_active,
            "circuit_breaker_reason": self._metrics.circuit_breaker_reason,
            "circuit_breaker_triggered_at": (
                self._metrics.circuit_breaker_triggered_at.isoformat()
                if self._metrics.circuit_breaker_triggered_at
                else None
            ),
            "last_reset_at": self._metrics.last_reset_at.isoformat(),
            "last_updated_at": self._metrics.last_updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: RiskMetricsDict, initial_balance: Decimal) -> RiskMetricsTracker:
        """Create RiskMetricsTracker from dictionary.

        Args:
            data: Dictionary representation of metrics.
            initial_balance: Initial account balance.

        Returns:
            RiskMetricsTracker instance.
        """
        tracker = cls(initial_balance)

        tracker._metrics.daily_realized_pnl = Decimal(data["daily_realized_pnl"])
        tracker._metrics.daily_unrealized_pnl = Decimal(data["daily_unrealized_pnl"])
        tracker._metrics.total_realized_pnl = Decimal(data["total_realized_pnl"])
        tracker._metrics.peak_equity = Decimal(data["peak_equity"])
        tracker._metrics.current_drawdown = Decimal(data["current_drawdown"])
        tracker._metrics.max_drawdown = Decimal(data["max_drawdown"])
        tracker._metrics.win_count = data["win_count"]
        tracker._metrics.loss_count = data["loss_count"]
        tracker._metrics.total_trades = data["total_trades"]
        tracker._metrics.total_win_amount = Decimal(data["total_win_amount"])
        tracker._metrics.total_loss_amount = Decimal(data["total_loss_amount"])
        tracker._metrics.circuit_breaker_active = data["circuit_breaker_active"]
        tracker._metrics.circuit_breaker_reason = data.get("circuit_breaker_reason")

        circuit_breaker_triggered_at = data.get("circuit_breaker_triggered_at")
        if circuit_breaker_triggered_at is not None:
            tracker._metrics.circuit_breaker_triggered_at = datetime.fromisoformat(
                circuit_breaker_triggered_at
            )

        tracker._metrics.last_reset_at = datetime.fromisoformat(data["last_reset_at"])
        tracker._metrics.last_updated_at = datetime.fromisoformat(data["last_updated_at"])

        return tracker

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"RiskMetricsTracker("
            f"daily_pnl={float(self._metrics.daily_realized_pnl):.2f}, "
            f"drawdown={float(self._metrics.current_drawdown) * 100:.2f}%, "
            f"win_rate={float(self.win_rate) * 100:.1f}%, "
            f"circuit_breaker={'ACTIVE' if self._metrics.circuit_breaker_active else 'inactive'}"
            ")"
        )
