# Cryptrink

![CI](https://github.com/trinchetto/cryptrink/actions/workflows/ci.yml/badge.svg)
![Coverage](.github/badges/coverage.svg)

A crypto trading agent for [Revolut X](https://www.revolut.com/business/revolut-x/) with backtesting and multiple strategy support.

## Project Status

**Phase 4 - Strategy Framework: COMPLETE ✅**

- Base strategy framework with Signal, SignalType, SignalStrength
- Strategy registry for dynamic strategy loading
- Three implemented strategies:
  - SMA Crossover (trend following)
  - RSI Mean Reversion
  - Bollinger Bands Mean Reversion
- Comprehensive strategy testing (7 new test modules)
- Strategy context with OHLCV data and position information

**Previous Phases:**
- ✅ Phase 1 - Foundation (Core Infrastructure)
- ✅ Phase 2 - Revolut X Integration (42 unit tests, 9 integration tests)
- ✅ Phase 3 - Data & Indicators (67 tests)
- ✅ Phase 4 - Strategy Framework (strategy base class + 3 strategies)

**Next Phase**: Phase 5 - Trading Engine

See the [Project Plan](docs/wiki/Project-Plan.md) for detailed roadmap.

## Features

### Implemented ✅
- **Revolut X Integration**: Direct API integration with Ed25519 authentication
- **Market Data**: Real-time ticker, orderbook, trades, and symbol information
- **Account Management**: Balance queries and order status tracking
- **Data Storage**: SQLite database with async operations and Decimal precision
- **OHLCV Aggregation**: Convert raw trades to candlesticks (7 timeframes)
- **Technical Indicators**: SMA, EMA, RSI, Bollinger Bands, MACD, ATR
- **Data Feeds**: Live, historical, and hybrid data access patterns
- **Trading Strategies**: Three implemented strategies
  - SMA Crossover (trend following)
  - RSI Mean Reversion
  - Bollinger Bands Mean Reversion
- **Strategy Framework**: Base classes, signal generation, and strategy registry

### Planned 🚧
- **Trading Engine**: Order execution and position management
- **Backtesting Engine**: Test strategies against historical data
- **Multiple Execution Modes**: live, paper, backtest, suggest
- **Risk Management**: Position sizing, stop-loss, take-profit, circuit breakers
- **Notifications**: Discord alerts for trade execution and signals
- **Additional Strategies**: Market-making and more advanced strategies

## Prerequisites

- Python 3.13+
- Poetry for dependency management
- OpenSSL (for generating Ed25519 keys)
- Revolut X account with API access

## Installation

Clone the repository and install dependencies:

git clone https://github.com/trinchetto/cryptrink.git
cd cryptrink
poetry install

## Quick Start

See [Getting Started](docs/GETTING_STARTED.md) for detailed setup instructions.

## Documentation

- [Getting Started Guide](docs/GETTING_STARTED.md) - Complete setup instructions
- [Revolut X Integration](docs/REVOLUTX_INTEGRATION.md) - API documentation and examples
- [Project Wiki](docs/wiki/Home.md) - Project overview and status
- [Architecture Design](docs/wiki/Architecture.md) - System architecture
- [Project Plan](docs/wiki/Project-Plan.md) - Implementation roadmap
- [Strategy Documentation](docs/wiki/Strategies.md) - Trading strategies guide
- [Development Guide](docs/wiki/Development-Guide.md) - Contributing and development setup
- [Deployment Guide](docs/wiki/Deployment.md) - Production deployment options

## Development

poetry install
poetry run pre-commit install
poetry run pytest
poetry run pytest --cov=src/cryptrink --cov-report=html
poetry run ruff check src/ tests/
poetry run mypy src/

## Security

- Never commit `.env.local`, `*.pem`, or `*.key` files
- Store PEM files in the `secrets/` directory (gitignored)
- Use GitHub Secrets for CI/CD
- Use `CRYPTRINK_EXECUTION_MODE=paper` for testing

## Important Notes

- **Production Environment Only**: Revolut X does not provide a test environment
- **Paper Trading Mode**: Always test with paper mode before live trading
- **Rate Limits**: Be aware of API rate limits

## License

MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This software is for educational and research purposes only. Cryptocurrency trading involves substantial risk of loss. Use at your own risk.
