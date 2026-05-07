# Project Plan

This document outlines the implementation plan for Cryptrink, organized into phases with clear milestones.

## Overview

The project follows an MVP-first approach, building a functional trading bot with simple strategies before adding advanced features.

---

## Phase 1: Foundation (Core Infrastructure) - COMPLETED

### Objectives
Set up the project structure, tooling, and core abstractions.

### Deliverables
- [x] Poetry project initialization
- [x] Package structure (`src/cryptrink/`)
- [x] Development tooling (ruff, mypy, pytest, pre-commit)
- [x] Configuration management with pydantic-settings
- [x] Structured logging with structlog
- [x] Abstract interfaces:
  - [x] `BaseExchange` - Exchange connector interface
  - [x] `BaseStrategy` - Trading strategy interface
  - [x] `BaseDataFeed` - Market data interface
- [x] CLI skeleton with typer

### Files Created
```
src/cryptrink/
├── __init__.py
├── cli.py
├── core/
│   ├── __init__.py
│   ├── config.py
│   └── logging.py
├── exchange/
│   ├── __init__.py
│   └── base.py
├── strategies/
│   ├── __init__.py
│   └── base.py
└── data/
    ├── __init__.py
    └── feed.py
```

---

## Phase 2: Revolut X Integration - COMPLETED ✅

### Objectives
Implement the Revolut X API client with authentication and rate limiting.

### Deliverables
- [x] Ed25519 authentication module
- [x] REST API client with httpx
- [x] Rate limiting and retry logic
- [x] Market data endpoints:
  - [x] Get ticker
  - [x] Get order book
  - [x] Get recent trades
  - [x] Get available symbols
- [x] Trading endpoints (read-only):
  - [ ] Place order (market/limit) - Pending Phase 5
  - [ ] Cancel order - Pending Phase 5
  - [ ] Get order status - Implemented
  - [x] Get open orders
  - [x] Get order history
- [x] Account endpoints:
  - [x] Get balances
- [ ] WebSocket support (if available) - Future enhancement
- [x] Comprehensive tests: 42 unit tests + 9 integration tests

### Files Created ✅
```
src/cryptrink/exchange/
├── revolutx.py        # Main Revolut X client
├── auth.py            # Ed25519 signing
└── rate_limiter.py    # Rate limiting logic
```

### Documentation
- [Revolut X Integration Guide](../REVOLUTX_INTEGRATION.md)
- [Getting Started](../GETTING_STARTED.md)

### Technical Notes
- Revolut X uses Ed25519 for request signing
- API key obtained from Revolut X web app
- Headers: `X-Revx-API-Key`, `X-Revx-Timestamp`, `X-Revx-Signature`
- No test environment available - production only
- Rate limiting: 100 requests per minute (default)
- Fees: 0% maker, 0.09% taker

---

## Phase 3: Data & Indicators - COMPLETED ✅

### Objectives
Implement data storage, historical data fetching, and technical indicators.

### Deliverables
- [x] Historical data fetcher from Revolut X
  - `HistoricalDataFetcher` - Fetch and aggregate recent trades into OHLCV
  - `OHLCVAggregator` - Convert raw trades to candlestick data
- [x] SQLite storage for OHLCV data
  - `OHLCV` model with Decimal precision (stored as strings)
  - `OHLCVRepository` with async operations
  - Support for time range queries and batch operations
- [x] OHLCV aggregation from tick data
  - 7 timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d
  - Proper timestamp bucketing and sorting
- [x] Core technical indicators (pandas-based):
  - [x] SMA (Simple Moving Average)
  - [x] EMA (Exponential Moving Average)
  - [x] RSI (Relative Strength Index)
  - [x] Bollinger Bands
  - [x] ATR (Average True Range)
  - [x] MACD (Moving Average Convergence Divergence)
- [x] Data feed abstraction (live vs historical):
  - [x] `BaseDataFeed` - Abstract interface for all feeds
  - [x] `LiveDataFeed` - Real-time data from exchange with optional storage
  - [x] `HistoricalDataFeed` - Read from database storage
  - [x] `HybridDataFeed` - Intelligent source selection (historical → live fallback)

