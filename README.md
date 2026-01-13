# Cryptrink

![CI](https://github.com/trinchetto/cryptrink/actions/workflows/ci.yml/badge.svg)
![Coverage](.github/badges/coverage.svg)

A crypto trading agent for [Revolut X](https://www.revolut.com/business/revolut-x/) with backtesting and multiple strategy support.

## Project Status

**Phase 2 - Revolut X Integration: COMPLETE**

- Revolut X API client with Ed25519 authentication
- All market data endpoints (ticker, orderbook, trades, symbols)
- All account endpoints (balances)
- Order management (read-only: get orders, order history)
- 42 unit tests passing
- 9 integration tests passing
- Production-ready for read-only operations

**Next Phase**: Phase 3 - Data & Indicators

See the [Project Plan](docs/wiki/Project-Plan.md) for detailed roadmap.

## Features

- **Revolut X Integration**: Direct API integration with Ed25519 authentication
- **Multiple Trading Strategies**: Trend following, mean reversion, and market-making strategies (planned)
- **Backtesting Engine**: Test strategies against historical data before live trading (planned)
- **Multiple Execution Modes**: live, paper, backtest, suggest (planned)
- **Risk Management**: Position sizing, stop-loss, take-profit, and circuit breakers (planned)
- **Notifications**: Discord alerts for trade execution and signals (planned)

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
