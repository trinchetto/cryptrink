"""Configuration management for Cryptrink."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load environment variables from .env.local if it exists (but not during tests)
if os.getenv("PYTEST_CURRENT_TEST") is None:
    load_dotenv(".env.local")


class ExecutionMode(StrEnum):
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
        default=SecretStr(""), description="Ed25519 private key for signing (base64)"
    )
    private_key_path: str | None = Field(
        default=None, description="Path to PEM file containing Ed25519 private key"
    )
    base_url: str = Field(
        default="https://revx.revolut.com/api/1.0",
        description="Revolut X API base URL (includes /api/1.0 prefix)",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Ensure base URL doesn't have trailing slash."""
        return v.rstrip("/")

    def get_private_key(self) -> str:
        """Get the private key, loading from file if needed.

        Returns:
            Base64-encoded private key string (raw 32-byte seed).

        Raises:
            ValueError: If neither private_key nor private_key_path is set.
        """
        import base64

        # If private_key is already set, use it
        if self.private_key.get_secret_value():
            return self.private_key.get_secret_value()

        # Otherwise, try to load from file
        if self.private_key_path:
            key_path = Path(self.private_key_path)
            if not key_path.exists():
                msg = f"Private key file not found: {self.private_key_path}"
                raise ValueError(msg)

            # Load PEM file and extract raw Ed25519 seed (32 bytes)
            try:
                from cryptography.hazmat.backends import default_backend
                from cryptography.hazmat.primitives import serialization

                pem_data = key_path.read_bytes()
                private_key_obj = serialization.load_pem_private_key(
                    pem_data,
                    password=None,
                    backend=default_backend(),
                )

                # Extract raw 32-byte seed
                raw_private = private_key_obj.private_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PrivateFormat.Raw,
                    encryption_algorithm=serialization.NoEncryption(),
                )

                # Return as base64-encoded string
                return base64.b64encode(raw_private).decode("ascii")

            except Exception as e:
                msg = f"Failed to load private key from {self.private_key_path}: {e}"
                raise ValueError(msg) from e

        msg = "Either REVOLUTX_PRIVATE_KEY or REVOLUTX_PRIVATE_KEY_PATH must be set"
        raise ValueError(msg)


class SizingStrategy(StrEnum):
    """Position sizing strategy.

    - FIXED_FRACTIONAL: Risk a fixed percentage per trade based on stop-loss distance
    - VOLATILITY_BASED: Scale position size inversely with market volatility (ATR)
    - KELLY_CRITERION: Optimal sizing based on win rate and risk/reward ratio
    """

    FIXED_FRACTIONAL = "fixed_fractional"
    VOLATILITY_BASED = "volatility_based"
    KELLY_CRITERION = "kelly_criterion"


class RiskSettings(BaseSettings):
    """Risk management configuration."""

    model_config = SettingsConfigDict(env_prefix="RISK_")

    # Position Sizing (Phase 6.1)
    sizing_strategy: SizingStrategy = Field(
        default=SizingStrategy.FIXED_FRACTIONAL,
        description="Position sizing strategy to use",
    )
    risk_per_trade: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description="Percentage of account to risk per trade (0-1)",
    )
    kelly_fraction: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Fraction of Kelly criterion to use (0.25 = quarter-Kelly)",
    )
    volatility_multiplier: float = Field(
        default=2.0,
        gt=0.0,
        description="Multiplier for ATR in volatility-based sizing",
    )

    # Position Limits
    max_position_size_pct: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Maximum position size as percentage of portfolio",
    )
    max_open_positions: int = Field(
        default=5,
        ge=1,
        description="Maximum number of open positions",
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

    # Stop-Loss / Take-Profit Defaults
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


def _default_db_url() -> str:
    """Pick a default DB URL based on what's mounted at process startup.

    On HF Spaces with a Storage Bucket mounted at ``/data`` (the
    documented persistent path), we want the SQLite file to land there
    so it survives factory rebuilds. When ``/data`` exists AND is
    writable, default to ``/data/cryptrink.db``; otherwise keep the
    process-local ``cryptrink.db`` so local dev and CI are unaffected.

    The ``DB_URL`` env var still wins — pydantic-settings honours it
    before this factory runs.
    """
    persistent = Path("/data")
    if persistent.is_dir() and os.access(persistent, os.W_OK):
        return "sqlite+aiosqlite:////data/cryptrink.db"
    return "sqlite+aiosqlite:///cryptrink.db"


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    url: str = Field(
        default_factory=_default_db_url,
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
