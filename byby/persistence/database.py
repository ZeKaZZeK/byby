"""Database connection and models using SQLAlchemy async."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from byby.config import get_settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    pass


class OHLCVRecord(Base):
    __tablename__ = "ohlcv"
    __table_args__ = (
        Index("ix_ohlcv_symbol_timeframe_ts", "symbol", "timeframe", "timestamp"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False)
    timeframe = Column(String(10), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)


class RegimeRecord(Base):
    __tablename__ = "regime_history"
    __table_args__ = (
        Index("ix_regime_symbol_ts", "symbol", "timestamp"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    regime = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False)
    features = Column(Text)  # JSON


class OrderRecord(Base):
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    local_id = Column(String(50), unique=True, nullable=False, index=True)
    bybit_order_id = Column(String(50), index=True)
    symbol = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)
    order_type = Column(String(20), nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    status = Column(String(30), nullable=False)
    strategy_id = Column(String(100))
    filled_quantity = Column(Float, default=0.0)
    avg_fill_price = Column(Float)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    metadata_json = Column(Text)


class FillRecord(Base):
    __tablename__ = "fills"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_id = Column(String(50), nullable=False, index=True)
    bybit_order_id = Column(String(50))
    symbol = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    fee_currency = Column(String(20), default="USDT")
    timestamp = Column(DateTime(timezone=True), nullable=False)


class PnLRecord(Base):
    __tablename__ = "pnl_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    equity = Column(Float, nullable=False)
    daily_pnl = Column(Float, nullable=False)
    total_pnl = Column(Float, nullable=False)
    open_positions = Column(Integer, default=0)


async def get_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    # Convert to async URL
    async_url = url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, echo=False, pool_pre_ping=True)
    return engine


async def create_tables(engine) -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_tables_created")


def get_session_maker(engine) -> async_sessionmaker:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
