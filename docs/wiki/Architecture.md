# Architecture

This document describes the high-level architecture and design decisions for Cryptrink.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                          CLI (typer)                             │
├─────────────────────────────────────────────────────────────────┤
│                       Trading Engine                             │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │   Strategy  │  │    Order     │  │    Position            │  │
│  │   Manager   │  │   Manager    │  │    Tracker             │  │
│  └──────┬──────┘  └──────┬───────┘  └───────────┬────────────┘  │
│         │                │                      │                │
│  ┌──────▼──────┐  ┌──────▼───────┐  ┌──────────▼────────────┐   │
│  │  Signals    │  │    Risk      │  │    State              │   │
│  │  Generator  │  │   Manager    │  │   Persistence         │   │
│  └─────────────┘  └──────────────┘  └───────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                        Data Layer                                │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  Data Feed  │  │   Storage    │  │    Indicators          │  │
│  │  (Live/Hist)│  │  (SQLite)    │  │    (pandas-ta)         │  │
│  └─────────────┘  └──────────────┘  └────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                      Exchange Layer                              │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Revolut X Client                          ││
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  ││
│  │  │    Auth     │  │ Rate Limiter │  │    HTTP Client     │  ││
│  │  │  (Ed25519)  │  │              │  │      (httpx)       │  ││
│  │  └─────────────┘  └──────────────┘  └────────────────────┘  ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Component Breakdown

### 1. CLI Layer

**Technology**: typer, rich

The CLI provides the user interface for:
- Starting/stopping the trading agent
- Running backtests
- Getting trade suggestions
- Viewing status and history

```python
# Example commands
cryptrink run --mode paper --strategy sma_crossover
cryptrink backtest sma_crossover BTC-EUR --start 2024-01-01
cryptrink suggest mean_reversion ETH-EUR
```

### 2. Trading Engine (🚧 Next Phase)

The core orchestration layer that coordinates all trading activities.

#### Strategy Manager (Partially Implemented)
- **Strategy Framework** (✅): Base classes, signal generation
- **Strategy Registry** (✅): Dynamic strategy loading
- **Implemented Strategies** (✅):
  - SMA Crossover (trend following)
  - RSI Mean Reversion
  - Bollinger Bands Mean Reversion
- **Strategy Execution Loop** (⏸️): Pending Phase 5

#### Order Manager (⏸️ Pending Phase 5)
- Tracks order lifecycle (pending → open → filled/cancelled)
- Handles partial fills
- Maintains order history

#### Position Tracker (⏸️ Pending Phase 5)
- Tracks current positions per symbol
- Calculates unrealized P&L
- Provides position sizing context

#### State Persistence (⏸️ Pending Phase 5)
- Saves state to database for crash recovery
- Supports idempotent order placement
- Reconciles with exchange on restart

### 3. Data Layer

#### Data Feed (✅ Implemented)
Abstract `BaseDataFeed` interface with three implementations:
- **LiveDataFeed**: Real-time data from Revolut X with optional storage
- **HistoricalDataFeed**: Query stored OHLCV data from database
- **HybridDataFeed**: Intelligent source selection (historical → live fallback)

All feeds support async operations and provide OHLCV data as pandas DataFrames.

#### Storage (✅ Implemented)
SQLAlchemy 2.0 async ORM with repository pattern:
- **OHLCV Model**: Stores candlestick data with Decimal precision
- **OHLCVRepository**: Async operations for data access
  - Time range queries
  - Batch insert operations
  - Symbol-based filtering
- **Database**: SQLite for development, PostgreSQL-ready for production
- **Decimal Storage**: Financial data stored as strings to avoid float errors

#### Indicators (✅ Implemented)
Custom pandas-based technical analysis (`src/cryptrink/data/indicators.py`):
- **Moving averages**: SMA, EMA
- **Oscillators**: RSI
- **Volatility**: Bollinger Bands, ATR
- **Trend**: MACD

All indicators implemented as static methods returning pandas Series for efficient vectorized calculations.

#### Historical Data (✅ Implemented)
OHLCV aggregation from raw trades:
- **HistoricalDataFetcher**: Fetch recent trades and aggregate to OHLCV
- **OHLCVAggregator**: Convert tick data to candlesticks
- **Supported Timeframes**: 1m, 5m, 15m, 30m, 1h, 4h, 1d
- **Proper Bucketing**: Timestamp alignment and sorting

### 4. Exchange Layer

#### Revolut X Client
The exchange connector implementing `BaseExchange`:

```python
class RevolutXExchange(BaseExchange):
    async def get_ticker(self, symbol: str) -> Ticker
    async def get_orderbook(self, symbol: str) -> OrderBook
    async def create_order(...) -> Order
    async def cancel_order(order_id: str) -> Order
    async def get_balances() -> dict[str, Balance]
```

