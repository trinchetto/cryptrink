"""Base classes and enums for the execution framework.

This module defines the core abstractions for order execution, including
execution modes, order types, and the base executor interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptrink.strategies.base import Signal


class ExecutionMode(str, Enum):
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


class OrderType(str, Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"


class OrderSide(str, Enum):
    """Order side (buy or sell)."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """Order status throughout its lifecycle."""

    PENDING = "pending"  # Created but not yet submitted
    SUBMITTED = "submitted"  # Submitted to exchange
    PARTIALLY_FILLED = "partially_filled"  # Partial execution
    FILLED = "filled"  # Fully executed
    CANCELLED = "cancelled"  # Cancelled by user or system
    REJECTED = "rejected"  # Rejected by exchange
    EXPIRED = "expired"  # Expired (for limit orders with TTL)


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
