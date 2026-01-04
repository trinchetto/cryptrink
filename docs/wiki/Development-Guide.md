# Development Guide

This guide covers setting up a development environment and contributing to Cryptrink.

## Development Setup

### Prerequisites

- Python 3.12 or 3.13
- [Poetry](https://python-poetry.org/) 2.0+
- Git

### Clone and Install

```bash
# Clone the repository
git clone https://github.com/trinchetto/cryptrink.git
cd cryptrink

# Install all dependencies (including dev)
poetry install

# Activate the virtual environment
poetry shell

# Verify installation
cryptrink --version
```

### Install Pre-commit Hooks

```bash
# Install hooks
poetry run pre-commit install

# Run hooks manually
poetry run pre-commit run --all-files
```

---

## Project Structure

```
cryptrink/
├── src/cryptrink/          # Main package
│   ├── __init__.py         # Package init, version
│   ├── cli.py              # CLI commands (typer)
│   ├── core/               # Core components
│   │   ├── config.py       # Configuration (pydantic)
│   │   └── logging.py      # Structured logging
│   ├── exchange/           # Exchange connectors
│   │   └── base.py         # Abstract exchange interface
│   ├── strategies/         # Trading strategies
│   │   └── base.py         # Strategy base class
│   ├── data/               # Data management
│   │   └── feed.py         # Data feed interface
│   ├── signals/            # Signal generation
│   ├── risk/               # Risk management
│   ├── backtest/           # Backtesting engine
│   └── notifications/      # Alerts (Discord)
├── tests/                  # Test suite
│   ├── conftest.py         # Pytest fixtures
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests
├── docs/wiki/              # Wiki documentation
├── pyproject.toml          # Poetry config
├── .pre-commit-config.yaml # Pre-commit hooks
├── config.example.yaml     # Example configuration
└── Dockerfile              # Container build
```

---

## Coding Standards

### Style Guide

- Follow [PEP 8](https://peps.python.org/pep-0008/)
- Use [Google-style docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- Maximum line length: 100 characters
- Use type hints everywhere

### Formatting

Ruff handles formatting:

```bash
# Format code
poetry run ruff format src/ tests/

# Check formatting
poetry run ruff format --check src/ tests/
```

### Linting

```bash
# Run linter
poetry run ruff check src/ tests/

# Auto-fix issues
poetry run ruff check --fix src/ tests/
```

### Type Checking

```bash
# Run mypy
poetry run mypy src/

# Check specific file
poetry run mypy src/cryptrink/core/config.py
```

---

## Testing

### Running Tests

```bash
# All tests
poetry run pytest

# With verbose output
poetry run pytest -v

# Specific test file
poetry run pytest tests/unit/test_config.py

# Specific test
poetry run pytest tests/unit/test_config.py::TestSettings::test_default_values

# With coverage
poetry run pytest --cov=src/cryptrink --cov-report=html
open htmlcov/index.html
```

### Test Categories

```bash
# Unit tests only
poetry run pytest tests/unit/ -m unit

# Integration tests only
poetry run pytest tests/integration/ -m integration

# Skip slow tests
poetry run pytest -m "not slow"
```

### Writing Tests

```python
# tests/unit/test_my_feature.py
import pytest
from cryptrink.my_module import MyClass


class TestMyClass:
    """Tests for MyClass."""

    def test_something(self) -> None:
        """Test that something works."""
        obj = MyClass()
        result = obj.do_something()
        assert result == expected

    @pytest.mark.asyncio
    async def test_async_method(self) -> None:
        """Test async method."""
        obj = MyClass()
        result = await obj.async_method()
        assert result is not None

    def test_with_fixture(self, sample_ticker) -> None:
        """Test using a fixture."""
        assert sample_ticker.symbol == "BTC-EUR"
```

### Fixtures

Common fixtures in `tests/conftest.py`:

```python
@pytest.fixture
def mock_settings() -> Settings:
    """Test settings."""
    return Settings(...)

@pytest.fixture
def sample_ticker() -> Ticker:
    """Sample ticker data."""
    return Ticker(...)

@pytest.fixture
def mock_exchange() -> AsyncMock:
    """Mocked exchange."""
    exchange = AsyncMock()
    exchange.name = "mock"
    return exchange
```

---

## Adding New Features

### 1. Create a Branch

```bash
git checkout -b feature/my-new-feature
```

### 2. Write Tests First (TDD)

```python
# tests/unit/test_new_feature.py
def test_new_feature():
    # Write failing test first
    pass
```

### 3. Implement Feature

```python
# src/cryptrink/new_module.py
def new_feature():
    """Implement the feature."""
    pass
```

### 4. Run Tests and Linting

```bash
poetry run pytest
poetry run ruff check src/ tests/
poetry run mypy src/
```

### 5. Commit and Push

```bash
git add .
git commit -m "feat: add new feature"
git push origin feature/my-new-feature
```

---

## Adding a New Strategy

1. **Create strategy file**:
```python
# src/cryptrink/strategies/my_strategy.py
from cryptrink.strategies.base import BaseStrategy, Signal, StrategyContext

class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "my_strategy"

    @property
    def description(self) -> str:
        return "My custom strategy"

    def generate_signal(self, context: StrategyContext) -> Signal:
        # Implementation
        pass
```

2. **Add tests**:
```python
# tests/unit/test_my_strategy.py
from cryptrink.strategies.my_strategy import MyStrategy

def test_my_strategy_signal(sample_ohlcv):
    strategy = MyStrategy()
    # Test signal generation
```

3. **Register strategy** (once registry is implemented)

---

## Adding a New Exchange

1. **Implement BaseExchange**:
```python
# src/cryptrink/exchange/new_exchange.py
from cryptrink.exchange.base import BaseExchange, Ticker, Order

class NewExchange(BaseExchange):
    @property
    def name(self) -> str:
        return "new_exchange"

    async def get_ticker(self, symbol: str) -> Ticker:
        # Implementation
        pass

    # Implement all abstract methods...
```

2. **Add authentication module if needed**

3. **Write tests with mocked responses**:
```python
# tests/unit/test_new_exchange.py
import respx

@respx.mock
async def test_get_ticker():
    respx.get("https://api.example.com/ticker").respond(json={...})
    exchange = NewExchange()
    ticker = await exchange.get_ticker("BTC-EUR")
    assert ticker.symbol == "BTC-EUR"
```

---

## Debugging

### Using the Logger

```python
from cryptrink.core.logging import get_logger

logger = get_logger(__name__)

def my_function():
    logger.debug("entering_function", arg1=value1)
    try:
        result = do_something()
        logger.info("operation_complete", result=result)
    except Exception as e:
        logger.error("operation_failed", error=str(e))
        raise
```

### Debug Mode

```bash
# Set debug logging
CRYPTRINK_LOG_LEVEL=DEBUG cryptrink run --mode paper
```

### Using pdb

```python
def problematic_function():
    import pdb; pdb.set_trace()  # Breakpoint
    # ... code to debug
```

---

## Documentation

### Docstrings

Use Google-style docstrings:

```python
def function_name(param1: str, param2: int = 10) -> bool:
    """Short description of function.

    Longer description if needed. Can span multiple lines
    and include examples.

    Args:
        param1: Description of param1.
        param2: Description of param2. Defaults to 10.

    Returns:
        Description of return value.

    Raises:
        ValueError: When something is wrong.

    Example:
        >>> result = function_name("test", 5)
        >>> print(result)
        True
    """
    pass
```

### Wiki Updates

Update wiki pages in `docs/wiki/` when:
- Adding new features
- Changing architecture
- Updating deployment options
- Adding new strategies

---

## Release Process

1. **Update version** in `src/cryptrink/__init__.py`:
```python
__version__ = "0.2.0"
```

2. **Update CHANGELOG** (if we have one)

3. **Create release commit**:
```bash
git add .
git commit -m "release: v0.2.0"
git tag v0.2.0
git push origin main --tags
```

4. **Build and publish** (when ready):
```bash
poetry build
poetry publish --dry-run  # Test first
poetry publish
```

---

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/trinchetto/cryptrink/issues)
- **Wiki**: [Project Wiki](https://github.com/trinchetto/cryptrink/wiki)
- **Discussions**: GitHub Discussions (if enabled)
