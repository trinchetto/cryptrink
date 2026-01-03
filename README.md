# Cryptrink

A crypto trading agent for [Revolut X](https://www.revolut.com/business/revolut-x/) with backtesting and multiple strategy support.

## Features

- **Multiple Trading Strategies**: Trend following, mean reversion, and market-making strategies
- **Revolut X Integration**: Direct API integration with Ed25519 authentication
- **Backtesting Engine**: Test strategies against historical data before live trading
- **Multiple Execution Modes**:
  - `live`: Execute real trades on Revolut X
  - `paper`: Simulate trades without real money
  - `backtest`: Test against historical data
  - `suggest`: Generate trade suggestions without executing
- **Risk Management**: Position sizing, stop-loss, take-profit, and circuit breakers
- **Notifications**: Telegram alerts for trade execution and signals

## Installation

### Prerequisites

- Python 3.13 or 3.14
- [Poetry](https://python-poetry.org/) for dependency management

### From Source

```bash
# Clone the repository
git clone https://github.com/trinchetto/cryptrink.git
cd cryptrink

# Install dependencies
poetry install

# Install with Telegram support
poetry install --extras telegram

# Activate the virtual environment
poetry shell
```

## Quick Start

### 1. Configure the Agent

Copy the example configuration and update with your settings:

```bash
cp config.example.yaml config.yaml
```

Set your Revolut X API credentials as environment variables:

```bash
export REVOLUTX_API_KEY="your-api-key"
export REVOLUTX_PRIVATE_KEY="your-ed25519-private-key"
```

### 2. Run in Paper Trading Mode

```bash
cryptrink run --mode paper --strategy sma_crossover --symbol BTC-EUR
```

### 3. Backtest a Strategy

```bash
cryptrink backtest sma_crossover BTC-EUR --start 2024-01-01 --capital 10000
```

### 4. Get Trade Suggestions

```bash
cryptrink suggest mean_reversion ETH-EUR --format table
```

## CLI Commands

```bash
# Show help
cryptrink --help

# Run trading agent
cryptrink run [OPTIONS]
  --config, -c    Path to configuration file
  --mode, -m      Execution mode (live/paper/backtest/suggest)
  --strategy, -s  Strategy to run
  --symbol        Trading symbol (e.g., BTC-EUR)

# Run backtest
cryptrink backtest STRATEGY SYMBOL [OPTIONS]
  --start, -s     Start date (YYYY-MM-DD)
  --end, -e       End date (YYYY-MM-DD)
  --capital       Initial capital in EUR

# Get trade suggestions
cryptrink suggest STRATEGY SYMBOL [OPTIONS]
  --format, -f    Output format (table/json)

# Show status
cryptrink status
```

## Available Strategies

| Strategy | Type | Description |
|----------|------|-------------|
| `sma_crossover` | Trend Following | SMA crossover with configurable periods |
| `rsi_reversal` | Mean Reversion | RSI-based overbought/oversold signals |
| `bollinger_bands` | Mean Reversion | Bollinger Bands breakout/mean reversion |
| `spread_capture` | Market Making | Basic spread capture strategy |

## Project Structure

```
cryptrink/
├── src/cryptrink/
│   ├── cli.py              # Command-line interface
│   ├── core/               # Core components
│   │   ├── config.py       # Configuration management
│   │   └── logging.py      # Structured logging
│   ├── exchange/           # Exchange connectors
│   │   └── base.py         # Abstract exchange interface
│   ├── strategies/         # Trading strategies
│   │   └── base.py         # Strategy base class
│   ├── data/               # Data feeds
│   │   └── feed.py         # Data feed interface
│   ├── signals/            # Signal generation
│   ├── risk/               # Risk management
│   ├── backtest/           # Backtesting engine
│   └── notifications/      # Alert notifications
├── tests/                  # Test suite
├── pyproject.toml          # Project configuration
├── config.example.yaml     # Example configuration
└── Dockerfile              # Container deployment
```

## Development

### Setup Development Environment

```bash
# Install all dependencies including dev
poetry install

# Install pre-commit hooks
poetry run pre-commit install

# Run tests
poetry run pytest

# Run tests with coverage
poetry run pytest --cov=src/cryptrink --cov-report=html

# Run linting
poetry run ruff check src/ tests/
poetry run ruff format src/ tests/

# Run type checking
poetry run mypy src/
```

### Running Tests

```bash
# All tests
poetry run pytest

# Unit tests only
poetry run pytest tests/unit/

# Integration tests only
poetry run pytest tests/integration/

# With verbose output
poetry run pytest -v

# Specific test file
poetry run pytest tests/unit/test_config.py
```

## Configuration Reference

Configuration can be provided via:
1. YAML configuration file (`config.yaml`)
2. Environment variables (take precedence)

### Environment Variables

| Variable | Description |
|----------|-------------|
| `REVOLUTX_API_KEY` | Revolut X API key |
| `REVOLUTX_PRIVATE_KEY` | Ed25519 private key for signing |
| `CRYPTRINK_EXECUTION_MODE` | Execution mode |
| `CRYPTRINK_LOG_LEVEL` | Log level (DEBUG/INFO/WARNING/ERROR) |
| `RISK_MAX_POSITION_SIZE_PCT` | Max position size (0.0-1.0) |
| `RISK_MAX_DAILY_LOSS_PCT` | Max daily loss (0.0-1.0) |
| `DB_URL` | Database connection URL |

## Deployment

### Docker

```bash
# Build image
docker build -t cryptrink .

# Run in paper mode
docker run -e REVOLUTX_API_KEY=xxx -e REVOLUTX_PRIVATE_KEY=xxx \
  cryptrink run --mode paper --strategy sma_crossover

# Run with config file
docker run -v $(pwd)/config.yaml:/app/config.yaml \
  cryptrink run --config /app/config.yaml
```

### Cloud Run

See the [Deployment Guide](https://github.com/trinchetto/cryptrink/wiki/Deployment) in the wiki.

## Documentation

- [Project Wiki](https://github.com/trinchetto/cryptrink/wiki)
- [Architecture & Design](https://github.com/trinchetto/cryptrink/wiki/Architecture)
- [Project Plan](https://github.com/trinchetto/cryptrink/wiki/Project-Plan)
- [Strategy Development](https://github.com/trinchetto/cryptrink/wiki/Strategies)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This software is for educational and research purposes. Cryptocurrency trading involves substantial risk of loss. Use at your own risk. The authors are not responsible for any financial losses incurred through the use of this software.
