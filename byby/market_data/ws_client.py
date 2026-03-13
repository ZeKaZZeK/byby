"""Bybit WebSocket client for real-time market data."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from byby.market_data.models import OHLCV, OrderBook, OrderBookEntry, OrderBookSide, Trade

logger = structlog.get_logger(__name__)

BYBIT_WS_TESTNET = "wss://stream-testnet.bybit.com/v5/public/linear"
BYBIT_WS_MAINNET = "wss://stream.bybit.com/v5/public/linear"


class BybitWSClient:
    """Bybit WebSocket client with automatic reconnection."""

    def __init__(
        self,
        symbol: str,
        testnet: bool = True,
        on_ohlcv: Callable[[OHLCV], Coroutine] | None = None,
        on_orderbook: Callable[[OrderBook], Coroutine] | None = None,
        on_trade: Callable[[Trade], Coroutine] | None = None,
        ping_interval: int = 20,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
    ) -> None:
        self.symbol = symbol
        self.ws_url = BYBIT_WS_TESTNET if testnet else BYBIT_WS_MAINNET
        self.on_ohlcv = on_ohlcv
        self.on_orderbook = on_orderbook
        self.on_trade = on_trade
        self.ping_interval = ping_interval
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay
        self._running = False
        self._ws: Any = None
        self._orderbook_cache: dict[str, list[OrderBookEntry]] = {"bids": [], "asks": []}

    async def start(self) -> None:
        self._running = True
        delay = self.reconnect_delay
        while self._running:
            try:
                await self._connect()
                delay = self.reconnect_delay  # reset on success
            except (ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                if not self._running:
                    break
                logger.warning("ws_disconnected", error=str(e), reconnect_in=delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_reconnect_delay)
            except Exception as e:
                logger.error("ws_unexpected_error", error=str(e))
                if not self._running:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_reconnect_delay)

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _connect(self) -> None:
        bybit_symbol = self.symbol.replace("/", "").replace(":USDT", "")
        subscriptions = []
        if self.on_ohlcv:
            subscriptions.append(f"kline.1.{bybit_symbol}")
        if self.on_orderbook:
            subscriptions.append(f"orderbook.25.{bybit_symbol}")
        if self.on_trade:
            subscriptions.append(f"publicTrade.{bybit_symbol}")

        logger.info("ws_connecting", url=self.ws_url, symbol=bybit_symbol)
        async with websockets.connect(
            self.ws_url,
            ping_interval=self.ping_interval,
            ping_timeout=10,
        ) as ws:
            self._ws = ws
            # Subscribe
            sub_msg = {"op": "subscribe", "args": subscriptions}
            await ws.send(json.dumps(sub_msg))
            logger.info("ws_subscribed", topics=subscriptions)

            async for raw_msg in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw_msg)
                    await self._handle_message(msg)
                except json.JSONDecodeError:
                    logger.warning("ws_invalid_json", raw=raw_msg[:200])
                except Exception as e:
                    logger.error("ws_message_error", error=str(e))

    async def _handle_message(self, msg: dict) -> None:
        topic = msg.get("topic", "")
        data = msg.get("data", {})

        if topic.startswith("kline."):
            await self._handle_kline(data)
        elif topic.startswith("orderbook."):
            msg_type = msg.get("type", "snapshot")
            await self._handle_orderbook(data, msg_type)
        elif topic.startswith("publicTrade."):
            await self._handle_trades(data)

    async def _handle_kline(self, data: list | dict) -> None:
        if not self.on_ohlcv:
            return
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not item.get("confirm", False):
                continue  # only process confirmed (closed) candles
            ts = datetime.fromtimestamp(int(item["start"]) / 1000, tz=timezone.utc)
            ohlcv = OHLCV(
                timestamp=ts,
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(item["volume"]),
                symbol=self.symbol,
                timeframe="1m",
            )
            await self.on_ohlcv(ohlcv)

    async def _handle_orderbook(self, data: dict, msg_type: str) -> None:
        if not self.on_orderbook:
            return

        def parse_entries(raw: list, side: OrderBookSide) -> list[OrderBookEntry]:
            return [
                OrderBookEntry(price=float(p), size=float(s), side=side)
                for p, s in raw
            ]

        if msg_type == "snapshot":
            self._orderbook_cache["bids"] = parse_entries(data.get("b", []), OrderBookSide.BID)
            self._orderbook_cache["asks"] = parse_entries(data.get("a", []), OrderBookSide.ASK)
        else:  # delta
            bid_updates = {float(p): float(s) for p, s in data.get("b", [])}
            ask_updates = {float(p): float(s) for p, s in data.get("a", [])}

            # Update bids
            current_bids = {e.price: e.size for e in self._orderbook_cache["bids"]}
            current_bids.update(bid_updates)
            current_bids = {p: s for p, s in current_bids.items() if s > 0}
            self._orderbook_cache["bids"] = [
                OrderBookEntry(price=p, size=s, side=OrderBookSide.BID)
                for p, s in sorted(current_bids.items(), reverse=True)
            ]

            # Update asks
            current_asks = {e.price: e.size for e in self._orderbook_cache["asks"]}
            current_asks.update(ask_updates)
            current_asks = {p: s for p, s in current_asks.items() if s > 0}
            self._orderbook_cache["asks"] = [
                OrderBookEntry(price=p, size=s, side=OrderBookSide.ASK)
                for p, s in sorted(current_asks.items())
            ]

        ts = datetime.now(tz=timezone.utc)
        orderbook = OrderBook(
            symbol=self.symbol,
            timestamp=ts,
            bids=self._orderbook_cache["bids"][:25],
            asks=self._orderbook_cache["asks"][:25],
        )
        await self.on_orderbook(orderbook)

    async def _handle_trades(self, data: list) -> None:
        if not self.on_trade:
            return
        for item in data:
            ts = datetime.fromtimestamp(int(item["T"]) / 1000, tz=timezone.utc)
            trade = Trade(
                timestamp=ts,
                symbol=self.symbol,
                price=float(item["p"]),
                size=float(item["v"]),
                side="buy" if item["S"] == "Buy" else "sell",
            )
            await self.on_trade(trade)
