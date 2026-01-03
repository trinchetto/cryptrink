# Cryptrink Wiki

Welcome to the Cryptrink documentation wiki! This wiki contains design decisions, project planning, and development documentation for the crypto trading agent.

## Quick Links

- [Project Plan](Project-Plan) - Implementation roadmap and milestones
- [Architecture](Architecture) - System design and component overview
- [Strategies](Strategies) - Trading strategy documentation
- [Revolut X Integration](Revolut-X-Integration) - Exchange API details
- [Deployment](Deployment) - Deployment options and configuration
- [Development Guide](Development-Guide) - Contributing and development setup

## Project Overview

Cryptrink is a crypto trading agent designed for [Revolut X](https://www.revolut.com/business/revolut-x/) that supports:

- **Multiple Trading Strategies**: Trend following, mean reversion, and market-making
- **Backtesting**: Test strategies against historical data
- **Paper Trading**: Simulate trades without real money
- **Live Trading**: Execute real trades with risk management
- **Trade Suggestions**: Get recommendations without auto-execution

## Current Status

**Version**: 0.1.0 (MVP in development)

### Completed
- Project structure and packaging (Poetry)
- Configuration management (pydantic-settings)
- Abstract interfaces (Exchange, Strategy, DataFeed)
- Development tooling (ruff, mypy, pytest, pre-commit)
- CLI framework (typer)
- Logging infrastructure (structlog)

### In Progress
- Revolut X API integration
- Data feed implementation
- Basic trading strategies

### Planned
- Backtesting engine
- Risk management module
- Telegram notifications
- Performance metrics and reporting

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12+ |
| Package Manager | Poetry |
| HTTP Client | httpx |
| Data Processing | pandas, numpy |
| Technical Analysis | pandas-ta |
| Database | SQLite (dev) / PostgreSQL (prod) |
| CLI | typer, rich |
| Logging | structlog |
| Testing | pytest, respx |
| Linting | ruff, mypy |
