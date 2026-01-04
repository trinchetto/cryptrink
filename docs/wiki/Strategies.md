# Trading Strategies

This document describes the trading strategies implemented in Cryptrink and how to create custom strategies.

## Strategy Types

Cryptrink supports three main categories of trading strategies:

### 1. Trend Following
Strategies that identify and follow market trends.

- **SMA Crossover**: Uses moving average crossovers
- **Breakout**: Trades breakouts from ranges
- **Momentum**: Follows price momentum

### 2. Mean Reversion
Strategies that bet on prices returning to average.

- **RSI Reversal**: Uses overbought/oversold RSI levels
- **Bollinger Bands**: Trades bounces from bands
- **Statistical Arbitrage**: Pairs trading (future)

### 3. Market Making
Strategies that provide liquidity and capture spreads.

- **Spread Capture**: Basic bid-ask spread capture
- **Inventory Management**: Balances position risk

---

## Implemented Strategies

### SMA Crossover (Trend Following)

**Description**: Generates buy signals when a fast moving average crosses above a slow moving average, and sell signals on the opposite crossover.

**Parameters**:
| Parameter | Default | Description |
|-----------|---------|-------------|
| `fast_period` | 10 | Fast SMA period |
| `slow_period` | 30 | Slow SMA period |
| `signal_threshold` | 0.001 | Minimum crossover distance |

**Signals**:
- **ENTRY_LONG**: Fast SMA crosses above Slow SMA
- **EXIT_LONG**: Fast SMA crosses below Slow SMA
- **HOLD**: No crossover detected

**Example**:
```python
from cryptrink.strategies.trend_following import SMACrossover

strategy = SMACrossover(
    fast_period=10,
    slow_period=30,
    signal_threshold=0.001,
)
```

---

### RSI Mean Reversion

**Description**: Generates buy signals when RSI is oversold and sell signals when RSI is overbought.

**Parameters**:
| Parameter | Default | Description |
|-----------|---------|-------------|
| `rsi_period` | 14 | RSI calculation period |
| `overbought` | 70 | Overbought threshold |
| `oversold` | 30 | Oversold threshold |
| `exit_threshold` | 50 | Exit position threshold |

**Signals**:
- **ENTRY_LONG**: RSI < oversold (e.g., RSI < 30)
- **EXIT_LONG**: RSI > exit_threshold (e.g., RSI > 50)
- **ENTRY_SHORT**: RSI > overbought (e.g., RSI > 70)
- **EXIT_SHORT**: RSI < exit_threshold (e.g., RSI < 50)

**Example**:
```python
from cryptrink.strategies.mean_reversion import RSIMeanReversion

strategy = RSIMeanReversion(
    rsi_period=14,
    overbought=70,
    oversold=30,
)
```

---

### Bollinger Bands

**Description**: Trades based on price position relative to Bollinger Bands, buying at the lower band and selling at the upper band.

**Parameters**:
| Parameter | Default | Description |
|-----------|---------|-------------|
| `period` | 20 | SMA period for middle band |
| `std_dev` | 2.0 | Standard deviation multiplier |
| `entry_threshold` | 0.0 | Distance past band to trigger |

**Signals**:
- **ENTRY_LONG**: Price touches/crosses lower band
- **EXIT_LONG**: Price touches middle or upper band
- **ENTRY_SHORT**: Price touches/crosses upper band
- **EXIT_SHORT**: Price touches middle or lower band

---

### Spread Capture (Market Making)

**Description**: Places limit orders on both sides of the spread to capture the bid-ask difference.

**Parameters**:
| Parameter | Default | Description |
|-----------|---------|-------------|
| `spread_target` | 0.002 | Target spread (0.2%) |
| `max_position` | 0.1 | Max position size (as % of capital) |
| `rebalance_threshold` | 0.05 | Position imbalance to trigger rebalance |

**Note**: Market making requires careful risk management and is not recommended for beginners.

---

## Creating Custom Strategies

### Step 1: Inherit from BaseStrategy