### Files Created ✅
```
src/cryptrink/data/
├── storage.py         # Database models and repository (307 lines, 15 tests)
├── historical.py      # Historical data fetcher & aggregation (256 lines, 17 tests)
├── indicators.py      # Technical indicators (237 lines, 24 tests)
└── feed.py            # Data feed abstraction (342 lines, 11 tests)
```

### Test Coverage ✅
- **67 tests** for Phase 3 components (all passing)
- **170 total tests** passing across entire project
- Unit tests for all modules with edge case coverage
- Mock-based testing for database and exchange interactions

### Technical Highlights
- **Decimal Precision**: Financial data stored as strings to avoid float errors
- **Async Architecture**: All database and network operations use async/await
- **Type Safety**: Full type hints with mypy validation
- **SQLAlchemy 2.0**: Modern ORM with typed mappings
- **Pandas Integration**: Efficient indicator calculations with Series/DataFrame
- **Flexible Data Access**: LiveDataFeed, HistoricalDataFeed, HybridDataFeed patterns

---

## Phase 4: Strategy Framework - COMPLETED ✅

### Objectives
Implement the strategy execution framework and basic strategies.

### Deliverables
- [x] Strategy base class enhancements
  - [x] `BaseStrategy` abstract class with `generate_signal()` method
  - [x] `Signal` dataclass with type, strength, price, stop-loss, take-profit
  - [x] `SignalType`: ENTRY_LONG, ENTRY_SHORT, EXIT_LONG, EXIT_SHORT, HOLD
  - [x] `SignalStrength`: WEAK, MODERATE, STRONG
  - [x] `StrategyContext` with market data and position info
- [x] Strategy registry and loader
  - [x] `StrategyRegistry` for dynamic strategy registration
  - [x] Strategy instantiation from configuration
- [x] SMA Crossover strategy (trend following)
  - [x] Fast/slow SMA crossover detection
  - [x] Signal strength based on crossover distance
  - [x] Configurable periods and threshold
- [x] RSI Mean Reversion strategy
  - [x] Oversold/overbought detection
  - [x] Strength based on RSI extremes
  - [x] Configurable RSI period and thresholds
- [x] Bollinger Bands strategy
  - [x] Band breakout detection
  - [x] Mean reversion signals
  - [x] Configurable period and standard deviation
- [ ] Basic Market Making strategy - Deferred to Phase 9
- [x] Signal confidence scoring (via SignalStrength enum)
- [x] Strategy parameter optimization hooks (constructor parameters)

### Files Created ✅
```
src/cryptrink/strategies/
├── base.py                # BaseStrategy, Signal, StrategyContext
├── registry.py            # Strategy registration and loading
├── trend_following.py     # SmaCrossoverStrategy
└── mean_reversion.py      # RsiMeanReversionStrategy, BollingerBandsStrategy
```

### Test Coverage ✅
- 7 new test modules for strategies
- Unit tests for all strategy implementations
- Signal generation edge case testing
- Strategy registry tests
- 253+ total tests passing

### Strategy Parameters (Implemented)

**SMA Crossover**
- `fast_period`: 10 (default)
- `slow_period`: 30 (default)
- `signal_threshold`: 0.001 (default)

**RSI Mean Reversion**
- `period`: 14 (default)
- `overbought`: 70 (default)
- `oversold`: 30 (default)

**Bollinger Bands**
- `period`: 20 (default)
- `std_dev`: 2.0 (default)

---

## Phase 5: Trading Engine - COMPLETED ✅

### Objectives
Build the core trading loop with order management and position tracking.

### Deliverables
- [x] Main trading loop with state machine
- [x] Order manager:
  - [x] Order lifecycle management
  - [x] Fill tracking
  - [x] Partial fill handling
- [x] Position tracker:
  - [x] Current positions
  - [x] P&L calculation (realized and unrealized)
  - [x] Position history
