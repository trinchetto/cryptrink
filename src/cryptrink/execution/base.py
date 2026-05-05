"""Base classes and enums for the execution framework.

This module defines the core abstractions for order execution, including
execution modes, order types, and the base executor interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

if TYPE_CHECKING:
    from cryptrink.strategies.base import Signal, SignalType


class ExecutionMode(StrEnum):
    """Execution mode for the trading engine.

    - LIVE: Execute real orders on the exchange
    - PAPER: Simulate order execution without touching the exchange
    - SUGGEST: Generate trade suggestions without execution
    - BACKTEST: Backtest mode (for Phase 7)
    """

    LIVE = "live"
    PAPER = "paper"
    SUGGEST = "suggest"
    BACKTEST = "backtest"


class OrderType(StrEnum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"


class OrderSide(StrEnum):
    """Order side (buy or sell)."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    """Order status throughout its lifecycle."""

    PENDING = "pending"  # Created but not yet submitted
    SUBMITTED = "submitted"  # Submitted to exchange
    PARTIALLY_FILLED = "partially_filled"  # Partial execution
    FILLED = "filled"  # Fully executed
    CANCELLED = "cancelled"  # Cancelled by user or system
    REJECTED = "rejected"  # Rejected by exchange
    EXPIRED = "expired"  # Expired (for limit orders with TTL)


class PositionSizerProtocol(Protocol):
    """Protocol for position sizing implementations."""

    def calculate_position_size(
        self,
        context: ExecutionContext,
        signal: Signal,
        order_side: OrderSide,
    ) -> Decimal:
        """Return the desired position size."""


@dataclass
class ExecutionContext:
    """Context information for order execution.

    Contains all necessary information for making execution decisions,
    including current positions, account balance, and market data.
    """

    symbol: str
    current_price: Decimal
    timestamp: datetime
    account_balance: Decimal
    has_position: bool
    position_size: Decimal = Decimal("0")
    position_entry_price: Decimal | None = None
    available_balance: Decimal = Decimal("0")
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and set defaults."""
        if self.timestamp.tzinfo is None:
            # Assume UTC if no timezone
            self.timestamp = self.timestamp.replace(tzinfo=UTC)

        # Set available balance to account balance if not specified
        if self.available_balance == Decimal("0"):
            self.available_balance = self.account_balance


@dataclass
class ExecutionResult:
    """Result of an execution attempt.

    Contains information about the execution outcome, including
    success/failure, order details, and any error messages.
    """

    success: bool
    order_id: str | None = None
    order_type: OrderType | None = None
    order_side: OrderSide | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    message: str = ""
    error: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate timestamp has timezone info."""
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=UTC)


class BaseExecutor(ABC):
    """Abstract base class for order executors.

    Executors are responsible for executing trading signals based on the
    execution mode (live, paper, suggest). Each executor implements the
    execution logic appropriate for its mode.
    """

    def __init__(self, mode: ExecutionMode) -> None:
        """Initialize the executor.

        Args:
            mode: Execution mode for this executor.
        """
        self._mode = mode

    @property
    def mode(self) -> ExecutionMode:
        """Get the execution mode."""
        return self._mode

    @abstractmethod
    async def execute_signal(
        self,
        signal: Signal,
        context: ExecutionContext,
    ) -> ExecutionResult:
        """Execute a trading signal.

        Args:
            signal: Trading signal from strategy.
            context: Execution context with market data and positions.

        Returns:
            Result of the execution attempt.
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Args:
            order_id: ID of the order to cancel.

        Returns:
            True if cancellation was successful, False otherwise.
        """
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the status of an order.

        Args:
            order_id: ID of the order to check.

        Returns:
            Current status of the order.

        Raises:
            KeyError: If order ID is not found.
        """
        pass

    @abstractmethod
    async def sync_state(self) -> None:
        """Synchronize executor state with external systems.

        For live mode, this syncs with the exchange.
        For paper mode, this may update simulated fills.
        For suggest mode, this is typically a no-op.
        """
        pass

    def __repr__(self) -> str:
        """Return string representation."""
        return f"{self.__class__.__name__}(mode={self._mode.value})"


class _ValidationResult(TypedDict):
    """Result of order validation."""

    valid: bool
    reason: str


def determine_order_side(signal_type: SignalType) -> OrderSide:
    """Determine order side from signal type.

    Args:
        signal_type: Trading signal type.

    Returns:
        Order side (BUY or SELL).
    """
    from cryptrink.strategies.base import SignalType as ST

    if signal_type in (ST.ENTRY_LONG, ST.EXIT_SHORT):
        return OrderSide.BUY
    return OrderSide.SELL


def calculate_quantity(
    context: ExecutionContext,
    order_side: OrderSide,
    position_size: Decimal | None = None,
    signal: Signal | None = None,
    position_sizer: PositionSizerProtocol | None = None,
) -> Decimal:
    """Calculate order quantity for execution.

    Uses PositionSizer if provided, otherwise falls back to simple allocation.

    Args:
        context: Execution context with balance and price info.
        order_side: Order side (BUY or SELL).
        position_size: Current position size (for SELL orders), optional.
        signal: Trading signal (required for position sizing algorithms).
        position_sizer: PositionSizer instance (uses risk-based sizing if provided).

    Returns:
        Order quantity.
    """
    if order_side == OrderSide.SELL:
        # For sells, use current position size
        if position_size is not None and position_size > 0:
            return position_size
        if context.has_position and context.position_size > 0:
            return context.position_size
        return Decimal("0")

    # For buys, use PositionSizer if available
    if position_sizer is not None and signal is not None:
        return position_sizer.calculate_position_size(context, signal, order_side)

    # Fallback: simple 10% allocation (Phase 5 behavior)
    allocation = Decimal("0.1")
    notional_value = context.available_balance * allocation
    quantity = notional_value / context.current_price

    # Round toward zero to 8 decimal places so the resulting position value
    # never exceeds the requested allocation. Banker's rounding can tip the
    # quantity up by half a satoshi, which then breaches max_position_size_pct
    # at the validator and rejects perfectly sized orders.
    return quantity.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def validate_order(
    order_side: OrderSide,
    quantity: Decimal,
    context: ExecutionContext,
    balance: Decimal | None = None,
) -> _ValidationResult:
    """Validate order before execution.

    Args:
        order_side: Order side (BUY or SELL).
        quantity: Order quantity.
        context: Execution context with position and balance info.
        balance: Optional override for balance (used by paper executor).

    Returns:
        Validation result with 'valid' bool and 'reason' string.
    """
    if quantity <= 0:
        return {"valid": False, "reason": "Invalid quantity (must be > 0)"}

    effective_balance = balance if balance is not None else context.available_balance

    if order_side == OrderSide.BUY:
        # Check if we have enough balance
        required_balance = quantity * context.current_price
        if required_balance > effective_balance:
            return {
                "valid": False,
                "reason": f"Insufficient balance (required: {required_balance}, available: {effective_balance})",
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
