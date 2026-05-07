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

    def test_default_db_url_helper_returns_data_path_when_mounted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The auto-detect helper that drives the default factory must
        return the ``/data/cryptrink.db`` path when ``/data`` exists and
        is writable (HF Spaces with a Storage Bucket attached)."""
        from pathlib import Path

        from cryptrink.core import config as config_module

        original_is_dir = Path.is_dir

        def fake_is_dir(self: Path) -> bool:
            if str(self) == "/data":
                return True
            return original_is_dir(self)

        monkeypatch.setattr(Path, "is_dir", fake_is_dir)
        monkeypatch.setattr(
            config_module.os,
            "access",
            lambda path, _mode: str(path) == "/data",
        )

        assert config_module._default_db_url() == "sqlite+aiosqlite:////data/cryptrink.db"

    def test_default_db_url_helper_falls_back_when_no_data_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ``/data`` (local dev, CI), the default stays on the
        process-local ``cryptrink.db`` so existing flows are unchanged."""
        from pathlib import Path

        from cryptrink.core import config as config_module

        original_is_dir = Path.is_dir

        def fake_is_dir(self: Path) -> bool:
            if str(self) == "/data":
                return False
            return original_is_dir(self)

        monkeypatch.setattr(Path, "is_dir", fake_is_dir)

        assert config_module._default_db_url() == "sqlite+aiosqlite:///cryptrink.db"

    def test_db_url_env_override_wins_over_data_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Operators who set DB_URL explicitly must always win over the
        auto-detection (e.g. dev pointing at a tmp file, or pointing at
        a remote postgres in the future)."""
        monkeypatch.setenv("DB_URL", "sqlite+aiosqlite:///custom.db")
        settings = DatabaseSettings()
        assert settings.url == "sqlite+aiosqlite:///custom.db"


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
