# Cryptrink Wiki

Welcome to the Cryptrink documentation wiki! This wiki contains design decisions, project planning, and development documentation for the crypto trading agent.

## Quick Links

- [Getting Started](../GETTING_STARTED.md) - Complete setup instructions
- [Revolut X Integration](../REVOLUTX_INTEGRATION.md) - API documentation and examples
- [Project Plan](Project-Plan.md) - Implementation roadmap and milestones
- [Architecture](Architecture.md) - System design and component overview
- [Deployment](Deployment.md) - Deployment options and configuration
- [Development Guide](Development-Guide.md) - Contributing and development setup
- [Strategies](Strategies.md) - Trading strategy documentation

## Project Overview

Cryptrink is a crypto trading agent designed for [Revolut X](https://www.revolut.com/business/revolut-x/) that supports:

- **Multiple Trading Strategies**: Trend following, mean reversion, and market-making
- **Backtesting**: Test strategies against historical data
- **Paper Trading**: Simulate trades without real money
- **Live Trading**: Execute real trades with risk management
- **Trade Suggestions**: Get recommendations without auto-execution

## Current Status

**Version**: 0.1.0 (MVP in development)

### Phase 1: Foundation ✅ COMPLETE
- Project structure and packaging (Poetry)
- Configuration management (pydantic-settings)
- Abstract interfaces (Exchange, Strategy, DataFeed)
- Development tooling (ruff, mypy, pytest, pre-commit)
- CLI framework (typer)
- Logging infrastructure (structlog)

### Phase 2: Revolut X Integration ✅ COMPLETE
- Ed25519 authentication
- REST API client with httpx
- Rate limiting and retry logic
- All market data endpoints (ticker, orderbook, trades, symbols)
- Account endpoints (balances)
- Order endpoints (read-only: open orders, order history)
- 42 unit tests + 9 integration tests

### Phase 3: Data & Indicators ✅ COMPLETE
- SQLite storage with async SQLAlchemy 2.0
- OHLCV aggregation from raw trades (7 timeframes)
- Technical indicators: SMA, EMA, RSI, Bollinger Bands, MACD, ATR
- Data feed abstraction: LiveDataFeed, HistoricalDataFeed, HybridDataFeed
- Decimal precision for financial data
- Pandas integration for efficient calculations
- 67 tests (170 total tests passing)

### Phase 4: Strategy Framework 🚧 NEXT
- Strategy base class enhancements
- SMA Crossover strategy (trend following)
- RSI Mean Reversion strategy
- Signal confidence scoring
- Strategy parameter optimization hooks

### Future Phases
- Trading engine with order management
- Risk management module
- Backtesting engine
- Discord notifications
- Performance metrics and reporting

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.13+ |
| Package Manager | Poetry |
| HTTP Client | httpx |
| Data Processing | pandas, numpy |
| Technical Analysis | Custom pandas-based indicators |
| Database | SQLAlchemy 2.0 + SQLite (dev) / PostgreSQL (prod) |
| CLI | typer, rich |
| Logging | structlog |
| Testing | pytest, respx |
| Linting | ruff, mypy |
