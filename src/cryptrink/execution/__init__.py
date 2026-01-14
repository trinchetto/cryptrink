"""Execution module for order execution and position management.

This module provides the execution framework for trading operations, including:
- Multiple execution modes (live, paper, suggest)
- Order management and tracking
- Position tracking and P&L calculation
- State persistence and recovery
"""

from cryptrink.execution.base import (
    BaseExecutor,
    ExecutionContext,
    ExecutionMode,
    ExecutionResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from cryptrink.execution.models import Order, Trade
from cryptrink.execution.order_manager import OrderManager
from cryptrink.execution.repository import OrderRepository, TradeRepository

__all__ = [  # noqa: RUF022
    # Base classes and enums
    "BaseExecutor",
    "ExecutionContext",
    "ExecutionMode",
    "ExecutionResult",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    # Models
    "Order",
    "Trade",
    # Managers and repositories
    "OrderManager",
    "OrderRepository",
    "TradeRepository",
]
