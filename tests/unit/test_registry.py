"""Unit tests for strategy registry."""

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from cryptrink.strategies.base import BaseStrategy, Signal, SignalType, StrategyContext
from cryptrink.strategies.mean_reversion import BollingerBandsStrategy, RsiMeanReversionStrategy
from cryptrink.strategies.registry import (
    StrategyRegistry,
    create,
    get_registry,
    list_strategies,
    register,
    unregister,
)
from cryptrink.strategies.trend_following import SmaCrossoverStrategy


class DummyStrategy(BaseStrategy):
    """Dummy strategy for testing."""

    def __init__(self, param1: int = 10, param2: str = "test") -> None:
        self.param1 = param1
        self.param2 = param2

    @property
    def name(self) -> str:
        return f"dummy_{self.param1}"

    @property
    def description(self) -> str:
        return f"Dummy strategy with param1={self.param1}"

    @property
    def required_history(self) -> int:
        return 10

    @property
    def timeframe(self) -> str:
        return "1h"

    def generate_signal(self, context: StrategyContext) -> Signal:
        return Signal(
            signal_type=SignalType.HOLD,
            symbol=context.symbol,
            timestamp=context.timestamp,
            price=context.current_price,
        )

    def reset(self) -> None:
        pass


class TestStrategyRegistry:
    """Tests for StrategyRegistry class."""

    def test_init_creates_empty_registry(self) -> None:
        """Test that initialization creates an empty registry."""
        registry = StrategyRegistry()

        assert len(registry) == 0
        assert registry.list_strategies() == []

    def test_register_strategy(self) -> None:
        """Test registering a strategy."""
        registry = StrategyRegistry()

        registry.register("dummy", DummyStrategy)

        assert len(registry) == 1
        assert "dummy" in registry
        assert registry.is_registered("dummy")
        assert registry.list_strategies() == ["dummy"]

    def test_register_multiple_strategies(self) -> None:
        """Test registering multiple strategies."""
        registry = StrategyRegistry()

        registry.register("sma", SmaCrossoverStrategy)
        registry.register("rsi", RsiMeanReversionStrategy)
        registry.register("bb", BollingerBandsStrategy)

        assert len(registry) == 3
        assert set(registry.list_strategies()) == {"sma", "rsi", "bb"}

    def test_register_duplicate_raises_error(self) -> None:
        """Test that registering duplicate strategy raises error."""
        registry = StrategyRegistry()
        registry.register("dummy", DummyStrategy)

        with pytest.raises(ValueError, match="already registered"):
            registry.register("dummy", DummyStrategy)

    def test_register_empty_name_raises_error(self) -> None:
        """Test that registering with empty name raises error."""
        registry = StrategyRegistry()

        with pytest.raises(ValueError, match="non-empty string"):
            registry.register("", DummyStrategy)

    def test_register_non_callable_raises_error(self) -> None:
        """Test that registering non-callable raises error."""
        registry = StrategyRegistry()

        with pytest.raises(TypeError, match="must be callable"):
            registry.register("invalid", "not_a_callable")  # type: ignore[arg-type]

    def test_unregister_strategy(self) -> None:
        """Test unregistering a strategy."""
        registry = StrategyRegistry()
        registry.register("dummy", DummyStrategy)

        assert "dummy" in registry

        registry.unregister("dummy")

        assert "dummy" not in registry
        assert len(registry) == 0

    def test_unregister_nonexistent_raises_error(self) -> None:
        """Test that unregistering nonexistent strategy raises error."""
        registry = StrategyRegistry()

        with pytest.raises(KeyError, match="not registered"):
            registry.unregister("nonexistent")

    def test_is_registered(self) -> None:
        """Test checking if strategy is registered."""
        registry = StrategyRegistry()

        assert not registry.is_registered("dummy")

        registry.register("dummy", DummyStrategy)

        assert registry.is_registered("dummy")
        assert not registry.is_registered("other")

    def test_create_strategy_no_params(self) -> None:
        """Test creating a strategy with default parameters."""
        registry = StrategyRegistry()
        registry.register("dummy", DummyStrategy)

        strategy = registry.create("dummy")

        assert isinstance(strategy, DummyStrategy)
        assert strategy.param1 == 10
        assert strategy.param2 == "test"

    def test_create_strategy_with_params(self) -> None:
        """Test creating a strategy with custom parameters."""
        registry = StrategyRegistry()
        registry.register("dummy", DummyStrategy)

        strategy = registry.create("dummy", param1=20, param2="custom")

        assert isinstance(strategy, DummyStrategy)
        assert strategy.param1 == 20
        assert strategy.param2 == "custom"

    def test_create_nonexistent_raises_error(self) -> None:
        """Test that creating nonexistent strategy raises error."""
        registry = StrategyRegistry()

        with pytest.raises(KeyError, match="not registered"):
            registry.create("nonexistent")

    def test_create_with_invalid_params_raises_error(self) -> None:
        """Test that creating with invalid parameters raises error."""
        registry = StrategyRegistry()
        registry.register("sma", SmaCrossoverStrategy)

        # Invalid parameters: fast_period must be less than slow_period
        with pytest.raises(ValueError, match="Failed to create strategy"):
            registry.create("sma", fast_period=30, slow_period=10)

    def test_create_real_strategies(self) -> None:
        """Test creating real trading strategies."""
        registry = StrategyRegistry()
        registry.register("sma", SmaCrossoverStrategy)
        registry.register("rsi", RsiMeanReversionStrategy)
        registry.register("bb", BollingerBandsStrategy)

        sma = registry.create("sma", fast_period=10, slow_period=30)
        rsi = registry.create("rsi", rsi_period=14)
        bb = registry.create("bb", period=20, std_dev=2.0)

        assert isinstance(sma, SmaCrossoverStrategy)
        assert isinstance(rsi, RsiMeanReversionStrategy)
        assert isinstance(bb, BollingerBandsStrategy)

        # Verify strategies work
        prices = [100] * 50
        ohlcv = pd.DataFrame(
            {
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [1000] * len(prices),
            }
        )
        context = StrategyContext(
            symbol="BTC-USD",
            current_price=Decimal("100"),
            timestamp=datetime.now(UTC),
            ohlcv=ohlcv,
        )

        sma_signal = sma.generate_signal(context)
        rsi_signal = rsi.generate_signal(context)
        bb_signal = bb.generate_signal(context)

        assert sma_signal.symbol == "BTC-USD"
        assert rsi_signal.symbol == "BTC-USD"
        assert bb_signal.symbol == "BTC-USD"

    def test_list_strategies_sorted(self) -> None:
        """Test that list_strategies returns sorted names."""
        registry = StrategyRegistry()
        registry.register("zebra", DummyStrategy)
        registry.register("alpha", DummyStrategy)
        registry.register("beta", DummyStrategy)

        strategies = registry.list_strategies()

        assert strategies == ["alpha", "beta", "zebra"]

    def test_clear_removes_all_strategies(self) -> None:
        """Test that clear removes all strategies."""
        registry = StrategyRegistry()
        registry.register("sma", SmaCrossoverStrategy)
        registry.register("rsi", RsiMeanReversionStrategy)

        assert len(registry) == 2

        registry.clear()

        assert len(registry) == 0
        assert registry.list_strategies() == []

    def test_len(self) -> None:
        """Test __len__ returns correct count."""
        registry = StrategyRegistry()

        assert len(registry) == 0

        registry.register("dummy1", DummyStrategy)
        assert len(registry) == 1

        registry.register("dummy2", DummyStrategy)
        assert len(registry) == 2

        registry.unregister("dummy1")
        assert len(registry) == 1

    def test_contains(self) -> None:
        """Test __contains__ for 'in' operator."""
        registry = StrategyRegistry()
        registry.register("dummy", DummyStrategy)

        assert "dummy" in registry
        assert "other" not in registry

    def test_repr(self) -> None:
        """Test __repr__ returns informative string."""
        registry = StrategyRegistry()

        repr_empty = repr(registry)
        assert "StrategyRegistry" in repr_empty
        assert "strategies=0" in repr_empty

        registry.register("dummy", DummyStrategy)

        repr_one = repr(registry)
        assert "strategies=1" in repr_one


