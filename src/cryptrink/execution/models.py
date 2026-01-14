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
