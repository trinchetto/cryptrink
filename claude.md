# Claude Code Instructions for Cryptrink

This document provides coding standards and guidelines for Claude Code when working on the Cryptrink project.

## Code Quality Requirements

### Type Safety (mypy)

All code must pass mypy type checking with strict settings. Follow these guidelines:

#### 1. Import Organization
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal  # noqa: TC003 if used at runtime
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from cryptrink.execution.models import Order, Position
```

**Rules:**
- Use `TYPE_CHECKING` block for imports only needed for type hints
- Add `# noqa: TC003` for stdlib imports used at runtime (e.g., Decimal in f-strings)
- Use `TypedDict` for dictionary return types to maintain type safety

#### 2. Type Annotations
```python
# Good: Explicit types
def calculate_returns(equity_curve: list[tuple[datetime, Decimal]]) -> Decimal:
    daily_returns: list[Decimal] = []
    running_total = 0.0  # Explicit float
    return sum(daily_returns, Decimal("0"))

# Bad: Implicit types that mypy can't infer
def calculate_returns(equity_curve):
    daily_returns = []
    running_total = 0
    return sum(daily_returns)
```

#### 3. Decimal Arithmetic
```python
# Good: Proper Decimal handling
mean = sum(values, Decimal("0")) / Decimal(str(len(values)))
variance = sum((r - mean) ** 2 for r in values) / Decimal(str(len(values) - 1))

# Bad: Mixed float/Decimal causing type errors
mean = sum(values) / len(values)  # Returns Decimal | float
```

#### 4. Type Ignores
Use type ignores sparingly and document why:
```python
# Good: Documented type ignore for third-party library
import matplotlib.pyplot as plt  # type: ignore[import-not-found]

# Good: Matplotlib datetime handling
ax.plot(timestamps, values)  # Matplotlib handles datetime automatically

# Bad: Hiding actual type errors
result = some_function()  # type: ignore
```

#### 5. Dictionary Return Types
```python
# Good: TypedDict for structured dictionaries
class TradeStatsDict(TypedDict):
    total_trades: int
    win_rate: Decimal
    avg_trade: Decimal

def calculate_stats(positions: list[Position]) -> TradeStatsDict:
    return {
        "total_trades": len(positions),
        "win_rate": Decimal("0.5"),
        "avg_trade": Decimal("100"),
    }

# Bad: Generic dict[str, object]
def calculate_stats(positions: list[Position]) -> dict[str, object]:
    return {"total_trades": len(positions)}  # Type errors downstream
```

### Code Formatting (ruff)

All code must pass ruff linting and formatting checks.

#### 1. Import Ordering
Ruff automatically organizes imports into:
1. Standard library
2. Third-party packages
3. First-party imports

```python
# Correct order
from datetime import datetime
from decimal import Decimal

import pandas as pd

from cryptrink.core.logging import get_logger
```

#### 2. Line Length
- Maximum 100 characters per line
- Break long lines at logical points
```python
# Good
result = calculator.calculate(
    positions=positions,
    orders=orders,
    initial_balance=initial_balance,
    final_balance=final_balance,
)

# Bad (too long)
result = calculator.calculate(positions=positions, orders=orders, initial_balance=initial_balance, final_balance=final_balance)
```

#### 3. String Quotes
- Use double quotes for strings
- Exception: Use single quotes to avoid escaping
```python
# Good
message = "Processing trade data"
sql = 'SELECT * FROM trades WHERE symbol = "BTC-USD"'

# Bad
message = 'Processing trade data'
```

### Pre-commit Hooks

The project uses pre-commit hooks that run automatically on commit:

1. **trim trailing whitespace** - Removes trailing spaces
2. **fix end of files** - Ensures files end with newline
3. **ruff** - Linting checks
4. **ruff-format** - Code formatting
5. **mypy** - Type checking

**Important:** If pre-commit modifies files (e.g., ruff-format), you must:
1. Run `git add -A` again to stage the changes
2. Re-run the commit

```bash
# Typical workflow
git add src/module.py
git commit -m "feat: add new feature"
# If pre-commit reformats files:
git add -A
git commit -m "feat: add new feature"  # Now succeeds
```

## Decimal Precision

Financial calculations must use `Decimal` for precision:

```python
from decimal import Decimal

# Good: Decimal for financial calculations
balance = Decimal("10000.00")
fee_rate = Decimal("0.001")
fee = balance * fee_rate  # Decimal("10.00")

# Good: Convert to Decimal explicitly
pnl = Decimal(str(position.realized_pnl))

# Bad: Float for money
balance = 10000.00
fee = balance * 0.001  # Potential precision loss
```

## Testing Standards

### Test Organization
```python
class TestFeatureName:
    """Tests for FeatureName."""

    def test_basic_case(self):
        """Test basic functionality."""
        # Arrange
        calculator = Calculator()

        # Act
        result = calculator.calculate(input_data)

        # Assert
        assert result == expected_value
```

