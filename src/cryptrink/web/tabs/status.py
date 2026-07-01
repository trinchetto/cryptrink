"""Status tab for the Cryptrink Gradio web app."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from cryptrink.data.storage import Base
from cryptrink.execution.models import EngineState, Order, Position
from cryptrink.execution.repository import OrderRepository, PositionRepository
from cryptrink.web.state import get_runtime


async def refresh() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch current engine states, recent orders, and recent positions."""
    runtime = get_runtime()
    session_factory = runtime.session_factory

    db_engine = session_factory.kw["bind"]
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        stmt = select(EngineState).order_by(EngineState.updated_at.desc())
        scalars = await session.execute(stmt)
        engines = list(scalars.scalars().all())

    order_repo = OrderRepository(session_factory)
    orders = await order_repo.get_recent_orders(limit=20)

    position_repo = PositionRepository(session_factory)
    positions = await position_repo.get_recent_positions(limit=20)

    return (
        _engines_dataframe(engines),
        _orders_dataframe(orders),
        _positions_dataframe(positions),
    )


def _engines_dataframe(engines: list[EngineState]) -> pd.DataFrame:
    columns = [
        "engine_id",
        "strategy",
        "mode",
        "running",
        "current_balance",
        "drawdown_pct",
        "circuit_breaker",
        "updated_at",
    ]
    if not engines:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "engine_id": e.engine_id,
            "strategy": e.strategy_name,
            "mode": e.executor_mode,
            "running": e.is_running,
            "current_balance": float(e.current_balance_decimal),
            "drawdown_pct": float(e.current_drawdown_decimal) * 100,
            "circuit_breaker": e.circuit_breaker_active,
            "updated_at": e.updated_datetime,
        }
        for e in engines
    ]
    return pd.DataFrame(rows, columns=columns)


def _orders_dataframe(orders: list[Order]) -> pd.DataFrame:
    columns = ["created_at", "symbol", "side", "type", "status", "quantity", "price"]
    if not orders:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "created_at": o.created_datetime,
            "symbol": o.symbol,
            "side": o.side,
            "type": o.order_type,
            "status": o.status,
            "quantity": float(o.quantity_decimal),
            "price": float(o.price_decimal) if o.price_decimal is not None else None,
        }
        for o in orders
    ]
    return pd.DataFrame(rows, columns=columns)


def _positions_dataframe(positions: list[Position]) -> pd.DataFrame:
    columns = [
        "opened_at",
        "closed_at",
        "symbol",
        "side",
        "status",
        "quantity",
        "entry_price",
        "exit_price",
        "realized_pnl",
    ]
    if not positions:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "opened_at": p.opened_datetime,
            "closed_at": p.closed_datetime,
            "symbol": p.symbol,
            "side": p.side,
            "status": p.status,
            "quantity": float(p.quantity_decimal),
            "entry_price": float(p.entry_price_decimal),
            "exit_price": (
                float(p.exit_price_decimal) if p.exit_price_decimal is not None else None
            ),
            "realized_pnl": float(p.realized_pnl_decimal),
        }
        for p in positions
    ]
    return pd.DataFrame(rows, columns=columns)
