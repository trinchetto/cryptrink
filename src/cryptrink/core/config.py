"""Configuration management for Cryptrink."""

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    """Trading execution mode."""

    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"
    SUGGEST = "suggest"


class RevolutXSettings(BaseSettings):
    """Revolut X API configuration."""

    model_config = SettingsConfigDict(env_prefix="REVOLUTX_")

    api_key: SecretStr = Field(default=SecretStr(""), description="Revolut X API key")
    private_key: SecretStr = Field(
        default=SecretStr(""), description="Ed25519 private key for signing"
    )
    base_url: str = Field(
        default="https://x.revolut.com/api",
        description="Revolut X API base URL",
    )
    sandbox: bool = Field(default=True, description="Use sandbox environment")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Ensure base URL doesn't have trailing slash."""
        return v.rstrip("/")


class RiskSettings(BaseSettings):
    """Risk management configuration."""

    model_config = SettingsConfigDict(env_prefix="RISK_")

    max_position_size_pct: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Maximum position size as percentage of portfolio",
    )
    max_daily_loss_pct: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Maximum daily loss before stopping",
    )
    max_drawdown_pct: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Maximum drawdown before stopping",
    )
    default_stop_loss_pct: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description="Default stop loss percentage",
    )
    default_take_profit_pct: float = Field(
        default=0.04,
        ge=0.0,
        le=1.0,
        description="Default take profit percentage",
    )


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    url: str = Field(
        default="sqlite+aiosqlite:///cryptrink.db",
        description="Database connection URL",
    )
    echo: bool = Field(default=False, description="Echo SQL statements")


class NotificationSettings(BaseSettings):
    """Notification configuration."""

    model_config = SettingsConfigDict(env_prefix="NOTIFY_")

    discord_enabled: bool = Field(default=False, description="Enable Discord notifications")
    discord_webhook_url: SecretStr = Field(default=SecretStr(""), description="Discord webhook URL")


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_prefix="CRYPTRINK_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # General settings
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.PAPER,
        description="Trading execution mode",
    )
    default_strategy: str = Field(
        default="sma_crossover",
        description="Default trading strategy",
    )
    symbols: list[str] = Field(
        default=["BTC-EUR", "ETH-EUR"],
        description="Trading symbols",
    )
    log_level: str = Field(default="INFO", description="Logging level")

    # Nested settings
    revolutx: RevolutXSettings = Field(default_factory=RevolutXSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)


def load_config(config_path: str | Path | None = None) -> Settings:
    """Load configuration from file and environment variables.

    Args:
        config_path: Optional path to YAML configuration file.

    Returns:
        Settings object with merged configuration.
    """
    file_settings: dict[str, Any] = {}

    if config_path:
        path = Path(config_path)
        if path.exists():
            with path.open() as f:
                file_settings = yaml.safe_load(f) or {}

    # Environment variables take precedence over file settings
    return Settings(**file_settings)