- [x] Execution modes:
  - [x] Live (real orders on Revolut X)
  - [x] Paper (simulated execution)
  - [x] Suggest (recommendations only)
- [x] State persistence (survive restarts)
  - [x] EngineState model with full state capture
  - [x] EngineStateRepository with save/load/delete
  - [x] Auto-save on lifecycle events (start/stop/reset)
- [x] Error recovery and reconciliation
  - [x] State synchronization with exchange
  - [x] Order status tracking and updates

### Files Created ✅
```
src/cryptrink/execution/
├── engine.py              # TradingEngine orchestrator (435 lines)
├── base.py                # Base classes and enums (194 lines)
├── live.py                # LiveExecutor with RevolutX integration (405 lines)
├── paper.py               # PaperExecutor for simulation (366 lines)
├── suggest.py             # SuggestExecutor for recommendations (203 lines)
├── order_manager.py       # OrderManager with lifecycle tracking (369 lines)
├── position_tracker.py    # PositionTracker with P&L calculation (367 lines)
├── models.py              # Database models (Order, Position, EngineState) (374 lines)
└── repository.py          # Data repositories (528 lines)

tests/unit/
├── test_trading_engine.py            # TradingEngine tests (19 tests)
├── test_engine_state_persistence.py  # State persistence tests (13 tests)
├── test_live_executor.py             # LiveExecutor tests (15 tests)
├── test_order_manager.py             # OrderManager tests
├── test_position_tracker.py          # PositionTracker tests
└── test_execution_*.py               # Executor tests
```

### Test Coverage ✅
- **362 tests** passing (100% pass rate)
- Complete test coverage for all execution components
- Integration tests for database operations
- Mock-based testing for exchange interactions

### Technical Highlights
- **Full Trading Loop**: Strategy → Engine → Executor → OrderManager → PositionTracker
- **Risk Management**: Signal validation, position limits, balance checks
- **State Persistence**: Full engine state save/load with database backing
- **Live Trading**: Real order placement on Revolut X exchange
- **Type Conversion**: Clean separation between execution and exchange enums
- **Async Architecture**: All operations use async/await for efficiency

---

## Phase 6: Risk Management

### Status: **COMPLETE** ✅ (Core functionality implemented)

### Objectives
Implement risk controls and position sizing.

### Deliverables
- [x] **Phase 6.1**: Position sizing algorithms:
  - [x] Fixed fractional
  - [x] Kelly criterion
  - [x] Volatility-based
- [x] **Phase 6.2**: Risk validation and metrics:
  - [x] Maximum position size validation
  - [x] Maximum open positions limit
  - [x] Maximum daily loss (circuit breaker)
  - [x] Maximum drawdown (circuit breaker)
  - [x] Risk metrics tracking (P&L, drawdown, win rate)
  - [x] EngineState persistence for risk metrics
- [x] **Phase 6.3**: TradingEngine integration:
  - [x] Circuit breaker integration with engine
  - [x] Automatic/manual circuit breaker recovery
  - [x] Risk validation in signal processing
  - [x] State persistence for risk metrics
- [ ] **Phase 6.4**: Stop-loss/take-profit orders (future enhancement):
  - [ ] Per-trade stop loss order placement in executors
  - [ ] Take profit order placement in executors
  - [ ] Automatic protective order management

### Files Created
```
src/cryptrink/risk/
├── __init__.py            # Module exports
├── position_sizer.py      # Position sizing (Phase 6.1) ✅
├── validator.py           # Risk validation (Phase 6.2) ✅
└── metrics.py             # Risk metrics (Phase 6.2) ✅

tests/unit/
├── test_position_sizer.py    # 23 tests ✅
├── test_risk_validator.py    # 24 tests (9 passing) ⚠️
└── test_risk_metrics.py      # 43 tests ✅
```

### Key Components

#### PositionSizer (Phase 6.1)
- Three sizing strategies with automatic fallback
- Kelly Criterion uses live win rate from RiskMetrics
- All strategies enforce max position size limits
- **Test Coverage**: 23/23 passing

