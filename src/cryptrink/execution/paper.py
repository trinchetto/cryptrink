"""Paper trading executor - simulates order execution without real money.

This executor simulates order execution using current market prices,
allowing strategies to be tested without risking real capital.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict
from uuid import uuid4

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
    from cryptrink.strategies.base import Signal

logger = get_logger(__name__)


class _ValidationResult(TypedDict):
    valid: bool
    reason: str


class PaperExecutor(BaseExecutor):
    """Executor that simulates order execution without real money.

    This executor tracks simulated orders and positions, executing
    orders immediately at current market prices. It maintains a
    simulated balance and position state.

    Useful for:
    - Testing strategies with realistic execution
    - Validating strategy performance before going live
    - Training and practice trading
    """

    def __init__(self, initial_balance: Decimal = Decimal("10000")) -> None:
        """Initialize the paper executor.

        Args:
            initial_balance: Starting balance for paper trading (default: $10,000).
        """
        super().__init__(ExecutionMode.PAPER)
        self._initial_balance = initial_balance
        self._balance = initial_balance
        self._orders: dict[str, dict[str, object]] = {}
        self._positions: dict[str, dict[str, object]] = {}

        logger.info(
            "paper_executor_initialized",
            initial_balance=float(initial_balance),
        )

    @property
    def balance(self) -> Decimal:
        """Get current simulated balance."""
        return self._balance

    @property
    def initial_balance(self) -> Decimal:
        """Get initial balance."""
        return self._initial_balance

    async def execute_signal(
        self,
        signal: Signal,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute a trading signal in paper trading mode.

        Args:
            signal: Trading signal from strategy.
            context: Execution context with market data and positions.

        Returns:
            Result of the simulated execution.
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

        # Generate order ID
        order_id = f"PAPER-{uuid4().hex[:12].upper()}"

        # Determine order details
        order_side = self._determine_order_side(signal.signal_type)
        order_type = OrderType.MARKET
        execution_price = context.current_price
        quantity = self._calculate_quantity(context, signal, order_side)

        # Validate order
        validation_result = self._validate_order(order_side, quantity, execution_price, context)
        if not validation_result["valid"]:
            return ExecutionResult(
                success=False,
                order_id=order_id,
                order_type=order_type,
                order_side=order_side,
                quantity=quantity,
                price=execution_price,
                status=OrderStatus.REJECTED,
                message=validation_result["reason"],
                error=validation_result["reason"],
                metadata={"signal_type": signal.signal_type.value},
            )

        # Execute the order (instant fill in paper mode)
        execution_result = self._execute_order(
            order_id, order_side, quantity, execution_price, signal.symbol
        )

        # Update balance and positions
        self._update_balance_and_positions(order_side, quantity, execution_price, signal.symbol)

        logger.info(
            "paper_order_executed",
            order_id=order_id,
            symbol=signal.symbol,
            side=order_side.value,
            quantity=float(quantity),
            price=float(execution_price),
            balance=float(self._balance),
            signal_type=signal.signal_type.value,
        )

        return execution_result

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a paper order.

        In paper mode, market orders are filled instantly, so cancellation
        is not applicable. This method is here for interface completeness.

        Args:
            order_id: Order ID to cancel.

        Returns:
            False, as paper market orders cannot be cancelled (instant fill).
        """
        if order_id not in self._orders:
            logger.warning("cancel_order_not_found", order_id=order_id)
            return False

        order = self._orders[order_id]
        if order["status"] == OrderStatus.FILLED:
            logger.debug(
                "cannot_cancel_filled_order",
                order_id=order_id,
            )
            return False

        # Update order status
        order["status"] = OrderStatus.CANCELLED
        logger.info("paper_order_cancelled", order_id=order_id)
        return True

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the status of a paper order.

        Args:
            order_id: Order ID to check.

        Returns:
            Current order status.

        Raises:
            KeyError: If order ID is not found.
        """
        if order_id not in self._orders:
            raise KeyError(f"Order {order_id} not found")

        return self._orders[order_id]["status"]  # type: ignore[return-value]

    async def sync_state(self) -> None:
        """Sync state (no-op for paper mode).

        Paper mode maintains its own internal state and doesn't need
        to sync with external systems.
        """
        logger.debug(
            "paper_mode_sync_state",
            balance=float(self._balance),
            num_positions=len(self._positions),
            num_orders=len(self._orders),
        )

    def get_position(self, symbol: str) -> dict[str, object] | None:
        """Get current position for a symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            Position details or None if no position.
        """
        return self._positions.get(symbol)

    def reset(self, initial_balance: Decimal | None = None) -> None:
        """Reset paper trading state.

        Args:
            initial_balance: New initial balance (optional).
        """
        if initial_balance is not None:
            self._initial_balance = initial_balance

        self._balance = self._initial_balance
        self._orders.clear()
        self._positions.clear()

        logger.info(
            "paper_executor_reset",
            initial_balance=float(self._initial_balance),
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
        """Calculate order quantity for paper trading.

        Simplified calculation - Phase 6 will implement proper position sizing.

        Args:
            context: Execution context.
            signal: Trading signal (reserved for future use).
            order_side: Order side (BUY or SELL).

        Returns:
            Order quantity.
        """
        if order_side == OrderSide.SELL:
            # For sells, use current position size
            position = self._positions.get(context.symbol)
            if position:
                return position["quantity"]  # type: ignore[return-value]
            return Decimal("0")

        # For buys, use 10% of balance
        allocation = Decimal("0.1")
        notional_value = self._balance * allocation
        quantity = notional_value / context.current_price

        # Round to 8 decimal places
        return quantity.quantize(Decimal("0.00000001"))

    def _validate_order(
        self,
        order_side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        context: ExecutionContext,
    ) -> _ValidationResult:
        """Validate order before execution.

        Args:
            order_side: Order side.
            quantity: Order quantity.
            price: Execution price.
            context: Execution context.

        Returns:
            Validation result with 'valid' bool and 'reason' string.
        """
        if quantity <= 0:
            return {"valid": False, "reason": "Invalid quantity (must be > 0)"}

        if order_side == OrderSide.BUY:
            # Check if we have enough balance
            required_balance = quantity * price
            if required_balance > self._balance:
                return {
                    "valid": False,
                    "reason": f"Insufficient balance (required: {required_balance}, available: {self._balance})",
                }

        elif order_side == OrderSide.SELL:
            # Check if we have a position to sell
            position = self._positions.get(context.symbol)
            if not position:
                return {"valid": False, "reason": "No position to sell"}

            if quantity > position["quantity"]:  # type: ignore[operator]
                return {
                    "valid": False,
                    "reason": f"Insufficient position (requested: {quantity}, available: {position['quantity']})",
                }

        return {"valid": True, "reason": ""}

    def _execute_order(
        self,
        order_id: str,
        order_side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        symbol: str,
    ) -> ExecutionResult:
        """Execute and record the order.

        Args:
            order_id: Order ID.
            order_side: Order side.
            quantity: Order quantity.
            price: Execution price.
            symbol: Trading symbol.

        Returns:
            Execution result.
        """
        timestamp = datetime.now(UTC)

        # Record order
        self._orders[order_id] = {
            "order_id": order_id,
            "symbol": symbol,
            "side": order_side,
            "type": OrderType.MARKET,
            "quantity": quantity,
            "price": price,
            "status": OrderStatus.FILLED,
            "timestamp": timestamp,
        }

        return ExecutionResult(
            success=True,
            order_id=order_id,
            order_type=OrderType.MARKET,
            order_side=order_side,
            quantity=quantity,
            price=price,
            status=OrderStatus.FILLED,
            timestamp=timestamp,
            message=f"Paper order filled: {order_side.value} {quantity} {symbol} @ {price}",
            metadata={
                "paper_trading": True,
                "balance_after": float(self._balance),
            },
        )

    def _update_balance_and_positions(
        self,
        order_side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        symbol: str,
    ) -> None:
        """Update balance and positions after order execution.

        Args:
            order_side: Order side.
            quantity: Order quantity.
            price: Execution price.
            symbol: Trading symbol.
        """
        notional_value = quantity * price

        if order_side == OrderSide.BUY:
            # Decrease balance
            self._balance -= notional_value

            # Update or create position
            if symbol in self._positions:
                position = self._positions[symbol]
                old_quantity = position["quantity"]
                old_value = old_quantity * position["entry_price"]  # type: ignore[operator]
                new_quantity = old_quantity + quantity  # type: ignore[operator]
                new_value = old_value + notional_value
                position["quantity"] = new_quantity
                position["entry_price"] = new_value / new_quantity
            else:
                self._positions[symbol] = {
                    "symbol": symbol,
                    "quantity": quantity,
                    "entry_price": price,
                    "timestamp": datetime.now(UTC),
                }

        elif order_side == OrderSide.SELL:
            # Increase balance
            self._balance += notional_value

            # Update or close position
            if symbol in self._positions:
                position = self._positions[symbol]
                position["quantity"] -= quantity  # type: ignore[operator]

                # Close position if quantity is zero
                if position["quantity"] <= Decimal("0.00000001"):  # type: ignore[operator]
                    del self._positions[symbol]