#### Authentication
Ed25519 signature for each request:
```
Headers:
  X-Revx-Api-Key: <api-key>
  X-Revx-Timestamp: <unix-timestamp>
  X-Revx-Signature: <ed25519-signature>
```

#### Rate Limiting
- Tracks request counts per endpoint
- Implements exponential backoff
- Respects `Retry-After` headers

## Design Patterns

### 1. Abstract Base Classes (✅ Implemented)

All major components define abstract interfaces:

```python
# Exchange interface
class BaseExchange(ABC):
    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker: ...
    @abstractmethod
    async def get_orderbook(self, symbol: str) -> OrderBook: ...
    @abstractmethod
    async def get_balances(self) -> dict[str, Balance]: ...
    # ... more methods

# Strategy interface
class BaseStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def generate_signal(self, context: StrategyContext) -> Signal: ...

# Data feed interface
class BaseDataFeed(ABC):
    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame: ...
```

**Benefits**:
- Exchange abstraction (currently Revolut X, can add others)
- Strategy abstraction (3 strategies implemented, easy to add more)
- Data feed abstraction (live, historical, hybrid implementations)
- Paper trading (mock exchange - future)
- Backtesting (historical data feed - future)

### 2. Async/Await Throughout

All I/O operations are async:
- HTTP requests to exchange
- Database operations
- WebSocket connections

Benefits:
- Efficient concurrent operations
- Non-blocking data fetching
- Better resource utilization

### 3. Immutable Data Classes

Market data uses frozen dataclasses:

```python
@dataclass(frozen=True)
class Ticker:
    symbol: str
    bid: Decimal
    ask: Decimal
    ...
```

Benefits:
- Thread-safe by design
- No accidental mutations
- Clear data contracts

### 4. Decimal for Financial Data

All prices and quantities use `Decimal`:

```python
from decimal import Decimal

price = Decimal("42000.50")
quantity = Decimal("0.001")
```

Avoids floating-point precision issues.

## Execution Modes

### Live Mode
- Real orders on Revolut X
- Real money at risk
- Full risk management active

### Paper Mode
- Simulated execution
- Tracks virtual positions
- Uses real market data

### Backtest Mode
- Historical data replay
- Simulated fills with slippage
- Performance analysis

### Suggest Mode
- Generates signals only
- No order execution
- Outputs recommendations

## Data Flow

### Signal Generation Flow

```
1. Data Feed provides OHLCV data
         ↓
2. Indicators calculate technical values
         ↓
3. Strategy generates Signal
         ↓
4. Risk Manager validates signal
         ↓
5. Position Sizer determines quantity
         ↓
6. Order Manager creates order
         ↓
7. Exchange executes order
         ↓
8. Position Tracker updates state
```

### Order Lifecycle

```
PENDING → OPEN → PARTIALLY_FILLED → FILLED
    ↓         ↓              ↓
    └─→ CANCELLED ←──────────┘
    ↓
    └─→ REJECTED
```

## Configuration

Layered configuration with precedence:

1. Environment variables (highest)
2. Configuration file (config.yaml)
3. Default values (lowest)

```yaml
# config.yaml
execution_mode: paper
symbols:
  - BTC-EUR
  - ETH-EUR

risk:
  max_position_size_pct: 0.1
  max_daily_loss_pct: 0.05
```

## Error Handling

### Exchange Errors
- `RateLimitError`: Exponential backoff, retry
- `AuthenticationError`: Log and stop
- `InsufficientFundsError`: Skip trade, alert
- `OrderNotFoundError`: Reconcile state

### Strategy Errors
- Catch all exceptions in strategy execution
- Log error with full context
- Continue with other symbols

### Circuit Breakers
- Max daily loss reached → pause trading
- Max drawdown reached → pause trading
- Consecutive errors → pause and alert

## Testing Strategy

### Unit Tests
- Strategy logic
- Indicator calculations
- Configuration parsing
- Data transformations

### Integration Tests
- Exchange client with mocked responses
- Database operations
- CLI commands

### Backtesting Tests
- Strategy performance on known data
- Edge cases (gaps, splits, etc.)
- Comparison with expected results

## Security Considerations

### API Key Protection
- Never commit API keys
- Use environment variables
- Encrypt at rest if stored

### Request Signing
- Ed25519 signatures prevent tampering
- Timestamp prevents replay attacks
- Per-request nonce (if supported)

### Input Validation
- Validate all user inputs
- Sanitize configuration values
- Limit order sizes in risk management
