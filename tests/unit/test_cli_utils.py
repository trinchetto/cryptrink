"""Unit tests for CLI utilities."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from cryptrink.cli.utils import (
    create_data_feed,
    create_session_factory,
    format_currency,
    format_percentage,
    load_strategy,
    run_async,
)
from cryptrink.core.config import DatabaseSettings, Settings
from cryptrink.data.feed import HistoricalDataFeed
from cryptrink.strategies.base import BaseStrategy


class TestRunAsync:
    """Tests for run_async utility."""

    def test_run_async_success(self):
        """Test successful async execution."""

        async def simple_coro():
            return "success"

        result = run_async(simple_coro())
        assert result == "success"

    def test_run_async_with_value(self):
        """Test async execution returning a value."""

        async def return_value():
            await asyncio.sleep(0.01)
            return 42

        result = run_async(return_value())
        assert result == 42

    def test_run_async_keyboard_interrupt(self):
        """Test KeyboardInterrupt handling."""

        async def interrupt_coro():
            raise KeyboardInterrupt

        with pytest.raises(SystemExit) as exc_info:
            run_async(interrupt_coro())

        assert exc_info.value.code == 0

    def test_run_async_exception(self):
        """Test exception propagation."""

        async def error_coro():
            msg = "Test error"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="Test error"):
            run_async(error_coro())


class TestCreateSessionFactory:
    """Tests for create_session_factory utility."""

    def test_create_session_factory_sqlite(self):
        """Test session factory creation with SQLite."""
        config = Settings(
            database=DatabaseSettings(
                url="sqlite+aiosqlite:///:memory:",
                echo=False,
            )
        )

        factory = create_session_factory(config)

        assert isinstance(factory, async_sessionmaker)
        # Factory is configured correctly - verify by checking it can be called
        assert callable(factory)

    def test_create_session_factory_with_echo(self):
        """Test session factory creation with echo enabled."""
        config = Settings(
            database=DatabaseSettings(
                url="sqlite+aiosqlite:///:memory:",
                echo=True,
            )
        )

        factory = create_session_factory(config)

        assert isinstance(factory, async_sessionmaker)


class TestLoadStrategy:
    """Tests for load_strategy utility."""

    def test_load_strategy_not_found(self):
        """Test loading non-existent strategy."""
        with pytest.raises(ValueError, match="Strategy 'nonexistent' not found"):
            load_strategy("nonexistent")

    @pytest.mark.skip(reason="Requires strategy registration; covered by integration tests")
    def test_load_strategy_success(self):
        """Test loading a valid strategy."""
        strategy = load_strategy("sma_crossover", short_period=10, long_period=30)

        assert isinstance(strategy, BaseStrategy)
        assert strategy.name == "sma_crossover"

    @pytest.mark.skip(reason="Requires strategy registration; covered by integration tests")
    def test_load_strategy_with_params(self):
        """Test loading strategy with custom parameters."""
        strategy = load_strategy(
            "rsi_mean_reversion",
            rsi_period=10,
            oversold_threshold=25,
            overbought_threshold=75,
        )

        assert isinstance(strategy, BaseStrategy)
        assert strategy.name == "rsi_mean_reversion"

    @pytest.mark.skip(reason="Requires strategy registration; covered by integration tests")
    def test_load_strategy_invalid_params(self):
        """Test loading strategy with invalid parameters."""
        with pytest.raises(TypeError):
            load_strategy("sma_crossover", invalid_param=999)


class TestCreateDataFeed:
    """Tests for create_data_feed utility."""

    def test_create_data_feed(self):
        """Test data feed creation."""
        config = Settings(
            database=DatabaseSettings(
                url="sqlite+aiosqlite:///:memory:",
                echo=False,
            )
        )
        factory = create_session_factory(config)

        data_feed = create_data_feed(config, factory)

        assert isinstance(data_feed, HistoricalDataFeed)
        # Data feed created successfully


class TestFormatCurrency:
    """Tests for format_currency utility."""

    def test_format_currency_whole_number(self):
        """Test formatting whole number."""
        result = format_currency(Decimal("1000"))
        assert result == "€1,000.00"

    def test_format_currency_with_decimals(self):
        """Test formatting number with decimals."""
        result = format_currency(Decimal("1234.56"))
        assert result == "€1,234.56"

    def test_format_currency_large_number(self):
        """Test formatting large number."""
        result = format_currency(Decimal("1234567.89"))
        assert result == "€1,234,567.89"

    def test_format_currency_zero(self):
        """Test formatting zero."""
        result = format_currency(Decimal("0"))
        assert result == "€0.00"

    def test_format_currency_negative(self):
        """Test formatting negative number."""
        result = format_currency(Decimal("-500.25"))
        assert result == "€-500.25"


class TestFormatPercentage:
    """Tests for format_percentage utility."""

    def test_format_percentage_default(self):
        """Test formatting percentage with default decimals."""
        result = format_percentage(Decimal("0.1"))
        assert result == "10.00%"

    def test_format_percentage_custom_decimals(self):
        """Test formatting percentage with custom decimals."""
        result = format_percentage(Decimal("0.12345"), decimals=3)
        assert result == "12.345%"

    def test_format_percentage_zero(self):
        """Test formatting zero percentage."""
        result = format_percentage(Decimal("0"))
        assert result == "0.00%"

    def test_format_percentage_negative(self):
        """Test formatting negative percentage."""
        result = format_percentage(Decimal("-0.05"))
        assert result == "-5.00%"

    def test_format_percentage_one_decimal(self):
        """Test formatting percentage with one decimal."""
        result = format_percentage(Decimal("0.1234"), decimals=1)
        assert result == "12.3%"

    def test_format_percentage_large_value(self):
        """Test formatting large percentage."""
        result = format_percentage(Decimal("1.5"))
        assert result == "150.00%"