```python
from decimal import Decimal
from cryptrink.strategies.base import (
    BaseStrategy,
    Signal,
    SignalStrength,
    SignalType,
    StrategyContext,
)


class MyCustomStrategy(BaseStrategy):
    """My custom trading strategy."""

    def __init__(self, param1: int = 10, param2: float = 0.5):
        self.param1 = param1
        self.param2 = param2

    @property
    def name(self) -> str:
        return "my_custom_strategy"

    @property
    def description(self) -> str:
        return "A custom strategy that does something unique"

    @property
    def required_history(self) -> int:
        # Number of candles needed for indicators
        return self.param1 + 10

    @property
    def timeframe(self) -> str:
        return "1h"  # Preferred candle timeframe

    def generate_signal(self, context: StrategyContext) -> Signal:
        # Validate we have enough data
        if not self.validate_context(context):
            return self._hold_signal(context)

        # Your strategy logic here
        # Access OHLCV data: context.ohlcv
        # Access current price: context.current_price
        # Check position: context.has_position

        # Example: Simple price comparison
        if self._should_buy(context):
            return Signal(
                signal_type=SignalType.ENTRY_LONG,
                symbol=context.symbol,
                strength=SignalStrength.MODERATE,
                timestamp=context.timestamp,
                price=context.current_price,
                stop_loss=context.current_price * Decimal("0.98"),
                take_profit=context.current_price * Decimal("1.04"),
            )

        return self._hold_signal(context)

    def _should_buy(self, context: StrategyContext) -> bool:
        # Implement your buy logic
        return False

    def _hold_signal(self, context: StrategyContext) -> Signal:
        return Signal(
            signal_type=SignalType.HOLD,
            symbol=context.symbol,
            strength=SignalStrength.WEAK,
            timestamp=context.timestamp,
            price=context.current_price,
        )
```

### Step 2: Register the Strategy

```python
# In src/cryptrink/strategies/registry.py
from cryptrink.strategies.my_custom import MyCustomStrategy

STRATEGIES = {
    "my_custom_strategy": MyCustomStrategy,
    # ... other strategies
}
```

### Step 3: Use in Configuration

```yaml
# config.yaml
default_strategy: my_custom_strategy
```

Or via CLI:
```bash
cryptrink run --strategy my_custom_strategy
```

---

## Strategy Context

The `StrategyContext` provides all information needed for decision making:

```python
@dataclass
class StrategyContext:
    symbol: str                      # Trading pair (e.g., "BTC-EUR")
    current_price: Decimal           # Current market price
    timestamp: datetime              # Current timestamp

    # OHLCV data (pandas DataFrame)
    ohlcv: pd.DataFrame              # Columns: open, high, low, close, volume

    # Current position info
    position_size: Decimal           # Size of current position
    position_side: OrderSide | None  # BUY (long) or SELL (short)
    position_entry_price: Decimal    # Entry price if in position

    # Account info
    available_balance: Decimal       # Available balance in quote currency
    total_equity: Decimal            # Total account equity

    # Order book info (optional)
    orderbook_bid: Decimal | None    # Best bid price
    orderbook_ask: Decimal | None    # Best ask price
```

---

## Signal Strength

Signals have a strength indicator that can influence position sizing:

| Strength | Description | Position Size Multiplier |
|----------|-------------|-------------------------|
| `WEAK` | Low confidence | 0.5x |
| `MODERATE` | Normal confidence | 1.0x |
| `STRONG` | High confidence | 1.5x |

---

## Strategy Lifecycle Hooks

Optional methods you can override:

```python
def on_trade_executed(
    self,
    symbol: str,
    side: OrderSide,
    quantity: Decimal,
    price: Decimal,
    timestamp: datetime,
) -> None:
    """Called when a trade is executed."""
    # Track trades, update internal state, etc.
    pass

def reset(self) -> None:
    """Reset strategy state."""
    # Clear any cached calculations
    pass
```

---

## Best Practices

### 1. Validate Data
Always check you have enough data:
```python
if not self.validate_context(context):
    return self._hold_signal(context)
```

### 2. Use Decimal for Prices
Avoid floating-point precision issues:
```python
stop_loss = context.current_price * Decimal("0.98")
```

### 3. Include Stop Loss / Take Profit
Always set risk levels:
```python
Signal(
    ...,
    stop_loss=entry_price * Decimal("0.98"),
    take_profit=entry_price * Decimal("1.04"),
)
```

### 4. Log Important Decisions
Use structured logging:
```python
from cryptrink.core.logging import get_logger

logger = get_logger(__name__)

def generate_signal(self, context):
    logger.info(
        "generating_signal",
        symbol=context.symbol,
        price=str(context.current_price),
        rsi=rsi_value,
    )
```

### 5. Backtest Thoroughly
Test your strategy against historical data before live trading:
```bash
cryptrink backtest my_strategy BTC-EUR --start 2024-01-01 --capital 10000
```

---

## Strategy Development Workflow

1. **Hypothesis**: Define what market condition you're exploiting
2. **Implementation**: Write the strategy code
3. **Unit Tests**: Test individual components
4. **Backtest**: Test against historical data
5. **Paper Trade**: Test with live data, no real money
6. **Monitor**: Track performance metrics
7. **Iterate**: Refine based on results
