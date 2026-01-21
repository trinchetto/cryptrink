# Backtest Engine - Future Enhancements

This document outlines potential enhancements to the backtesting engine for future development.

## Database Persistence for Backtest Results

### Overview
Add optional database persistence for backtest results to enable historical comparison and analysis of strategy performance across multiple runs.

### Implementation Plan

**1. Database Model**
```python
# New table: backtest_results
CREATE TABLE backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id TEXT NOT NULL UNIQUE,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    result_json TEXT NOT NULL,  -- Full BacktestResult serialized as JSON
    created_at INTEGER NOT NULL
);
```

**2. Repository Layer**
```python
# src/cryptrink/backtest/repository.py
class BacktestResultRepository:
    """Repository for persisting backtest results to database."""

    async def save_result(self, result: BacktestResult) -> str:
        """Save backtest result to database."""
        pass

    async def load_result(self, result_id: str) -> BacktestResult:
        """Load backtest result from database."""
        pass

    async def list_results(
        self,
        strategy_name: str | None = None,
        symbol: str | None = None,
        limit: int = 100
    ) -> list[BacktestResult]:
        """List saved backtest results with optional filtering."""
        pass
```

**3. BacktestResult Method**
```python
async def save_to_db(self, session_factory: async_sessionmaker) -> str:
    """Save backtest result to database for future analysis.

    Returns:
        result_id: Unique identifier for the saved result.
    """
    from cryptrink.backtest.repository import BacktestResultRepository

    repo = BacktestResultRepository(session_factory)
    return await repo.save_result(self)
```

**4. Migration**
```bash
# Create migration
alembic revision -m "add_backtest_results_table"

# Apply migration
alembic upgrade head
```

### Use Cases

1. **Historical Comparison**: Compare strategy performance across different time periods
2. **Parameter Optimization**: Track results of parameter sweeps
3. **Strategy Evolution**: Monitor how strategy changes affect performance over time
4. **Reporting**: Generate reports comparing multiple strategies

### Current Workaround

Users can already serialize results using `BacktestResult.to_dict()`:

```python
import json

# Run backtest
result = await engine.run(...)

# Save to file
with open("backtest_result.json", "w") as f:
    json.dump(result.to_dict(), f, indent=2)

# Load from file
with open("backtest_result.json", "r") as f:
    result_dict = json.load(f)
```

---

## Strategy Signal Integration

### Current State
The BacktestEngine currently processes candles through TradingEngine, which generates HOLD signals internally. Real strategy signals are not executed during backtest.

### Implementation Required
See TODO in [src/cryptrink/backtest/engine.py:201-209](../src/cryptrink/backtest/engine.py#L201-L209):

1. Enable DataFrame conversion in the event loop
2. Build StrategyContext from historical data up to current candle
3. Call `strategy.generate_signal(context)` to get actual signals
4. Pass signal to TradingEngine for execution

### Infrastructure Ready
- `_build_strategy_context()` method is already implemented
- `_build_dataframe()` method is already implemented
- All three real strategies (SMA Crossover, RSI Mean Reversion, Bollinger Bands) are tested and ready

**Blocked by:** TradingEngine needs to be updated to accept pre-generated signals instead of generating them internally.

---

## Advanced Slippage Models

### Volume-Based Slippage
```python
class VolumeBasedSlippageModel(SlippageModel):
    """Slippage based on order size relative to candle volume."""

    def apply_slippage(
        self,
        price: Decimal,
        signal: Signal,
        order_side: OrderSide,
        order_quantity: Decimal,
        candle_volume: Decimal,
    ) -> Decimal:
        # Higher slippage for larger orders relative to volume
        volume_impact = order_quantity / candle_volume
        slippage_pct = self.base_slippage * (1 + volume_impact)
        # ...
```

### Bid-Ask Spread Simulation
```python
class BidAskSpreadModel(SlippageModel):
    """Realistic bid-ask spread simulation."""

    def __init__(self, spread_bps: Decimal = Decimal("0.0010")):
        self.spread_bps = spread_bps

    def apply_slippage(
        self,
        price: Decimal,
        signal: Signal,
        order_side: OrderSide,
    ) -> Decimal:
        # Buy at ask, sell at bid
        half_spread = price * self.spread_bps / 2
        if order_side == OrderSide.BUY:
            return price + half_spread  # Ask price
        else:
            return price - half_spread  # Bid price
```

---

## Multi-Timeframe Support

### Goal
Enable strategies that use multiple timeframes (e.g., daily trend + hourly entry).

### Implementation
```python
class MultiTimeframeBacktestEngine(BacktestEngine):
    """Backtest engine supporting multiple timeframes."""

    async def run(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        primary_timeframe: str = "1h",
        additional_timeframes: dict[str, int] = None,
    ) -> BacktestResult:
        # Load data for all timeframes
        # Synchronize candles across timeframes
        # Build multi-timeframe StrategyContext
        # ...
```

---

## Walk-Forward Analysis

### Goal
Optimize strategy parameters on one period, test on the next period, rolling forward through time.

### Implementation
```python
class WalkForwardAnalyzer:
    """Perform walk-forward analysis for strategy optimization."""

    async def run(
        self,
        strategy_factory: Callable[..., BaseStrategy],
        parameter_grid: dict[str, list],
        in_sample_days: int = 90,
        out_sample_days: int = 30,
        total_days: int = 365,
    ) -> WalkForwardResult:
        # Split data into in-sample/out-sample periods
        # Optimize on in-sample
        # Test on out-sample
        # Roll forward
        # ...
```

---

## Monte Carlo Simulation

### Goal
Assess strategy robustness by randomizing trade sequence.

### Implementation
```python
class MonteCarloSimulator:
    """Monte Carlo simulation of trade sequences."""

    def simulate(
        self,
        trades: list[Position],
        num_simulations: int = 1000,
    ) -> MonteCarloResult:
        # Randomize trade order
        # Calculate equity curves
        # Generate distribution of outcomes
        # ...
```

---

## Short Selling Support

### Current State
Only long positions are supported.

### Implementation Required
1. Update BacktestExecutor to handle short positions
2. Add margin requirements calculation
3. Add borrowing fee simulation
4. Update position tracking for short P&L

---

## Implementation Priority

1. **High Priority**: Strategy Signal Integration (blocked by TradingEngine update)
2. **Medium Priority**: Database Persistence (nice-to-have for analysis)
3. **Medium Priority**: Advanced Slippage Models (improves realism)
4. **Low Priority**: Multi-Timeframe Support (enables more strategies)
5. **Low Priority**: Walk-Forward Analysis (for optimization)
6. **Low Priority**: Monte Carlo Simulation (for robustness testing)
7. **Low Priority**: Short Selling Support (expands strategy types)
