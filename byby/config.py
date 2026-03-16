"""Application configuration using pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Bybit API
    bybit_api_key: str = Field(default="", description="Bybit API key")
    bybit_api_secret: str = Field(default="", description="Bybit API secret")
    bybit_testnet: bool = Field(default=True, description="Use Bybit testnet")
    bybit_base_url: str = Field(
        default="https://api-testnet.bybit.com",
        description="Bybit base URL",
    )

    # Trading
    trading_symbol: str = Field(default="BTC/USDT:USDT", description="Trading symbol")
    trading_timeframe: str = Field(default="1m", description="Trading timeframe")
    max_risk_per_trade: float = Field(default=0.003, description="Max risk per trade (fraction)")  # 0.3%
    max_daily_loss: float = Field(default=0.03, description="Max daily loss (fraction)")
    max_leverage: int = Field(default=5, description="Max leverage")
    max_concurrent_trades: int = Field(default=3, description="Max concurrent trades")
    max_total_exposure: float = Field(default=0.15, description="Max total exposure (fraction)")

    # Database
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="byby")
    postgres_user: str = Field(default="byby")
    postgres_password: str = Field(default="byby_password")
    database_url: str = Field(default="postgresql://byby:byby_password@localhost:5432/byby")

    # Redis
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Monitoring
    prometheus_port: int = Field(default=8000)
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="json")

    # Backtest
    backtest_start_date: str = Field(default="2023-01-01")
    backtest_end_date: str = Field(default="2025-01-01")
    backtest_initial_capital: float = Field(default=10000.0)

    # Regime Detector
    regime_confidence_threshold: float = Field(default=0.65)  # Higher threshold = only strongest signals
    regime_hysteresis_periods: int = Field(default=5)
    adx_period: int = Field(default=14)
    adx_trend_threshold: float = Field(default=25.0)
    volatility_period: int = Field(default=20)
    volatility_high_threshold: float = Field(default=0.02)

    # Paper Trading
    paper_trading: bool = Field(default=True)
    paper_initial_balance: float = Field(default=10000.0)

    @field_validator("max_risk_per_trade", "max_daily_loss", "max_total_exposure")
    @classmethod
    def validate_fractions(cls, v: float) -> float:
        if not 0 < v < 1:
            raise ValueError("Must be between 0 and 1")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
