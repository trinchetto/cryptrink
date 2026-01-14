"""Suggest mode executor - generates trade suggestions without execution.

This executor analyzes signals and returns suggestions for what trades
could be executed, but does not actually place any orders.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger
from cryptrink.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionMode,
    ExecutionResult,
    OrderStatus,
    OrderType,
    calculate_quantity,
    determine_order_side,
)
from cryptrink.strategies.base import SignalType

if TYPE_CHECKING:
    from cryptrink.strategies.base import Signal

logger = get_logger(__name__)


class SuggestExecutor(BaseExecutor):
    """Executor that generates trade suggestions without execution.

    This executor analyzes trading signals and provides suggestions for
    what orders could be placed, but never actually submits orders to
    an exchange or simulates execution.

    Useful for:
    - Testing strategy signals
    - Manual trading with automated suggestions
    - Strategy validation before going live
    """

    def __init__(self) -> None:
        """Initialize the suggest executor."""
        super().__init__(ExecutionMode.SUGGEST)
        self._suggestion_counter = 0

    async def execute_signal(
        self,
        signal: Signal,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Generate a trade suggestion from a signal.

        Args:
            signal: Trading signal from strategy.
            context: Execution context with market data and positions.

        Returns:
            ExecutionResult with suggestion details.
        """
        # Ignore HOLD signals
        if signal.signal_type == SignalType.HOLD:
            return ExecutionResult(
                success=False,
                message="No action suggested (HOLD signal)",
                metadata={
                    "signal_type": signal.signal_type.value,
                    "reason": "hold_signal",
                },
            )

        # Generate suggestion ID
        self._suggestion_counter += 1
        suggestion_id = f"SUGGEST-{self._suggestion_counter:06d}"

        # Determine order side and type
        order_side = determine_order_side(signal.signal_type)
        order_type = OrderType.MARKET  # For now, always suggest market orders

        # Calculate suggested quantity (simplified - Phase 6 will have proper position sizing)
        quantity = calculate_quantity(context, order_side)

        # Calculate suggested price
        suggested_price = signal.price if signal.price else context.current_price

        logger.info(
            "trade_suggestion_generated",
            suggestion_id=suggestion_id,
            symbol=signal.symbol,
            side=order_side.value,
            type=order_type.value,
            quantity=float(quantity),
            price=float(suggested_price),
            signal_type=signal.signal_type.value,
            signal_strength=signal.strength.value,
        )

        return ExecutionResult(
            success=True,
            order_id=suggestion_id,
            order_type=order_type,
            order_side=order_side,
            quantity=quantity,
            price=suggested_price,
            status=OrderStatus.PENDING,
            message=f"Suggested {order_side.value} {quantity} {signal.symbol} at ~{suggested_price}",
            metadata={
                "signal_type": signal.signal_type.value,
                "signal_strength": signal.strength.value,
                "stop_loss": float(signal.stop_loss) if signal.stop_loss else None,
                "take_profit": float(signal.take_profit) if signal.take_profit else None,
                "suggestion_only": True,
            },
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel is not applicable for suggestions.

        Args:
            order_id: Suggestion ID (ignored).

        Returns:
            False, as suggestions cannot be cancelled.
        """
        logger.debug(
            "cancel_not_applicable_for_suggestions",
            order_id=order_id,
        )
        return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get status of a suggestion.

        Args:
            order_id: Suggestion ID.

        Returns:
            Always returns PENDING for suggestions.
        """
        # All suggestions remain in PENDING state
        return OrderStatus.PENDING

    async def sync_state(self) -> None:
        """Sync state (no-op for suggest mode).

        Suggest mode has no state to sync since it doesn't execute orders.
        """
        logger.debug("suggest_mode_sync_state_noop")
