"""Bybit REST client for historical data and fallback."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import ccxt.async_support as ccxt
import structlog

from byby.config import get_settings
from byby.market_data.models import OHLCV

logger = structlog.get_logger(__name__)


class BybitRESTClient:
    """Async Bybit REST client using ccxt."""

    def __init__(self, settings=None) -> None:
        if settings is None:
            settings = get_settings()
        self.settings = settings
        self._exchange: ccxt.bybit | None = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def connect(self) -> None:
        params: dict[str, Any] = {
            "apiKey": self.settings.bybit_api_key,
            "secret": self.settings.bybit_api_secret,
            "enableRateLimit": True,
        }
        if self.settings.bybit_testnet:
            params["testnet"] = True
            params["options"] = {"defaultType": "linear"}

        self._exchange = ccxt.bybit(params)
        logger.info("rest_client_connected", testnet=self.settings.bybit_testnet)

    async def close(self) -> None:
        if self._exchange:
            await self._exchange.close()
            self._exchange = None

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[OHLCV]:
        """Fetch historical OHLCV data."""
        if not self._exchange:
            await self.connect()

        since_ms = int(since.timestamp() * 1000) if since else None

        try:
            raw = await self._exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=since_ms, limit=limit
            )
        except Exception as e:
            logger.error("rest_fetch_ohlcv_error", symbol=symbol, error=str(e))
            raise

        result = []
        for row in raw:
            ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc)
            result.append(
                OHLCV(
                    timestamp=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    symbol=symbol,
                    timeframe=timeframe,
                )
            )
        logger.info("rest_fetched_ohlcv", symbol=symbol, count=len(result))
        return result

    async def fetch_balance(self) -> dict[str, Any]:
        """Fetch account balance."""
        if not self._exchange:
            await self.connect()
        try:
            return await self._exchange.fetch_balance()
        except Exception as e:
            logger.error("rest_fetch_balance_error", error=str(e))
            raise

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker."""
        if not self._exchange:
            await self.connect()
        try:
            return await self._exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error("rest_fetch_ticker_error", symbol=symbol, error=str(e))
            raise