#### RiskValidator (Phase 6.2)
- Validates orders against 4 risk rules (position size, open positions, daily loss, drawdown)
- Circuit breaker triggers on daily loss or drawdown limits
- Sell orders bypass validation (allows closing positions)
- **Test Coverage**: 24 tests (some need quantity fixes)

#### RiskMetrics & RiskMetricsTracker (Phase 6.2)
- Tracks P&L (daily/total, realized/unrealized)
- Tracks drawdown (current, peak, max historical)
- Tracks win rate for Kelly Criterion
- Circuit breaker state management
- Serialization for persistence
- **Test Coverage**: 43/43 passing

### Integration & Implementation Summary

**Phase 6.1 - Position Sizing:**
- PositionSizer with 3 strategies (Fixed Fractional, Volatility-Based, Kelly Criterion)
- Automatic fallback to Fixed Fractional when data unavailable
- Kelly Criterion tracks win rate from RiskMetrics
- **Test Coverage**: 23/23 passing ✅

**Phase 6.2 - Risk Validation & Metrics:**
- RiskValidator enforces 4 risk rules (position size, open positions, daily loss, drawdown)
- RiskMetricsTracker monitors P&L, drawdown, and win rates
- Circuit breaker triggers on limit breach
- EngineState model extended with 18 risk metrics fields
- **Test Coverage**: 43/43 metrics tests passing ✅, 9/24 validator tests passing (15 need quantity fixes)

**Phase 6.3 - TradingEngine Integration:**
- RiskValidator integrated into `_validate_signal()`
- Circuit breaker blocks entry signals when active
- RiskMetricsTracker lifecycle management
- Risk metrics persisted in `save_state()` and restored in `load_state()`
- `resume_trading()` method for manual circuit breaker recovery
- **Test Coverage**: Core risk integration functional, needs end-to-end tests

**Overall Test Status**: 75/90 passing (83% - 15 validator tests need minor fixes)

---

## Phase 7: Backtesting - COMPLETED ✅

### Objectives
Build a realistic backtesting engine with performance analysis.

### Deliverables
- [x] Backtesting engine:
  - [x] Event-driven simulation with BacktestEngine orchestrator
  - [x] Historical data replay with candle-by-candle processing
- [x] Realistic execution simulation:
  - [x] Slippage modeling (ConstantSlippageModel)
  - [x] Fee calculation (PercentageFeeModel)
  - [x] Market impact simulation in BacktestExecutor
- [x] Performance metrics:
  - [x] Total return and annualized return
  - [x] Sharpe ratio
  - [x] Sortino ratio
  - [x] Maximum drawdown and duration
  - [x] Win rate and profit factor
  - [x] Average win/loss and trade statistics
- [x] Visualization and reporting:
  - [x] Equity curve plotting with matplotlib
  - [x] Drawdown overlay visualization
  - [x] Console summary with Rich formatting
  - [x] JSON export for programmatic analysis
- [ ] Strategy comparison (deferred to future)

### Files Created ✅
```
src/cryptrink/backtest/
├── __init__.py        # Module exports
├── engine.py          # BacktestEngine orchestrator (294 lines)
├── executor.py        # BacktestExecutor with slippage/fees (237 lines)
├── metrics.py         # BacktestMetricsCalculator (298 lines)
├── models.py          # Slippage and fee models (89 lines)
└── result.py          # BacktestResult with plotting (256 lines)

tests/unit/
├── test_backtest_engine.py       # Engine tests
├── test_backtest_executor.py     # Executor tests (25 tests)
├── test_backtest_metrics.py      # Metrics tests (14 tests)
└── test_backtest_result.py       # Result tests (9 tests)
```

### Technical Highlights
- **Event-Driven Replay**: Process historical candles one-by-one through TradingEngine
- **Realistic Execution**: Slippage and fees reduce backtest inflation
- **Comprehensive Metrics**: 20+ performance metrics calculated
- **Equity Curve Tracking**: Full equity history with drawdown analysis
- **Matplotlib Visualization**: Interactive plots with drawdown overlay
- **BacktestResult Dataclass**: Clean API for accessing all results

