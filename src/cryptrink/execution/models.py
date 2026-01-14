"""Database models for order execution and tracking.

This module provides SQLAlchemy models for storing orders, trades, and
execution state in the database.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from cryptrink.data.storage import Base


class Order(Base):
    """Order tracking model.

    Stores information about all orders (pending, filled, cancelled, etc.)
    for tracking and reconciliation purposes.
    """

    __tablename__ = "orders"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Order identification
    order_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Order details
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy, sell
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)  # market, limit
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Quantities and prices (stored as strings for precision)
    quantity: Mapped[str] = mapped_column(String(50), nullable=False)
    filled_quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    price: Mapped[str | None] = mapped_column(String(50), nullable=True)  # None for market orders
    average_fill_price: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Fees
    fee: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    fee_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Timestamps (Unix timestamp in milliseconds)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    submitted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    filled_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cancelled_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Metadata (JSON as string) - named order_metadata to avoid SQLAlchemy reserved word
    order_metadata: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Strategy information
    strategy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signal_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    def __repr__(self) -> str:
        """String representation of Order."""
        return (
            f"Order(order_id={self.order_id!r}, symbol={self.symbol!r}, "
            f"side={self.side}, status={self.status}, quantity={self.quantity})"
        )

    @property
    def quantity_decimal(self) -> Decimal:
        """Get quantity as Decimal."""
        return Decimal(self.quantity)

    @property
    def filled_quantity_decimal(self) -> Decimal:
        """Get filled quantity as Decimal."""
        return Decimal(self.filled_quantity)

    @property
    def price_decimal(self) -> Decimal | None:
        """Get price as Decimal."""
        return Decimal(self.price) if self.price else None

    @property
    def average_fill_price_decimal(self) -> Decimal | None:
        """Get average fill price as Decimal."""
        return Decimal(self.average_fill_price) if self.average_fill_price else None

    @property
    def fee_decimal(self) -> Decimal:
        """Get fee as Decimal."""
        return Decimal(self.fee)

    @property
    def created_datetime(self) -> datetime:
        """Get created_at as datetime object."""
        return datetime.fromtimestamp(self.created_at / 1000.0, tz=UTC)

    @property
    def submitted_datetime(self) -> datetime | None:
        """Get submitted_at as datetime object."""
        return (
            datetime.fromtimestamp(self.submitted_at / 1000.0, tz=UTC)
            if self.submitted_at
            else None
        )

    @property
    def filled_datetime(self) -> datetime | None:
        """Get filled_at as datetime object."""
        return datetime.fromtimestamp(self.filled_at / 1000.0, tz=UTC) if self.filled_at else None

    @property
    def cancelled_datetime(self) -> datetime | None:
        """Get cancelled_at as datetime object."""
        return (
            datetime.fromtimestamp(self.cancelled_at / 1000.0, tz=UTC)
            if self.cancelled_at
            else None
        )


class Trade(Base):
    """Trade execution model.

    Stores individual trade executions. An order can have multiple trades
    if it's partially filled multiple times.
    """

    __tablename__ = "trades"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Trade identification
    trade_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    exchange_trade_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Trade details
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy, sell

    # Quantities and prices (stored as strings for precision)
    quantity: Mapped[str] = mapped_column(String(50), nullable=False)
    price: Mapped[str] = mapped_column(String(50), nullable=False)

    # Fees
    fee: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    fee_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Timestamp (Unix timestamp in milliseconds)
    executed_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # Metadata - named trade_metadata to avoid SQLAlchemy reserved word
    trade_metadata: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    def __repr__(self) -> str:
        """String representation of Trade."""
        return (
            f"Trade(trade_id={self.trade_id!r}, order_id={self.order_id!r}, "
            f"symbol={self.symbol!r}, side={self.side}, quantity={self.quantity}, price={self.price})"
        )

    @property
    def quantity_decimal(self) -> Decimal:
        """Get quantity as Decimal."""
        return Decimal(self.quantity)

    @property
    def price_decimal(self) -> Decimal:
        """Get price as Decimal."""
        return Decimal(self.price)

    @property
    def fee_decimal(self) -> Decimal:
        """Get fee as Decimal."""
        return Decimal(self.fee)

    @property
    def executed_datetime(self) -> datetime:
        """Get executed_at as datetime object."""
        return datetime.fromtimestamp(self.executed_at / 1000.0, tz=UTC)

    @property
    def notional_value(self) -> Decimal:
        """Calculate the notional value of the trade."""
        return self.quantity_decimal * self.price_decimal


class Position(Base):
    """Position tracking model.

    Tracks open and closed positions with P&L calculation.
    Uses FIFO accounting for partial position closes.
    """

    __tablename__ = "positions"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Position identification
    position_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # long, short

    # Position state
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # open, closed

    # Quantities and prices (stored as strings for precision)
    quantity: Mapped[str] = mapped_column(String(50), nullable=False)
    entry_price: Mapped[str] = mapped_column(String(50), nullable=False)
    exit_price: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # P&L tracking
    realized_pnl: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    unrealized_pnl: Mapped[str] = mapped_column(String(50), nullable=False, default="0")

    # Fees
    total_fees: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    fee_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Timestamps (Unix timestamp in milliseconds)
    opened_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    closed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    # Entry/exit order tracking
    entry_order_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    exit_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Strategy information
    strategy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Metadata
    position_metadata: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    def __repr__(self) -> str:
        """String representation of Position."""
        return (
            f"Position(position_id={self.position_id!r}, symbol={self.symbol!r}, "
            f"side={self.side}, status={self.status}, quantity={self.quantity}, "
            f"entry_price={self.entry_price})"
        )

    @property
    def quantity_decimal(self) -> Decimal:
        """Get quantity as Decimal."""
        return Decimal(self.quantity)

    @property
    def entry_price_decimal(self) -> Decimal:
        """Get entry price as Decimal."""
        return Decimal(self.entry_price)

    @property
    def exit_price_decimal(self) -> Decimal | None:
        """Get exit price as Decimal."""
        return Decimal(self.exit_price) if self.exit_price else None

    @property
    def realized_pnl_decimal(self) -> Decimal:
        """Get realized P&L as Decimal."""
        return Decimal(self.realized_pnl)

    @property
    def unrealized_pnl_decimal(self) -> Decimal:
        """Get unrealized P&L as Decimal."""
        return Decimal(self.unrealized_pnl)

    @property
    def total_fees_decimal(self) -> Decimal:
        """Get total fees as Decimal."""
        return Decimal(self.total_fees)

    @property
    def opened_datetime(self) -> datetime:
        """Get opened_at as datetime object."""
        return datetime.fromtimestamp(self.opened_at / 1000.0, tz=UTC)

    @property
    def closed_datetime(self) -> datetime | None:
        """Get closed_at as datetime object."""
        return datetime.fromtimestamp(self.closed_at / 1000.0, tz=UTC) if self.closed_at else None

    @property
    def notional_value(self) -> Decimal:
        """Calculate the notional value of the position."""
        return self.quantity_decimal * self.entry_price_decimal

    @property
    def net_pnl(self) -> Decimal:
        """Calculate net P&L (realized + unrealized - fees)."""
        return self.realized_pnl_decimal + self.unrealized_pnl_decimal - self.total_fees_decimal


class EngineState(Base):
    """Engine state tracking model for persistence and recovery.

    Stores the state of the trading engine to enable recovery from interruptions.
    Only one active state record should exist per engine instance.
    """

    __tablename__ = "engine_states"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Engine identification
    engine_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    executor_mode: Mapped[str] = mapped_column(String(20), nullable=False)

    # Engine state
    is_running: Mapped[bool] = mapped_column(nullable=False, default=False)
    initial_balance: Mapped[str] = mapped_column(String(50), nullable=False)
    current_balance: Mapped[str] = mapped_column(String(50), nullable=False)

    # Configuration
    max_position_size: Mapped[str] = mapped_column(String(50), nullable=False)
    max_open_positions: Mapped[int] = mapped_column(nullable=False)

    # Counters
    signal_count: Mapped[int] = mapped_column(nullable=False, default=0)
    execution_count: Mapped[int] = mapped_column(nullable=False, default=0)

    # Timestamps (Unix timestamp in milliseconds)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    last_signal_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Metadata (JSON as string)
    state_metadata: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    def __repr__(self) -> str:
        """String representation of EngineState."""
        return (
            f"EngineState(engine_id={self.engine_id!r}, strategy={self.strategy_name}, "
            f"mode={self.executor_mode}, running={self.is_running})"
        )

    @property
    def initial_balance_decimal(self) -> Decimal:
        """Get initial balance as Decimal."""
        return Decimal(self.initial_balance)

    @property
    def current_balance_decimal(self) -> Decimal:
        """Get current balance as Decimal."""
        return Decimal(self.current_balance)

    @property
    def max_position_size_decimal(self) -> Decimal:
        """Get max position size as Decimal."""
        return Decimal(self.max_position_size)

    @property
    def created_datetime(self) -> datetime:
        """Get created_at as datetime object."""
        return datetime.fromtimestamp(self.created_at / 1000.0, tz=UTC)

    @property
    def updated_datetime(self) -> datetime:
        """Get updated_at as datetime object."""
        return datetime.fromtimestamp(self.updated_at / 1000.0, tz=UTC)

    @property
    def last_signal_datetime(self) -> datetime | None:
        """Get last_signal_at as datetime object."""
        return (
            datetime.fromtimestamp(self.last_signal_at / 1000.0, tz=UTC)
            if self.last_signal_at
            else None
        )
