"""Tests for the shared runtime helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from cryptrink.runtime import (
    BUILTIN_STRATEGIES,
    build_session_factory,
    ensure_builtins_registered,
    list_builtin_strategy_names,
    resolve_strategy,
)
from cryptrink.strategies import registry as strategy_registry
from cryptrink.strategies.base import BaseStrategy


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Each test starts with the global strategy registry cleared."""
    strategy_registry.get_registry().clear()


class TestEnsureBuiltinsRegistered:
    def test_registers_all_builtins(self) -> None:
        ensure_builtins_registered()
        registered = strategy_registry.list_strategies()
        for name in BUILTIN_STRATEGIES:
            assert name in registered

    def test_is_idempotent(self) -> None:
        ensure_builtins_registered()
        ensure_builtins_registered()  # second call must not raise
        assert len(strategy_registry.list_strategies()) == len(BUILTIN_STRATEGIES)


class TestResolveStrategy:
    def test_returns_basestrategy_instance(self) -> None:
        strategy = resolve_strategy("sma_crossover")
        assert isinstance(strategy, BaseStrategy)

    def test_unknown_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            resolve_strategy("does_not_exist")


class TestBuildSessionFactory:
    def test_returns_async_sessionmaker(self) -> None:
        factory = build_session_factory("sqlite+aiosqlite:///:memory:")
        assert isinstance(factory, async_sessionmaker)
        # The bound async engine is exposed via factory.kw["bind"]; both the CLI
        # (`cryptrink/cli.py`) and the web layer rely on this key being present.
        assert "bind" in factory.kw


class TestListBuiltinStrategyNames:
    def test_returns_sorted_names(self) -> None:
        names = list_builtin_strategy_names()
        assert names == sorted(BUILTIN_STRATEGIES.keys())
