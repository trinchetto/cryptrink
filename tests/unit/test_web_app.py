"""Smoke tests for the Cryptrink Gradio web app."""

from __future__ import annotations

import pytest

from cryptrink.strategies import registry as strategy_registry
from cryptrink.web import state as web_state

gr = pytest.importorskip("gradio")

from cryptrink.web.app import build_demo  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run each test against a fresh in-memory DB and a clean strategy registry."""
    monkeypatch.setenv("DB_URL", "sqlite+aiosqlite:///:memory:")
    strategy_registry.get_registry().clear()
    web_state.reset_runtime()
    yield
    web_state.reset_runtime()
    strategy_registry.get_registry().clear()


def test_build_demo_returns_blocks() -> None:
    demo = build_demo()
    assert isinstance(demo, gr.Blocks)


def test_build_demo_initialises_runtime_and_registers_builtins() -> None:
    build_demo()
    runtime = web_state.get_runtime()
    assert runtime.session_factory is not None
    # build_demo() must have registered the built-in strategies via get_runtime().
    assert "sma_crossover" in strategy_registry.list_strategies()


def test_get_runtime_is_cached() -> None:
    first = web_state.get_runtime()
    second = web_state.get_runtime()
    assert first is second
