"""Backtesting engine for testing trading strategies against historical data.

This module provides a realistic backtesting environment with:
- Slippage simulation (ConstantSlippageModel, PercentageSlippageModel)
- Trading fee calculation (PercentageFeeModel)
- Order execution simulation (BacktestExecutor)
- Performance metrics calculation (BacktestMetricsCalculator)
- Equity curve visualization (BacktestResult)
- Event-driven historical data replay (BacktestEngine)
"""

from __future__ import annotations

from cryptrink.backtest.executor import BacktestExecutor
from cryptrink.backtest.metrics import BacktestMetrics, BacktestMetricsCalculator
from cryptrink.backtest.models import (
    ConstantSlippageModel,
    FeeModel,
    PercentageFeeModel,
    PercentageSlippageModel,
    SlippageModel,
)
from cryptrink.backtest.result import BacktestResult

__all__ = [
    "BacktestExecutor",
    "BacktestMetrics",
    "BacktestMetricsCalculator",
    "BacktestResult",
    "ConstantSlippageModel",
    "FeeModel",
    "PercentageFeeModel",
    "PercentageSlippageModel",
    "SlippageModel",
]
