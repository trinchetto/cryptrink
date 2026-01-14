"""Live trading executor - executes real orders on the exchange.

This executor places real orders on the Revolut X exchange using the
RevolutX API client. Use with caution as this involves real money.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger
from cryptrink.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionMode,
    ExecutionResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from cryptrink.strategies.base import SignalType

if TYPE_CHECKING:
    from cryptrink.exchange.revolutx import RevolutXExchange
    from cryptrink.strategies.base import Signal

logger = get_logger(__name__)


class LiveExecutor(BaseExecutor):
    """Executor that places real orders on the exchange.

    This executor interfaces with the Revolut X exchange to execute
    real trades. It should only be used when you're ready to trade
    with real money.

    Important:
    - Real money is at risk
    - Orders are irreversible once filled
    - Always test with paper mode first
    - Ensure proper risk management is in place
    """

    def __init__(self, exchange_client: RevolutXExchange) -> None:
        """Initialize the live executor.

        Args:
            exchange_client: Revolut X API client for order execution.
        """
        super().__init__(ExecutionMode.LIVE)
        self._client = exchange_client
        self._order_tracking: dict[str, dict[str, object]] = {}

        logger.warning(
            "live_executor_initialized",
            message="Live trading mode activated - real money at risk",
        )

    async def execute_signal(
        self,
        signal: Signal,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute a trading signal on the live exchange.

        Args:
            signal: Trading signal from strategy.
            context: Execution context with market data and positions.

        Returns:
            Result of the live order execution.
        """
        # Ignore HOLD signals
        if signal.signal_type == SignalType.HOLD:
            return ExecutionResult(
                success=False,
                message="No execution (HOLD signal)",
                metadata={
                    "signal_type": signal.signal_type.value,
                    "reason": "hold_signal",
                },
            )

        # Determine order details
        order_side = self._determine_order_side(signal.signal_type)
        order_type = OrderType.MARKET  # Start with market orders only
        quantity = self._calculate_quantity(context, signal, order_side)

        # Validate order before submission
        validation_result = self._validate_order(order_side, quantity, context)
        if not validation_result["valid"]:
            return ExecutionResult(
                success=False,
                order_type=order_type,
                order_side=order_side,
                quantity=quantity,
                status=OrderStatus.REJECTED,
                message=validation_result["reason"],  # type: ignore[arg-type]
                error=validation_result["reason"],  # type: ignore[arg-type]
                metadata={"signal_type": signal.signal_type.value},
            )

        # Submit order to exchange
        try:
            # TODO: Implement place_order in RevolutX client (Step 6).
            raise NotImplementedError(
                "Live order placement not yet implemented. This will be added in Phase 5 Step 6."
            )

        except Exception as e:
            logger.error(
                "live_order_execution_failed",
                symbol=signal.symbol,
                side=order_side.value,
                quantity=float(quantity),
                error=str(e),
            )

            return ExecutionResult(
                success=False,
                order_type=order_type,
                order_side=order_side,
                quantity=quantity,
                status=OrderStatus.REJECTED,
                message=f"Order execution failed: {e}",
                error=str(e),
                metadata={"signal_type": signal.signal_type.value},
            )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a live order on the exchange.

        Args:
            order_id: Exchange order ID to cancel.

        Returns:
            True if cancellation was successful, False otherwise.
        """
        try:
            # TODO: Implement cancel_order in RevolutX client (Step 6).
            raise NotImplementedError(
                "Live order cancellation not yet implemented. This will be added in Phase 5 Step 6."
            )

        except Exception as e:
            logger.error(
                "live_order_cancellation_failed",
                order_id=order_id,
                error=str(e),
            )
            return False

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the status of a live order from the exchange.

        Args:
            order_id: Exchange order ID.

        Returns:
            Current order status.

        Raises:
            KeyError: If order ID is not found.
        """
        try:
            # Check local tracking first
            if order_id in self._order_tracking:
                # TODO: Sync with exchange to get latest status.
                return self._order_tracking[order_id]["status"]  # type: ignore[return-value]

            raise KeyError(f"Order {order_id} not found in tracking")

        except Exception as e:
            logger.error(
                "failed_to_get_order_status",
                order_id=order_id,
                error=str(e),
            )
            raise

    async def sync_state(self) -> None:
        """Synchronize executor state with the exchange.

        Fetches current order statuses and positions from the exchange
        to ensure our internal state matches reality.
        """
        try:
            # TODO: Implement state sync with exchange
            # - Fetch open orders
            # - Update order statuses
            # - Reconcile positions

            logger.debug(
                "live_state_sync",
                tracked_orders=len(self._order_tracking),
            )

        except Exception as e:
            logger.error(
                "live_state_sync_failed",
                error=str(e),
            )

    def _determine_order_side(self, signal_type: SignalType) -> OrderSide:
        """Determine order side from signal type."""
        if signal_type in (SignalType.ENTRY_LONG, SignalType.EXIT_SHORT):
            return OrderSide.BUY
        return OrderSide.SELL

    def _calculate_quantity(
        self,
        context: ExecutionContext,
        signal: Signal,
        order_side: OrderSide,
    ) -> Decimal:
        """Calculate order quantity for live trading.

        Simplified calculation - Phase 6 will implement proper position sizing.

        Args:
            context: Execution context.
            signal: Trading signal (reserved for future use).
            order_side: Order side.

        Returns:
            Order quantity.
        """
        if order_side == OrderSide.SELL:
            # For sells, use current position size
            if context.has_position:
                return context.position_size
            return Decimal("0")

        # For buys, use 10% of available balance
        allocation = Decimal("0.1")
        notional_value = context.available_balance * allocation
        quantity = notional_value / context.current_price

        # Round to 8 decimal places
        return quantity.quantize(Decimal("0.00000001"))

    def _validate_order(
        self,
        order_side: OrderSide,
        quantity: Decimal,
        context: ExecutionContext,
    ) -> dict[str, object]:
        """Validate order before submission to exchange.

        Args:
            order_side: Order side.
            quantity: Order quantity.
            context: Execution context.

        Returns:
            Validation result with 'valid' bool and 'reason' string.
        """
        if quantity <= 0:
            return {"valid": False, "reason": "Invalid quantity (must be > 0)"}

        if order_side == OrderSide.BUY:
            # Check if we have enough balance
            required_balance = quantity * context.current_price
            if required_balance > context.available_balance:
                return {
                    "valid": False,
                    "reason": f"Insufficient balance (required: {required_balance}, available: {context.available_balance})",
                }

        elif order_side == OrderSide.SELL:
            # Check if we have a position to sell
            if not context.has_position:
                return {"valid": False, "reason": "No position to sell"}

            if quantity > context.position_size:
                return {
                    "valid": False,
                    "reason": f"Insufficient position (requested: {quantity}, available: {context.position_size})",
                }

        return {"valid": True, "reason": ""}
