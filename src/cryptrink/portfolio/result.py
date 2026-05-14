"""Result container for a portfolio backtest.

Mirrors :class:`cryptrink.backtest.result.BacktestResult` but adds a
per-allocation breakdown so the Portfolio tab can show which pair
contributed how much to the aggregate equity curve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from cryptrink.backtest.metrics import BacktestMetrics
    from cryptrink.execution.models import Order, Position
    from cryptrink.portfolio.models import Portfolio


@dataclass
class AllocationBreakdown:
    """Per-allocation contribution rolled up from the closed positions."""

    symbol: str
    strategy_name: str
    realized_pnl: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal  # 0..1
    best_trade: Decimal
    worst_trade: Decimal


@dataclass
class PortfolioBacktestResult:
    """Comprehensive result of a portfolio backtest.

    ``equity_curve`` is the *aggregate* mark-to-market equity across the
    whole portfolio (cash + every open position priced at the current
    candle close). The per-allocation breakdown is best-effort: it
    aggregates the closed positions filtered by symbol, which is enough
    for "did this pair help or hurt?" but does not reconstruct a
    per-allocation equity curve (we'd need to track cash share per
    allocation to do that, which Phase 1 deliberately doesn't).
    """

    portfolio: Portfolio
    start_time: datetime
    end_time: datetime
    initial_balance: Decimal

    metrics: BacktestMetrics
    equity_curve: list[tuple[datetime, Decimal]]
    drawdown_curve: list[tuple[datetime, Decimal]]
    trades: list[Position]
    orders: list[Order]
    allocations: list[AllocationBreakdown]
