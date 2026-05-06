"""Smoke tests for the Cryptrink Gradio web app."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from cryptrink.core.config import (
    DatabaseSettings,
    NotificationSettings,
    RevolutXSettings,
    RiskSettings,
    Settings,
)
from cryptrink.strategies import registry as strategy_registry
from cryptrink.web import state as web_state

gr = pytest.importorskip("gradio")

from cryptrink.web.app import build_demo, log_credential_status  # noqa: E402


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


class TestLogCredentialStatus:
    """structlog routes through ``PrintLoggerFactory`` (direct stdout), so
    these tests use ``capsys`` rather than ``caplog``."""

    def test_does_not_leak_api_key_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        secret = "totally_secret_revolutx_api_key_xyz"
        settings = Settings(
            revolutx=RevolutXSettings(api_key=SecretStr(secret)),
            risk=RiskSettings(),
            database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
            notifications=NotificationSettings(),
        )
        log_credential_status(settings)
        captured = capsys.readouterr()
        # The literal secret value must never appear in the log output.
        assert secret not in captured.out
        assert secret not in captured.err

    def test_does_not_leak_private_key_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        secret = "U0VDUkVUX1BSSVZBVEVfS0VZX0RPX05PVF9MRUFL"
        settings = Settings(
            revolutx=RevolutXSettings(api_key=SecretStr("ok"), private_key=SecretStr(secret)),
            risk=RiskSettings(),
            database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
            notifications=NotificationSettings(),
        )
        log_credential_status(settings)
        captured = capsys.readouterr()
        assert secret not in captured.out
        assert secret not in captured.err

    def test_does_not_leak_discord_webhook(self, capsys: pytest.CaptureFixture[str]) -> None:
        secret_url = "https://discord.com/api/webhooks/SECRET/TOKEN"
        settings = Settings(
            revolutx=RevolutXSettings(),
            risk=RiskSettings(),
            database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
            notifications=NotificationSettings(
                discord_enabled=True,
                discord_webhook_url=SecretStr(secret_url),
            ),
        )
        log_credential_status(settings)
        captured = capsys.readouterr()
        assert secret_url not in captured.out
        assert secret_url not in captured.err

    def test_classifies_db_url_kind(self, capsys: pytest.CaptureFixture[str]) -> None:
        settings = Settings(
            revolutx=RevolutXSettings(),
            risk=RiskSettings(),
            database=DatabaseSettings(url="sqlite+aiosqlite:////data/cryptrink.db"),
            notifications=NotificationSettings(),
        )
        log_credential_status(settings)
        captured = capsys.readouterr()
        assert "sqlite-persistent" in captured.out

    def test_logs_true_when_credentials_present(self, capsys: pytest.CaptureFixture[str]) -> None:
        settings = Settings(
            revolutx=RevolutXSettings(api_key=SecretStr("k"), private_key=SecretStr("p")),
            risk=RiskSettings(),
            database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
            notifications=NotificationSettings(),
        )
        log_credential_status(settings)
        out = capsys.readouterr().out
        # Expect the boolean flags to read as True in the log line.
        assert "revolutx_api_key=True" in out or "revolutx_api_key=true" in out
        assert "revolutx_private_key=True" in out or "revolutx_private_key=true" in out
