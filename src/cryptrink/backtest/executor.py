"""Backtest executor - simulates order execution with slippage and fees.

This executor extends paper trading simulation with realistic execution costs:
- Slippage: Execution price differs from signal price
- Trading fees: Percentage-based fees deducted from balance
- Instant fills: All orders fill immediately (no partial fills in Phase 7)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast
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
    calculate_quantity,
    determine_order_side,
)
from cryptrink.strategies.base import SignalType

if TYPE_CHECKING:
    from cryptrink.backtest.models import FeeModel, SlippageModel
    from cryptrink.strategies.base import Signal

logger = get_logger(__name__)


class BacktestExecutor(BaseExecutor):
    """Executor that simulates order execution with slippage and fees.

    This executor extends paper trading simulation to include realistic
    execution costs, making backtesting results more accurate.

    Key features:
    - Slippage simulation (execution price differs from market price)
    - Trading fee calculation (percentage of notional value)
    - Instant order fills (no partial fills or order book simulation)
    - Balance and position tracking

    Useful for:
    - Realistic backtesting of strategies
    - Understanding impact of execution costs on strategy performance
    - Comparing strategies under similar cost assumptions
    """

    def __init__(
        self,
        initial_balance: Decimal,
        slippage_model: SlippageModel,
        fee_model: FeeModel,
    ) -> None:
        """Initialize the backtest executor.

        Args:
            initial_balance: Starting balance for backtest.
            slippage_model: Model for calculating slippage.
            fee_model: Model for calculating trading fees.
        """
        super().__init__(ExecutionMode.BACKTEST)
        self._initial_balance = initial_balance
        self._balance = initial_balance
        self._slippage_model = slippage_model
        self._fee_model = fee_model
        self._orders: dict[str, dict[str, object]] = {}
        self._positions: dict[str, dict[str, object]] = {}

        logger.info(
            "backtest_executor_initialized",
            initial_balance=float(initial_balance),
            slippage_model=repr(slippage_model),
            fee_model=repr(fee_model),
        )

    @property
    def balance(self) -> Decimal:
        """Get current balance."""
        return self._balance

    @property
    def initial_balance(self) -> Decimal:
        """Get initial balance."""
        return self._initial_balance

    def get_balance(self) -> Decimal:
        """Get current balance (for compatibility with TradingEngine)."""
        return self._balance

    async def execute_signal(
        self,
        signal: Signal,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute a trading signal in backtest mode.

        Args:
            signal: Trading signal from strategy.
            context: Execution context with market data and positions.

        Returns:
            Result of the simulated execution with slippage and fees.
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
        order_id = f"BT-{uuid4().hex[:12].upper()}"

        # Determine order details
        order_side = determine_order_side(signal.signal_type)
        order_type = OrderType.MARKET

        # Get position size from internal tracking
        position = self._positions.get(context.symbol)
        position_size = cast("Decimal", position["quantity"]) if position else None
        quantity = calculate_quantity(context, order_side, position_size)

        # Apply slippage to execution price
        execution_price = self._slippage_model.apply_slippage(
            context.current_price, signal, order_side
        )

        # Calculate trading fee
        fee = self._fee_model.calculate_fee(quantity, execution_price, order_side)

        # Validate order (balance check includes fee for buy orders)
        validation_result = self._validate_order_with_fees(
            order_side, quantity, execution_price, fee, context
        )
        if not validation_result["valid"]:
            reason = str(validation_result["reason"])
            return ExecutionResult(
                success=False,
                order_id=order_id,
                order_type=order_type,
                order_side=order_side,
                quantity=quantity,
                price=execution_price,
                status=OrderStatus.REJECTED,
                message=reason,
                error=reason,
                metadata={"signal_type": signal.signal_type.value},
            )

        # Execute the order (instant fill in backtest mode)
        execution_result = self._execute_order(
            order_id, order_side, quantity, execution_price, fee, signal.symbol
        )

        # Update balance and positions
        self._update_balance_and_positions(
            order_side, quantity, execution_price, fee, signal.symbol
        )

        logger.info(
            "backtest_order_executed",
            order_id=order_id,
            symbol=signal.symbol,
            side=order_side.value,
            quantity=float(quantity),
            price=float(execution_price),
            fee=float(fee),
            balance=float(self._balance),
            signal_type=signal.signal_type.value,
        )

        return execution_result

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a backtest order.

        In backtest mode, market orders are filled instantly, so cancellation
        is not applicable. This method is here for interface completeness.

        Args:
            order_id: Order ID to cancel.

        Returns:
            False, as backtest market orders cannot be cancelled (instant fill).
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
        logger.info("backtest_order_cancelled", order_id=order_id)
        return True

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the status of a backtest order.

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
        """Sync state (no-op for backtest mode).

        Backtest mode maintains its own internal state and doesn't need
        to sync with external systems.
        """
        logger.debug(
            "backtest_mode_sync_state",
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
        """Reset backtest state.

        Args:
            initial_balance: New initial balance (optional).
        """
        if initial_balance is not None:
            self._initial_balance = initial_balance

        self._balance = self._initial_balance
        self._orders.clear()
        self._positions.clear()

        logger.info(
            "backtest_executor_reset",
            initial_balance=float(self._initial_balance),
        )

    def _validate_order_with_fees(
        self,
        order_side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        context: ExecutionContext,
    ) -> dict[str, object]:
        """Validate order including fee cost.

        Args:
            order_side: Order side.
            quantity: Order quantity.
            price: Execution price.
            fee: Trading fee.
            context: Execution context.

        Returns:
            Validation result with "valid" and "reason" keys.
        """
        if order_side == OrderSide.BUY:
            # Buy requires balance for notional + fee
            required = quantity * price + fee
            if self._balance < required:
                return {
                    "valid": False,
                    "reason": f"Insufficient balance: {self._balance} < {required} (includes fee)",
                }

        # SELL orders don't need balance validation (selling existing position)
        return {"valid": True, "reason": ""}

    def _execute_order(
        self,
        order_id: str,
        order_side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        symbol: str,
    ) -> ExecutionResult:
        """Execute and record the order.

        Args:
            order_id: Order ID.
            order_side: Order side.
            quantity: Order quantity.
            price: Execution price (with slippage applied).
            fee: Trading fee.
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
            "fee": fee,
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
            message=f"Backtest order filled: {order_side.value} {quantity} {symbol} @ {price} (fee: {fee})",
            metadata={
                "backtest": True,
                "balance_after": float(self._balance),
                "execution_price_with_slippage": float(price),
                "fee": float(fee),
            },
        )

    def _update_balance_and_positions(
        self,
        order_side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        symbol: str,
    ) -> None:
        """Update balance and positions after order execution.

        Args:
            order_side: Order side.
            quantity: Order quantity.
            price: Execution price.
            fee: Trading fee.
            symbol: Trading symbol.
        """
        notional_value = quantity * price

        if order_side == OrderSide.BUY:
            # Decrease balance (cost + fee)
            self._balance -= notional_value + fee

            # Update or create position
            if symbol in self._positions:
                position = self._positions[symbol]
                old_quantity = position["quantity"]
                old_value = old_quantity * position["entry_price"]  # type: ignore[operator]
                new_quantity = old_quantity + quantity  # type: ignore[operator]
                new_value = old_value + notional_value
                position["quantity"] = new_quantity
                position["entry_price"] = new_value / new_quantity
                position["total_fees"] = position.get("total_fees", Decimal("0")) + fee  # type: ignore[operator]
            else:
                self._positions[symbol] = {
                    "symbol": symbol,
                    "quantity": quantity,
                    "entry_price": price,
                    "total_fees": fee,
                    "timestamp": datetime.now(UTC),
                }

        elif order_side == OrderSide.SELL:
            # Increase balance (proceeds - fee)
            self._balance += notional_value - fee

            # Update or close position
            if symbol in self._positions:
                position = self._positions[symbol]
                position["quantity"] -= quantity  # type: ignore[operator]
                position["total_fees"] = position.get("total_fees", Decimal("0")) + fee  # type: ignore[operator]

                # Close position if quantity is zero or near-zero
                if position["quantity"] <= Decimal("0.00000001"):  # type: ignore[operator]
                    del self._positions[symbol]