### Async Tests
```python
@pytest.mark.asyncio
async def test_async_operation(self):
    """Test asynchronous operation."""
    result = await executor.execute_signal(signal, context)
    assert result.success is True
```

### Fixtures
```python
@pytest.fixture
def sample_data():
    """Create sample data for testing."""
    return [
        Position(...),
        Position(...),
    ]
```

## Error Handling

### Validation
```python
# Good: Early validation with clear errors
def calculate_metrics(positions: list[Position]) -> BacktestMetrics:
    if not positions:
        raise ValueError("Cannot calculate metrics with empty position list")

    if len(positions) < 2:
        logger.warning("metrics_calculated_with_few_positions", count=len(positions))

    # Continue with calculation
```

### Logging
```python
from cryptrink.core.logging import get_logger

logger = get_logger(__name__)

# Good: Structured logging
logger.info(
    "backtest_completed",
    symbol=symbol,
    total_trades=metrics.total_trades,
    final_balance=str(final_balance),
)

# Good: Error logging
logger.error(
    "backtest_failed",
    symbol=symbol,
    error=str(e),
    exc_info=True,
)
```

## Docstrings

Use Google-style docstrings:

```python
def calculate_sharpe_ratio(
    daily_returns: list[Decimal],
    risk_free_rate: Decimal = Decimal("0.02"),
) -> Decimal:
    """Calculate Sharpe ratio from daily returns.

    The Sharpe ratio measures risk-adjusted returns by comparing excess returns
    to the standard deviation of returns.

    Args:
        daily_returns: List of daily percentage returns.
        risk_free_rate: Annual risk-free rate (default: 2%).

    Returns:
        Annualized Sharpe ratio.

    Raises:
        ValueError: If daily_returns is empty.

    Example:
        >>> returns = [Decimal("0.01"), Decimal("-0.005"), Decimal("0.02")]
        >>> sharpe = calculate_sharpe_ratio(returns)
        >>> print(f"Sharpe ratio: {sharpe:.2f}")
        Sharpe ratio: 1.23
    """
```

## Common Patterns

### Dataclasses
```python
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class BacktestResult:
    """Comprehensive backtest result.

    This dataclass contains all information about a completed backtest,
    including metrics, equity curve, and trade history.
    """

    strategy_name: str
    symbol: str
    metrics: BacktestMetrics
    equity_curve: list[tuple[datetime, Decimal]]
```

### Async Context Managers
```python
async with session_factory() as session:
    repository = TradeRepository(session)
    trades = await repository.get_all()
```

### List Comprehensions
```python
# Good: Readable single-line
pnls = [Decimal(str(pos.realized_pnl)) for pos in positions]

# Good: Multi-line for complex expressions
equity_curve = [
    {"timestamp": ts.isoformat(), "equity": str(eq)}
    for ts, eq in self.equity_curve
]
```

## Git Commit Messages

Follow Conventional Commits:

```bash
# Format: <type>(<scope>): <subject>

# Types:
feat: add new feature
fix: bug fix
docs: documentation changes
test: add or modify tests
refactor: code refactoring
chore: maintenance tasks

# Examples:
git commit -m "feat: implement BacktestEngine with event-driven replay

- Add BacktestEngine orchestrator
- Implement rolling StrategyContext building
- Add equity curve tracking
- Integrate with TradingEngine

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

## Module Structure

### Standard Module Layout
```python
"""Module docstring describing purpose and key functionality."""

from __future__ import annotations

# Standard library imports
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Third-party imports
import pandas as pd

# Type checking imports
from typing import TYPE_CHECKING

# Local imports
from cryptrink.core.logging import get_logger

if TYPE_CHECKING:
    from cryptrink.execution.models import Order

logger = get_logger(__name__)


# Constants
DEFAULT_SLIPPAGE_BPS = Decimal("0.0005")


# Classes and functions
class ClassName:
    """Class docstring."""
    pass
```

## Performance Considerations

1. **Use generators for large datasets:**
```python
# Good: Generator for memory efficiency
def process_large_dataset(data: list[Candle]) -> Iterator[Signal]:
    for candle in data:
        yield process_candle(candle)

# Bad: Load everything into memory
def process_large_dataset(data: list[Candle]) -> list[Signal]:
    return [process_candle(candle) for candle in data]
```

2. **Avoid premature optimization:**
   - Focus on correctness first
   - Profile before optimizing
   - Document why optimizations are needed

## Summary Checklist

Before committing code, ensure:

- [ ] All type hints are correct and mypy passes
- [ ] Code is formatted with ruff-format
- [ ] Docstrings follow Google style
- [ ] Tests are comprehensive and pass
- [ ] Decimal used for financial calculations
- [ ] Logging uses structured format
- [ ] Git commit follows Conventional Commits
- [ ] Pre-commit hooks pass

## Questions or Issues?

If you encounter unclear type errors or linting issues:
1. Check this document for guidance
2. Look at similar code in the codebase for patterns
3. Ask the user for clarification on project-specific conventions