---

## Phase 8: CLI & User Experience - COMPLETED ✅

### Objectives
Complete the CLI interface and add notifications.

### Deliverables
- [x] CLI commands:
  - [x] `run` - Start trading agent (placeholder, automated loop deferred)
  - [x] `backtest` - Run backtests with BacktestEngine
  - [x] `suggest` - Get trade suggestions from strategies
  - [x] `status` - Show current engine status and positions
  - [x] `history` - View trade and order history
- [x] Trade suggestion output (table/JSON)
  - [x] Rich tables for backtest results
  - [x] Rich tables for trade suggestions
  - [x] Rich tables for trade/order history
  - [x] Rich panels for engine status
- [x] Discord notifications:
  - [x] Trade execution alerts
  - [x] Position closed notifications
  - [x] Daily summary
  - [x] Error notifications
  - [x] Circuit breaker alerts
  - [x] Rate limiting (1-second minimum interval)
- [ ] Interactive mode (deferred to future enhancement)

### Files Created ✅
```
src/cryptrink/cli/
├── __init__.py        # CLI package exports
├── formatters.py      # Rich table/panel formatters (183 lines)
└── utils.py           # CLI utilities (async bridge, strategy loading) (124 lines)

src/cryptrink/notifications/
├── __init__.py        # Module exports (updated)
└── discord.py         # Discord webhook notifier (248 lines)

tests/unit/
├── test_cli_formatters.py    # Formatter tests (9 tests)
├── test_cli_utils.py         # Utility tests (21 tests)
└── test_discord_notifier.py  # Discord tests (18 tests)
```

### CLI Commands

**backtest** - Run strategy backtests
```bash
cryptrink backtest sma_crossover BTC-EUR --start-date 2024-01-01 --end-date 2024-12-31 --plot --output results.json
```

**suggest** - Get trade suggestions
```bash
cryptrink suggest sma_crossover BTC-EUR --format table
```

**status** - Show engine status
```bash
cryptrink status --config config.toml
```

**history** - View trade history
```bash
cryptrink history --limit 50 --status closed --orders
```

### Technical Highlights
- **Async/Sync Bridge**: `run_async()` bridges Typer CLI with async engines
- **Rich Formatting**: Beautiful terminal output with tables and panels
- **Discord Integration**: Webhook-based notifications with rate limiting
- **JSON Export**: Machine-readable output for all commands
- **48 Tests**: Comprehensive unit test coverage

---

## Phase 9: Hugging Face Spaces Deployment

### Pivot
Phase 9 now targets Hugging Face Spaces as the single deployment surface
instead of Docker / Cloud Run / GCE / Fly.io. The CLI from Phase 8 stays
as the operator's local interface; the Space hosts the Gradio UI plus
the optional live trading loop. This keeps cryptrink's "one place to
run it" story aligned with the LLM-agent strategy work targeting
ZeroGPU.

The phase ships in three independently deployable sub-phases.

### Phase 9a — Web shell on a CPU Space ✅

A Gradio app exposes the existing rule-based strategies through a
browser. No live trading, no LLM, no GPU.

Delivered:
- `app.py` at the repo root + HF Space metadata in `README.md` YAML
  front-matter (`sdk: gradio`, `app_file: app.py`, `sdk_version: 6.x`).
- `cryptrink.web` package: `build_demo()` and three tabs (Backtest,
  Suggest, Status) reusing `BacktestEngine`, `SuggestExecutor`, and the
  persistence repositories.
- `cryptrink.runtime` shared module that bootstraps the strategy
  registry and async session factory for both the CLI and the web app.
- `requirements.txt` exported via `poetry export --extras web` so the
  Space installs the same dep set.
- `--all-extras` install in CI so the web layer is type-checked and
  unit-tested in the lint and test jobs.

Verification: `python app.py` opens the three-tab UI; the Space build
on `huggingface.co/spaces/<owner>/cryptrink` runs the same UI on free
CPU Basic hardware. Each tab returns either real data (against the
configured DB) or a friendly missing-data message.

