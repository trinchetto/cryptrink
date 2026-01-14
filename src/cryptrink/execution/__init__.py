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
from cryptrink.execution.engine import TradingEngine
from cryptrink.execution.models import Order, Position, Trade
from cryptrink.execution.order_manager import OrderManager
from cryptrink.execution.position_tracker import PositionTracker
from cryptrink.execution.repository import (
    EngineStateRepository,
    OrderRepository,
    PositionRepository,
    TradeRepository,
)

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
    "Position",
    "Trade",
    # Managers and repositories
    "OrderManager",
    "PositionTracker",
    "OrderRepository",
    "PositionRepository",
    "TradeRepository",
    "EngineStateRepository",
    # Engine
    "TradingEngine",
]
