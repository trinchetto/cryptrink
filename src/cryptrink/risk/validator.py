"""Risk validation framework for enforcing risk rules.

This module implements the RiskValidator class which enforces all risk
management rules including position size limits, open position counts,
daily loss limits, and maximum drawdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from cryptrink.core.config import RiskSettings
from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from cryptrink.execution.base import ExecutionContext, OrderSide
    from cryptrink.risk.metrics import RiskMetrics
    from cryptrink.strategies.base import Signal

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of risk validation.

    Attributes:
        valid: Whether the order passes all risk checks.
        reason: Human-readable reason for rejection (empty if valid).
        circuit_breaker_triggered: Whether this validation triggered a circuit breaker.
        circuit_breaker_reason: Reason for circuit breaker activation (if applicable).
    """

    valid: bool
    reason: str = ""
    circuit_breaker_triggered: bool = False
    circuit_breaker_reason: str | None = None


class RiskValidator:
    """Validates orders against risk management rules.

    This class enforces all risk limits including:
    - Maximum position size per trade
    - Maximum number of open positions
    - Daily loss limits (circuit breaker)
    - Maximum drawdown limits (circuit breaker)
    """

    def __init__(self, risk_settings: RiskSettings | None = None) -> None:
        """Initialize the risk validator.

        Args:
            risk_settings: Risk management settings. Uses defaults if not provided.
        """
        self._settings = risk_settings or RiskSettings()

        logger.info(
            "risk_validator_initialized",
            max_position_size_pct=self._settings.max_position_size_pct,
            max_daily_loss_pct=self._settings.max_daily_loss_pct,
            max_drawdown_pct=self._settings.max_drawdown_pct,
        )

    def validate_order(
        self,
        signal: Signal,
        quantity: Decimal,
        context: ExecutionContext,
        order_side: OrderSide,
        metrics: RiskMetrics,
        open_positions_count: int = 0,
    ) -> ValidationResult:
        """Validate order against all risk rules.

        Args:
            signal: Trading signal.
            quantity: Order quantity.
            context: Execution context with balance and position info.
            order_side: Order side (BUY or SELL).
            metrics: Current risk metrics.
            open_positions_count: Number of currently open positions.

        Returns:
            ValidationResult with validation outcome.
        """
        from cryptrink.execution.base import OrderSide

        # Skip validation for sell orders (closing positions)
        if order_side == OrderSide.SELL:
            return ValidationResult(valid=True)

        # 1. Position size validation
        position_size_check = self._validate_position_size(quantity, context)
        if not position_size_check.valid:
            return position_size_check

        # 2. Open position count validation
        position_count_check = self._validate_open_positions(open_positions_count)
        if not position_count_check.valid:
            return position_count_check

        # 3. Daily loss limit (circuit breaker)
        daily_loss_check = self._validate_daily_loss(metrics, context)
        if not daily_loss_check.valid:
            return daily_loss_check

        # 4. Maximum drawdown (circuit breaker)
        drawdown_check = self._validate_drawdown(metrics)
        if not drawdown_check.valid:
            return drawdown_check

        # All checks passed
        return ValidationResult(valid=True)

    def _validate_position_size(
        self,
        quantity: Decimal,
        context: ExecutionContext,
    ) -> ValidationResult:
        """Validate that position size doesn't exceed maximum.

        Args:
            quantity: Order quantity.
            context: Execution context with price and balance info.

        Returns:
            ValidationResult.
        """
        # Calculate position value
        position_value = quantity * context.current_price

        # Calculate maximum allowed position size
        max_position_value = context.account_balance * Decimal(
            str(self._settings.max_position_size_pct)
        )

        if position_value > max_position_value:
            reason = (
                f"Position size ({position_value:.2f}) exceeds maximum "
                f"({max_position_value:.2f}, {self._settings.max_position_size_pct * 100}% of balance)"
            )
            logger.warning(
                "position_size_limit_exceeded",
                position_value=float(position_value),
                max_position_value=float(max_position_value),
                symbol=context.symbol,
            )
            return ValidationResult(valid=False, reason=reason)

        return ValidationResult(valid=True)

    def _validate_open_positions(
        self,
        open_positions_count: int,
    ) -> ValidationResult:
        """Validate that open position count doesn't exceed maximum.

        Args:
            open_positions_count: Number of currently open positions.

        Returns:
            ValidationResult.
        """
        max_open_positions = self._settings.max_open_positions

        if open_positions_count >= max_open_positions:
            reason = (
                f"Open positions ({open_positions_count}) at or above "
                f"maximum ({max_open_positions})"
            )
            logger.warning(
                "max_open_positions_reached",
                open_positions=open_positions_count,
                max_open_positions=max_open_positions,
            )
            return ValidationResult(valid=False, reason=reason)

        return ValidationResult(valid=True)

    def _validate_daily_loss(
        self,
        metrics: RiskMetrics,
        context: ExecutionContext,
    ) -> ValidationResult:
        """Validate that daily loss hasn't exceeded limit.

        This is a circuit breaker - triggers trading pause.

        Args:
            metrics: Current risk metrics.
            context: Execution context with balance info.

        Returns:
            ValidationResult with circuit_breaker_triggered if limit hit.
        """
        # Calculate maximum allowed daily loss
        max_daily_loss = context.account_balance * Decimal(str(self._settings.max_daily_loss_pct))

        # Check if daily realized P&L exceeds loss limit (negative = loss)
        if metrics.daily_realized_pnl < -max_daily_loss:
            reason = (
                f"Daily loss limit exceeded: "
                f"{metrics.daily_realized_pnl:.2f} < -{max_daily_loss:.2f} "
                f"({self._settings.max_daily_loss_pct * 100}% of balance)"
            )
            circuit_breaker_reason = (
                f"Daily loss limit ({self._settings.max_daily_loss_pct * 100}%) exceeded"
            )

            logger.error(
                "daily_loss_limit_exceeded",
                daily_pnl=float(metrics.daily_realized_pnl),
                max_daily_loss=float(max_daily_loss),
                circuit_breaker=True,
            )

            return ValidationResult(
                valid=False,
                reason=reason,
                circuit_breaker_triggered=True,
                circuit_breaker_reason=circuit_breaker_reason,
            )

        return ValidationResult(valid=True)

    def _validate_drawdown(
        self,
        metrics: RiskMetrics,
    ) -> ValidationResult:
        """Validate that drawdown hasn't exceeded maximum.

        This is a circuit breaker - triggers trading pause requiring manual intervention.

        Args:
            metrics: Current risk metrics.

        Returns:
            ValidationResult with circuit_breaker_triggered if limit hit.
        """
        max_drawdown = Decimal(str(self._settings.max_drawdown_pct))

        if metrics.current_drawdown > max_drawdown:
            reason = (
                f"Maximum drawdown exceeded: "
                f"{metrics.current_drawdown * 100:.2f}% > {max_drawdown * 100:.2f}%"
            )
            circuit_breaker_reason = f"Maximum drawdown ({max_drawdown * 100:.2f}%) exceeded"

            logger.error(
                "max_drawdown_exceeded",
                current_drawdown=float(metrics.current_drawdown),
                max_drawdown=float(max_drawdown),
                circuit_breaker=True,
            )

            return ValidationResult(
                valid=False,
                reason=reason,
                circuit_breaker_triggered=True,
                circuit_breaker_reason=circuit_breaker_reason,
            )

        return ValidationResult(valid=True)

    @property
    def settings(self) -> RiskSettings:
        """Get the risk settings."""
        return self._settings

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"RiskValidator("
            f"max_position_size={self._settings.max_position_size_pct}, "
            f"max_daily_loss={self._settings.max_daily_loss_pct}, "
            f"max_drawdown={self._settings.max_drawdown_pct}"
            ")"
        )