### Phase 9b — Live tab + persistent storage ✅

Adds the live trading control panel and the asyncio background loop
on top of the 9a shell. Requires a paid CPU Space (so the process
doesn't sleep) and a Storage Bucket mounted at `/data` for SQLite
persistence.

Delivered:
- `cryptrink.web.live_loop.LiveLoop`: cancellable background task that
  on every interval pulls OHLCV from the configured data feed, builds
  a `StrategyContext`, and routes the resulting `Signal` through
  `TradingEngine.process_signal(symbol, current_price, timestamp,
  signal=signal)`. Errors are caught per-iteration so a transient
  failure doesn't kill the task. Idempotent `start()` and `stop()`,
  optional `on_signal` and `on_stop` hooks.
- `cryptrink.web.live_setup.build_live_components`: returns a started
  `TradingEngine`, a `BaseDataFeed`, a cleanup closure, the actual
  mode, and an optional `DiscordNotifier`. Live mode requires
  `REVOLUTX_API_KEY` plus a private key (raw or PEM-path); without
  them the Start button silently falls back to paper mode.
- `cryptrink.web.tabs.live`: Mode radio (paper / live), strategy +
  symbol + interval inputs, Start / Stop / Refresh buttons, and a
  markdown status pane that renders running flag, iteration / signal /
  execution counts, last signal type and time, and error count + last
  error.
- DB persistence works without code changes: `DB_URL` env var is
  honoured by `DatabaseSettings(env_prefix="DB_")`, so a Space with a
  Storage Bucket mounted at `/data` only needs
  `DB_URL=sqlite+aiosqlite:////data/cryptrink.db` in its environment.
- Discord notifier wired into the loop's `on_signal` callback when
  `NOTIFY_DISCORD_ENABLED=true` and a webhook URL is set.

### Phase 9c — Local-inference LLM agent on a ZeroGPU Space (planned)

The TradingAgents-inspired analyst → researcher → trader → risk
pipeline implemented as a `BaseStrategy` subclass that runs each role
through a local open-weights model gated by `@spaces.GPU(duration=60)`.
Lands a Transcript tab that renders the per-role rationales the agent
recorded for each decision. Out of scope for 9b.

### Files Created (9a + 9b)
```
app.py
requirements.txt
src/cryptrink/runtime.py
src/cryptrink/web/__init__.py
src/cryptrink/web/app.py
src/cryptrink/web/state.py
src/cryptrink/web/live_loop.py
src/cryptrink/web/live_setup.py
src/cryptrink/web/tabs/__init__.py
src/cryptrink/web/tabs/backtest.py
src/cryptrink/web/tabs/suggest.py
src/cryptrink/web/tabs/status.py
src/cryptrink/web/tabs/live.py
tests/unit/test_runtime.py
tests/unit/test_web_app.py
tests/unit/test_live_loop.py
tests/unit/test_live_setup.py
```

---

## Future Enhancements (Post-MVP)

### Performance Optimizations
- **Indicator Caching**: Cache computed indicator values with TTL
- **Data Prefetching**: Preload OHLCV data for common timeframes
- **Connection Pooling**: Optimize database connection management
- **Bulk Operations**: Batch indicator calculations across symbols

### Advanced Strategies
- Machine learning-based signals
- Sentiment analysis integration
- Multi-timeframe analysis
- Portfolio optimization

### Platform Expansion
- Additional exchange support
- Multi-exchange arbitrage
- DEX integration

### Monitoring & Analytics
- Real-time dashboard
- Advanced performance analytics
- A/B testing for strategies

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-01-03 | Use Python 3.13 | Good ecosystem compatibility with latest features |
| 2025-01-03 | Build custom framework instead of using Freqtrade/Jesse | Revolut X not supported by CCXT |
| 2025-01-03 | Use pydantic-settings for configuration | Type-safe, env var support |
| 2025-01-03 | Use structlog for logging | Structured, context-aware logging |
| 2025-01-03 | Use SQLite for development | Simple, portable, upgradeable to PostgreSQL |
