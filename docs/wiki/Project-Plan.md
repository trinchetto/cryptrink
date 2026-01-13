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

## Phase 3: Data & Indicators - IN PROGRESS

### Objectives
Implement data storage, historical data fetching, and technical indicators.

### Deliverables
- [x] Historical data fetcher from Revolut X (HistoricalDataFetcher, OHLCVAggregator)
- [x] SQLite storage for OHLCV data (OHLCV model, OHLCVRepository)
- [x] OHLCV aggregation from tick data (7 timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d)
- [x] Core technical indicators:
  - [x] SMA (Simple Moving Average)
  - [x] EMA (Exponential Moving Average)
  - [x] RSI (Relative Strength Index)
  - [x] Bollinger Bands
  - [x] ATR (Average True Range)
  - [x] MACD
- [x] Data feed abstraction (live vs historical):
  - [x] BaseDataFeed abstract interface
  - [x] LiveDataFeed (real-time from exchange)
  - [x] HistoricalDataFeed (from database)
  - [x] HybridDataFeed (intelligent source selection)
- [ ] Caching layer for indicator values

### Files Created ✅
```
src/cryptrink/data/
├── storage.py         # SQLAlchemy models and repository (307 lines, 15 tests)
├── historical.py      # Historical data fetcher (256 lines, 17 tests)
├── indicators.py      # Technical indicators (237 lines, 24 tests)
└── feed.py            # Data feed abstraction (287 lines, 11 tests)
```

### Files to Create
```
src/cryptrink/data/
└── cache.py           # Indicator caching

src/cryptrink/signals/
├── generator.py       # Signal generation
```

### Test Coverage
- 67 tests for Phase 3 components
- All 170 total tests passing

---

## Phase 4: Strategy Framework

### Objectives
Implement the strategy execution framework and basic strategies.

### Deliverables
- [ ] Strategy base class enhancements
- [ ] Strategy registry and loader
- [ ] SMA Crossover strategy (trend following)
- [ ] RSI Mean Reversion strategy
- [ ] Bollinger Bands strategy
- [ ] Basic Market Making strategy
- [ ] Signal confidence scoring
- [ ] Strategy parameter optimization hooks

### Files to Create
```
src/cryptrink/strategies/
├── registry.py            # Strategy registration
├── trend_following.py     # SMA crossover, breakout
├── mean_reversion.py      # RSI, Bollinger Bands
└── market_making.py       # Spread capture
```

### Strategy Parameters (Examples)

**SMA Crossover**
- `fast_period`: 10
- `slow_period`: 30
- `signal_threshold`: 0.001

**RSI Mean Reversion**
- `period`: 14
- `overbought`: 70
- `oversold`: 30

---

## Phase 5: Trading Engine

### Objectives
Build the core trading loop with order management and position tracking.

### Deliverables
- [ ] Main trading loop with state machine
- [ ] Order manager:
  - [ ] Order lifecycle management
  - [ ] Fill tracking
  - [ ] Partial fill handling
- [ ] Position tracker:
  - [ ] Current positions
  - [ ] P&L calculation
  - [ ] Position history
- [ ] Execution modes:
  - [ ] Live (real orders)
  - [ ] Paper (simulated)
  - [ ] Suggest (no execution)
- [ ] State persistence (survive restarts)
- [ ] Error recovery and reconciliation

### Files to Create
```
src/cryptrink/core/
├── engine.py          # Main trading loop
├── state.py           # Position and state management
├── mode.py            # Execution mode handlers
└── order_manager.py   # Order lifecycle
```

---

## Phase 6: Risk Management

### Objectives
Implement risk controls and position sizing.

### Deliverables
- [ ] Position sizing algorithms:
  - [ ] Fixed fractional
  - [ ] Kelly criterion
  - [ ] Volatility-based
- [ ] Risk controls:
  - [ ] Maximum position size
  - [ ] Maximum daily loss
  - [ ] Maximum drawdown
  - [ ] Per-trade stop loss
  - [ ] Take profit levels
- [ ] Circuit breakers:
  - [ ] Trading pause on loss limits
  - [ ] Volatility-based pauses
- [ ] Risk metrics calculation

### Files to Create
```
src/cryptrink/risk/
├── position_sizer.py      # Position sizing
├── circuit_breaker.py     # Stop trading conditions
└── metrics.py             # Risk metrics
```

---

## Phase 7: Backtesting

### Objectives
Build a realistic backtesting engine with performance analysis.

### Deliverables
- [ ] Backtesting engine:
  - [ ] Event-driven simulation
  - [ ] Historical data replay
- [ ] Realistic execution simulation:
  - [ ] Slippage modeling
  - [ ] Fee calculation
  - [ ] Partial fills
- [ ] Performance metrics:
  - [ ] Total return
  - [ ] Sharpe ratio
  - [ ] Sortino ratio
  - [ ] Maximum drawdown
  - [ ] Win rate
  - [ ] Profit factor
- [ ] Visualization and reporting
- [ ] Strategy comparison

### Files to Create
```
src/cryptrink/backtest/
├── engine.py          # Backtesting orchestrator
├── simulation.py      # Market simulation
├── metrics.py         # Performance metrics
└── report.py          # Report generation
```

---

## Phase 8: CLI & User Experience

### Objectives
Complete the CLI interface and add notifications.

### Deliverables
- [ ] CLI commands:
  - [ ] `run` - Start trading agent
  - [ ] `backtest` - Run backtests
  - [ ] `suggest` - Get trade suggestions
  - [ ] `status` - Show current status
  - [ ] `history` - View trade history
- [ ] Trade suggestion output (table/JSON)
- [ ] Discord notifications:
  - [ ] Trade execution alerts
  - [ ] Daily summary
  - [ ] Error notifications
- [ ] Interactive mode (optional)

### Files to Create
```
src/cryptrink/notifications/
└── discord.py        # Discord webhook integration
```

---

## Phase 9: Packaging & Deployment

### Objectives
Prepare for production deployment.

### Deliverables
- [ ] Finalize pyproject.toml for PyPI
- [ ] Docker image optimization
- [ ] Docker Compose for local development
- [ ] Cloud deployment options:
  - [ ] GCE VM guide
  - [ ] Cloud Run guide
  - [ ] Fly.io guide
- [ ] GitHub Actions:
  - [ ] CI/CD pipeline
  - [ ] Automated releases
- [ ] Production documentation

### Files to Create
```
docker-compose.yml
.github/workflows/
├── ci.yml
└── release.yml
```

---

## Future Enhancements (Post-MVP)

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
