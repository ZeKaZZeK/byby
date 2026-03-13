"""Market data manager: combines WS and REST, stores history."""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from byby.config import get_settings
from byby.market_data.models import OHLCV, MarketState, OrderBook, Trade
from byby.market_data.rest_client import BybitRESTClient
from byby.market_data.ws_client import BybitWSClient

logger = structlog.get_logger(__name__)

MAX_OHLCV_HISTORY = 500


class MarketDataManager:
    """Manages real-time and historical market data."""

    def __init__(
        self,
        symbol: str,
        timeframe: str = "1m",
        testnet: bool = True,
        max_history: int = MAX_OHLCV_HISTORY,
        settings=None,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.testnet = testnet
        self.max_history = max_history
        self.settings = settings or get_settings()

        self._ohlcv_history: deque[OHLCV] = deque(maxlen=max_history)
        self._orderbook: Optional[OrderBook] = None
        self._last_trade: Optional[Trade] = None

        self._rest_client = BybitRESTClient(settings=self.settings)
        self._ws_client: Optional[BybitWSClient] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_connected = False

    async def start(self) -> None:
        """Start data manager: fetch history then connect WS."""
        await self._rest_client.connect()
        await self._fetch_initial_history()
        await self._start_websocket()

    async def stop(self) -> None:
        """Stop data manager."""
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._ws_client:
            await self._ws_client.stop()
        await self._rest_client.close()

    async def _fetch_initial_history(self) -> None:
        """Fetch initial OHLCV history via REST."""
        try:
            # Calculate lookback based on timeframe to request the right number of candles
            timeframe_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
            minutes_per_candle = timeframe_minutes.get(self.timeframe, 1)
            since = datetime.now(tz=timezone.utc) - timedelta(minutes=self.max_history * minutes_per_candle)
            candles = await self._rest_client.fetch_ohlcv(
                self.symbol, self.timeframe, since=since, limit=self.max_history
            )
            for candle in candles:
                self._ohlcv_history.append(candle)
            logger.info("initial_history_loaded", count=len(candles))
        except Exception as e:
            logger.error("initial_history_error", error=str(e))

    async def _start_websocket(self) -> None:
        """Start WebSocket connection in background."""
        self._ws_client = BybitWSClient(
            symbol=self.symbol,
            testnet=self.testnet,
            on_ohlcv=self._on_ohlcv,
            on_orderbook=self._on_orderbook,
            on_trade=self._on_trade,
        )
        self._ws_task = asyncio.create_task(self._ws_client.start())

    async def _on_ohlcv(self, ohlcv: OHLCV) -> None:
        self._ohlcv_history.append(ohlcv)
        logger.debug("ohlcv_received", symbol=ohlcv.symbol, close=ohlcv.close)

    async def _on_orderbook(self, orderbook: OrderBook) -> None:
        self._orderbook = orderbook

    async def _on_trade(self, trade: Trade) -> None:
        self._last_trade = trade

    async def get_market_state(self) -> MarketState:
        """Get current aggregated market state."""
        return MarketState(
            symbol=self.symbol,
            timestamp=datetime.now(tz=timezone.utc),
            ohlcv_history=list(self._ohlcv_history),
            orderbook=self._orderbook,
            last_trade=self._last_trade,
        )

    async def fetch_ohlcv_rest(
        self,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[OHLCV]:
        """Fallback REST fetch."""
        return await self._rest_client.fetch_ohlcv(
            self.symbol, self.timeframe, since=since, limit=limit
        )

    @property
    def ohlcv_history(self) -> list[OHLCV]:
        return list(self._ohlcv_history)
