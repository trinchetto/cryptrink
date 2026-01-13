"""Strategy registry for dynamic strategy loading and management.

This module provides a central registry for trading strategies, allowing them to be
registered, retrieved, and instantiated dynamically by name with custom parameters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from cryptrink.strategies.base import BaseStrategy


class StrategyRegistry:
    """Registry for managing trading strategies.

    The StrategyRegistry allows strategies to be registered with unique names
    and retrieved/instantiated later. It supports:
    - Strategy registration with factory functions
    - Dynamic strategy instantiation by name
    - Parameter validation and configuration
    - Strategy discovery and listing

    Example:
        >>> registry = StrategyRegistry()
        >>> registry.register("sma_crossover", SmaCrossoverStrategy)
        >>> strategy = registry.create("sma_crossover", fast_period=10, slow_period=30)
    """

    def __init__(self) -> None:
        """Initialize an empty strategy registry."""
        self._strategies: dict[str, Callable[..., BaseStrategy]] = {}

    def register(
        self,
        name: str,
        factory: Callable[..., BaseStrategy],
    ) -> None:
        """Register a strategy factory function.

        Args:
            name: Unique name for the strategy (e.g., "sma_crossover").
            factory: Factory function or class that creates strategy instances.

        Raises:
            ValueError: If name is empty or strategy already registered.
            TypeError: If factory is not callable.
        """
        if not name or not isinstance(name, str):
            raise ValueError("Strategy name must be a non-empty string")

        if not callable(factory):
            raise TypeError(f"Strategy factory must be callable, got {type(factory)}")

        if name in self._strategies:
            raise ValueError(f"Strategy '{name}' is already registered")

        self._strategies[name] = factory

    def unregister(self, name: str) -> None:
        """Unregister a strategy.

        Args:
            name: Name of the strategy to unregister.

        Raises:
            KeyError: If strategy is not registered.
        """
        if name not in self._strategies:
            raise KeyError(f"Strategy '{name}' is not registered")

        del self._strategies[name]

    def is_registered(self, name: str) -> bool:
        """Check if a strategy is registered.

        Args:
            name: Name of the strategy to check.

        Returns:
            True if strategy is registered, False otherwise.
        """
        return name in self._strategies

    def create(self, name: str, **kwargs: Any) -> BaseStrategy:
        """Create a strategy instance by name.

        Args:
            name: Name of the strategy to create.
            **kwargs: Parameters to pass to the strategy factory.

        Returns:
            Instantiated strategy object.

        Raises:
            KeyError: If strategy is not registered.
            TypeError: If factory parameters are invalid.
            ValueError: If strategy parameters are invalid.
        """
        if name not in self._strategies:
            raise KeyError(
                f"Strategy '{name}' is not registered. "
                f"Available strategies: {', '.join(self.list_strategies())}"
            )

        factory = self._strategies[name]

        try:
            strategy = factory(**kwargs)
        except TypeError as e:
            raise TypeError(f"Failed to create strategy '{name}': {e}") from e
        except ValueError as e:
            raise ValueError(f"Failed to create strategy '{name}': {e}") from e

        if not isinstance(strategy, BaseStrategy):
            raise TypeError(
                f"Strategy factory '{name}' must return a BaseStrategy instance, "
                f"got {type(strategy)}"
            )

        return strategy

    def list_strategies(self) -> list[str]:
        """List all registered strategy names.

        Returns:
            Sorted list of registered strategy names.
        """
        return sorted(self._strategies.keys())

    def clear(self) -> None:
        """Clear all registered strategies.

        This removes all strategies from the registry.
        """
        self._strategies.clear()

    def __len__(self) -> int:
        """Return the number of registered strategies.

        Returns:
            Number of registered strategies.
        """
        return len(self._strategies)

    def __contains__(self, name: str) -> bool:
        """Check if a strategy is registered using 'in' operator.

        Args:
            name: Name of the strategy to check.

        Returns:
            True if strategy is registered, False otherwise.
        """
        return name in self._strategies

    def __repr__(self) -> str:
        """Return a string representation of the registry.

        Returns:
            String showing number of registered strategies.
        """
        return f"StrategyRegistry(strategies={len(self._strategies)})"


# Global registry instance for convenience
_global_registry = StrategyRegistry()


def register(name: str, factory: Callable[..., BaseStrategy]) -> None:
    """Register a strategy in the global registry.

    Convenience function for registering strategies without accessing
    the global registry directly.

    Args:
        name: Unique name for the strategy.
        factory: Factory function or class that creates strategy instances.
    """
    _global_registry.register(name, factory)


def unregister(name: str) -> None:
    """Unregister a strategy from the global registry.

    Args:
        name: Name of the strategy to unregister.
    """
    _global_registry.unregister(name)


def create(name: str, **kwargs: Any) -> BaseStrategy:
    """Create a strategy instance from the global registry.

    Args:
        name: Name of the strategy to create.
        **kwargs: Parameters to pass to the strategy factory.

    Returns:
        Instantiated strategy object.
    """
    return _global_registry.create(name, **kwargs)


def list_strategies() -> list[str]:
    """List all strategies in the global registry.

    Returns:
        Sorted list of registered strategy names.
    """
    return _global_registry.list_strategies()


def get_registry() -> StrategyRegistry:
    """Get the global strategy registry.

    Returns:
        Global StrategyRegistry instance.
    """
    return _global_registry