class TestGlobalRegistry:
    """Tests for global registry convenience functions."""

    def setup_method(self) -> None:
        """Clear global registry before each test."""
        get_registry().clear()

    def teardown_method(self) -> None:
        """Clear global registry after each test."""
        get_registry().clear()

    def test_global_register(self) -> None:
        """Test global register function."""
        register("dummy", DummyStrategy)

        assert "dummy" in get_registry()

    def test_global_unregister(self) -> None:
        """Test global unregister function."""
        register("dummy", DummyStrategy)
        unregister("dummy")

        assert "dummy" not in get_registry()

    def test_global_create(self) -> None:
        """Test global create function."""
        register("dummy", DummyStrategy)

        strategy = create("dummy", param1=99)

        assert isinstance(strategy, DummyStrategy)
        assert strategy.param1 == 99

    def test_global_list_strategies(self) -> None:
        """Test global list_strategies function."""
        register("sma", SmaCrossoverStrategy)
        register("rsi", RsiMeanReversionStrategy)

        strategies = list_strategies()

        assert set(strategies) == {"sma", "rsi"}

    def test_get_registry_returns_same_instance(self) -> None:
        """Test that get_registry always returns the same instance."""
        registry1 = get_registry()
        registry2 = get_registry()

        assert registry1 is registry2

    def test_global_registry_persistence(self) -> None:
        """Test that global registry persists across function calls."""
        register("dummy", DummyStrategy)

        # Different function call should see the same registry
        strategies = list_strategies()
        assert "dummy" in strategies

        # Create should work
        strategy = create("dummy")
        assert isinstance(strategy, DummyStrategy)


class TestRegistryEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_create_returns_base_strategy_instance(self) -> None:
        """Test that created strategies are BaseStrategy instances."""
        registry = StrategyRegistry()
        registry.register("sma", SmaCrossoverStrategy)

        strategy = registry.create("sma")

        assert isinstance(strategy, BaseStrategy)

    def test_register_lambda_factory(self) -> None:
        """Test registering a lambda factory function."""
        registry = StrategyRegistry()

        # Lambda that creates strategy with fixed params
        registry.register("fixed_sma", lambda: SmaCrossoverStrategy(fast_period=5, slow_period=15))

        strategy = registry.create("fixed_sma")

        assert isinstance(strategy, SmaCrossoverStrategy)
        # Note: Can't easily verify internal params without exposing them

    def test_register_factory_function(self) -> None:
        """Test registering a custom factory function."""
        registry = StrategyRegistry()

        def create_custom_rsi(**kwargs: int | float) -> RsiMeanReversionStrategy:
            """Factory function with custom logic."""
            # Set default values with some custom logic
            rsi_period = kwargs.get("rsi_period", 14)
            oversold = kwargs.get("oversold_threshold", 30.0)
            overbought = kwargs.get("overbought_threshold", 70.0)
            return RsiMeanReversionStrategy(
                rsi_period=int(rsi_period),
                oversold_threshold=float(oversold),
                overbought_threshold=float(overbought),
            )

        registry.register("custom_rsi", create_custom_rsi)

        strategy = registry.create("custom_rsi", rsi_period=21)

        assert isinstance(strategy, RsiMeanReversionStrategy)

    def test_error_message_includes_available_strategies(self) -> None:
        """Test that error message includes available strategies."""
        registry = StrategyRegistry()
        registry.register("sma", SmaCrossoverStrategy)
        registry.register("rsi", RsiMeanReversionStrategy)

        with pytest.raises(KeyError) as exc_info:
            registry.create("nonexistent")

        error_msg = str(exc_info.value)
        assert "nonexistent" in error_msg
        assert "Available strategies" in error_msg
        assert "sma" in error_msg
        assert "rsi" in error_msg

    def test_register_after_clear(self) -> None:
        """Test that registry can be used after clearing."""
        registry = StrategyRegistry()
        registry.register("dummy1", DummyStrategy)
        registry.clear()

        # Should be able to register again
        registry.register("dummy2", DummyStrategy)

        assert len(registry) == 1
        assert "dummy2" in registry
        assert "dummy1" not in registry
