"""Tests for configuration management."""

import pytest

from cryptrink.core.config import (
    DatabaseSettings,
    ExecutionMode,
    RevolutXSettings,
    RiskSettings,
    Settings,
    load_config,
)


class TestExecutionMode:
    """Tests for ExecutionMode enum."""

    def test_execution_modes_exist(self) -> None:
        """Test all expected execution modes exist."""
        assert ExecutionMode.LIVE == "live"
        assert ExecutionMode.PAPER == "paper"
        assert ExecutionMode.BACKTEST == "backtest"
        assert ExecutionMode.SUGGEST == "suggest"


class TestRevolutXSettings:
    """Tests for RevolutX configuration."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default configuration values."""
        # Clear any environment variables that might be set
        monkeypatch.delenv("REVOLUTX_BASE_URL", raising=False)
        monkeypatch.delenv("REVOLUTX_API_KEY", raising=False)
        monkeypatch.delenv("REVOLUTX_PRIVATE_KEY", raising=False)
        monkeypatch.delenv("REVOLUTX_PRIVATE_KEY_PATH", raising=False)

        settings = RevolutXSettings()
        assert settings.base_url == "https://revx.revolut.com/api/1.0"

    def test_base_url_strips_trailing_slash(self) -> None:
        """Test that trailing slash is removed from base URL."""
        settings = RevolutXSettings(base_url="https://revx.revolut.com/api/1.0/")
        assert settings.base_url == "https://revx.revolut.com/api/1.0"


class TestRiskSettings:
    """Tests for risk management configuration."""

    def test_default_values(self) -> None:
        """Test default risk settings."""
        settings = RiskSettings()
        assert settings.max_position_size_pct == 0.1
        assert settings.max_daily_loss_pct == 0.05
        assert settings.max_drawdown_pct == 0.15
        assert settings.default_stop_loss_pct == 0.02
        assert settings.default_take_profit_pct == 0.04

    def test_validation_bounds(self) -> None:
        """Test that risk percentages must be between 0 and 1."""
        with pytest.raises(ValueError):
            RiskSettings(max_position_size_pct=1.5)

        with pytest.raises(ValueError):
            RiskSettings(max_daily_loss_pct=-0.1)


class TestDatabaseSettings:
    """Tests for database configuration."""

    def test_default_sqlite(self) -> None:
        """Test default SQLite configuration."""
        settings = DatabaseSettings()
        assert "sqlite" in settings.url
        assert settings.echo is False


class TestSettings:
    """Tests for main application settings."""

    def test_default_values(self) -> None:
        """Test default settings."""
        settings = Settings()
        assert settings.execution_mode == ExecutionMode.PAPER
        assert settings.default_strategy == "sma_crossover"
        assert "BTC-EUR" in settings.symbols
        assert settings.log_level == "INFO"

    def test_nested_settings(self) -> None:
        """Test nested settings are properly initialized."""
        settings = Settings()
        assert isinstance(settings.revolutx, RevolutXSettings)
        assert isinstance(settings.risk, RiskSettings)
        assert isinstance(settings.database, DatabaseSettings)


class TestLoadConfig:
    """Tests for configuration loading."""

    def test_load_config_without_file(self) -> None:
        """Test loading config without a file uses defaults."""
        config = load_config(None)
        assert config.execution_mode == ExecutionMode.PAPER

    def test_load_config_nonexistent_file(self) -> None:
        """Test loading config with nonexistent file uses defaults."""
        config = load_config("/nonexistent/path/config.yaml")
        assert config.execution_mode == ExecutionMode.PAPER
