"""Live trading executor - executes real orders on the exchange.

This executor places real orders on the Revolut X exchange using the
RevolutX API client. Use with caution as this involves real money.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cryptrink.core.logging import get_logger
from cryptrink.exchange.base import (
    OrderSide as ExchangeOrderSide,
)
from cryptrink.exchange.base import (
    OrderStatus as ExchangeOrderStatus,
)
from cryptrink.exchange.base import (
    OrderType as ExchangeOrderType,
)
from cryptrink.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionMode,
    ExecutionResult,
    OrderSide,
    OrderStatus,
    OrderType,
    calculate_quantity,
    determine_order_side,
    validate_order,
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
        order_side = determine_order_side(signal.signal_type)
        order_type = OrderType.MARKET  # Start with market orders only
        quantity = calculate_quantity(context, order_side)

        # Validate order before submission
        validation_result = validate_order(order_side, quantity, context)
        if not validation_result["valid"]:
            return ExecutionResult(
                success=False,
                order_type=order_type,
                order_side=order_side,
                quantity=quantity,
                status=OrderStatus.REJECTED,
                message=validation_result["reason"],
                error=validation_result["reason"],
                metadata={"signal_type": signal.signal_type.value},
            )

        # Submit order to exchange
        try:
            logger.info(
                "placing_live_order",
                symbol=signal.symbol,
                side=order_side.value,
                type=order_type.value,
                quantity=float(quantity),
                signal_type=signal.signal_type.value,
            )

            # Place order on exchange
            exchange_order = await self._client.create_order(
                symbol=signal.symbol,
                side=self._to_exchange_order_side(order_side),
                order_type=self._to_exchange_order_type(order_type),
                quantity=quantity,
                price=None,  # Market order has no price
            )

            execution_status = self._to_execution_order_status(exchange_order.status)

            # Track order locally
            self._order_tracking[exchange_order.id] = {
                "order_id": exchange_order.id,
                "symbol": signal.symbol,
                "side": order_side,
                "quantity": quantity,
                "status": execution_status,
                "signal_type": signal.signal_type,
                "created_at": exchange_order.created_at,
            }

            logger.info(
                "live_order_placed",
                order_id=exchange_order.id,
                symbol=signal.symbol,
                side=order_side.value,
                quantity=float(quantity),
                status=execution_status.value,
            )

            return ExecutionResult(
                success=True,
                order_id=exchange_order.id,
                order_type=order_type,
                order_side=order_side,
                quantity=quantity,
                price=signal.price,
                status=execution_status,
                message=f"Live order placed successfully: {exchange_order.id}",
                metadata={
                    "signal_type": signal.signal_type.value,
                    "exchange_order_id": exchange_order.id,
                    "filled_quantity": float(exchange_order.filled_quantity),
                    "created_at": exchange_order.created_at.isoformat(),
                },
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
            logger.info("cancelling_live_order", order_id=order_id)

            # Cancel order on exchange
            cancelled_order = await self._client.cancel_order(order_id)
            execution_status = self._to_execution_order_status(cancelled_order.status)

            # Update local tracking
            if order_id in self._order_tracking:
                self._order_tracking[order_id]["status"] = execution_status

            logger.info(
                "live_order_cancelled",
                order_id=order_id,
                status=execution_status.value,
            )

            return True

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
            # Fetch latest status from exchange
            order = await self._client.get_order(order_id)
            execution_status = self._to_execution_order_status(order.status)

            # Update local tracking
            if order_id in self._order_tracking:
                self._order_tracking[order_id]["status"] = execution_status

            return execution_status

        except Exception as e:
            logger.error(
                "failed_to_get_order_status",
                order_id=order_id,
                error=str(e),
            )
            raise KeyError(f"Order {order_id} not found or inaccessible: {e}") from e

    async def sync_state(self) -> None:
        """Synchronize executor state with the exchange.

        Fetches current order statuses and positions from the exchange
        to ensure our internal state matches reality.
        """
        try:
            # Fetch all open orders from exchange
            open_orders = await self._client.get_open_orders()

            # Update tracking for any tracked orders
            synced_count = 0
            for order_id, tracked_data in list(self._order_tracking.items()):
                # Find matching order in open orders
                matching_order = next((o for o in open_orders if o.id == order_id), None)

                if matching_order:
                    # Update status from exchange
                    tracked_data["status"] = self._to_execution_order_status(matching_order.status)
                    synced_count += 1
                else:
                    # Order not in open orders - likely filled or cancelled
                    # Try to get order details
                    try:
                        order = await self._client.get_order(order_id)
                        tracked_data["status"] = self._to_execution_order_status(order.status)
                        synced_count += 1
                    except Exception:
                        # Order not accessible - remove from tracking
                        logger.warning(
                            "order_not_found_during_sync",
                            order_id=order_id,
                        )

            logger.debug(
                "live_state_sync_completed",
                tracked_orders=len(self._order_tracking),
                synced_orders=synced_count,
                open_orders_count=len(open_orders),
            )

        except Exception as e:
            logger.error(
                "live_state_sync_failed",
                error=str(e),
            )

    def _to_exchange_order_side(self, order_side: OrderSide) -> ExchangeOrderSide:
        """Convert execution order side to exchange order side."""
        return ExchangeOrderSide(order_side.value)

    def _to_exchange_order_type(self, order_type: OrderType) -> ExchangeOrderType:
        """Convert execution order type to exchange order type."""
        return ExchangeOrderType(order_type.value)

    def _to_execution_order_status(self, status: ExchangeOrderStatus) -> OrderStatus:
        """Convert exchange order status to execution order status."""
        mapping = {
            ExchangeOrderStatus.PENDING: OrderStatus.PENDING,
            ExchangeOrderStatus.OPEN: OrderStatus.SUBMITTED,
            ExchangeOrderStatus.PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED,
            ExchangeOrderStatus.FILLED: OrderStatus.FILLED,
            ExchangeOrderStatus.CANCELLED: OrderStatus.CANCELLED,
            ExchangeOrderStatus.REJECTED: OrderStatus.REJECTED,
            ExchangeOrderStatus.EXPIRED: OrderStatus.EXPIRED,
        }
        return mapping.get(status, OrderStatus.SUBMITTED)
