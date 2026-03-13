"""Execution engine: places and tracks orders on Bybit."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from byby.config import get_settings
from byby.execution_engine.models import Fill, Order, OrderStatus
from byby.strategies.base import DesiredOrder

logger = structlog.get_logger(__name__)


class ExecutionEngine:
    """Manages order placement and tracking via ccxt."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self._exchange: Any = None
        self._orders: dict[str, Order] = {}  # local_id -> Order
        self._fills: list[Fill] = []
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Connect to Bybit exchange."""
        import ccxt.async_support as ccxt
        params: dict[str, Any] = {
            "apiKey": self.settings.bybit_api_key,
            "secret": self.settings.bybit_api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "linear"},
        }
        if self.settings.bybit_testnet:
            params["testnet"] = True

        self._exchange = ccxt.bybit(params)
        logger.info("execution_engine_connected", testnet=self.settings.bybit_testnet)

    async def close(self) -> None:
        """Close exchange connection."""
        if self._exchange:
            await self._exchange.close()
            self._exchange = None

    def _make_local_id(self, desired: DesiredOrder) -> str:
        """Generate unique local order ID."""
        if desired.client_order_id:
            return desired.client_order_id
        return str(uuid.uuid4())[:36]

    async def submit_order(self, desired: DesiredOrder) -> Optional[Order]:
        """Submit a desired order to the exchange."""
        if not self._exchange:
            await self.connect()

        local_id = self._make_local_id(desired)

        # Idempotency: check if already submitted
        async with self._lock:
            if local_id in self._orders:
                existing = self._orders[local_id]
                logger.warning("duplicate_order", local_id=local_id, status=existing.status)
                return existing

        order = Order(
            local_id=local_id,
            symbol=desired.symbol,
            side=desired.side.value,
            order_type=desired.order_type.value,
            quantity=desired.quantity,
            price=desired.price,
            stop_loss=desired.stop_loss,
            take_profit=desired.take_profit,
            strategy_id=desired.strategy_id,
            metadata=desired.metadata,
        )

        async with self._lock:
            self._orders[local_id] = order

        try:
            result = await self._place_order_with_retry(order)
            if result:
                async with self._lock:
                    order.bybit_order_id = result.get("id")
                    order.status = OrderStatus.SUBMITTED
                    order.updated_at = datetime.now(tz=timezone.utc)
                logger.info(
                    "order_submitted",
                    local_id=local_id,
                    bybit_id=order.bybit_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    qty=order.quantity,
                )
                # Place SL/TP if provided
                if desired.stop_loss or desired.take_profit:
                    await self._place_sl_tp(order, desired)
            return order
        except Exception as e:
            async with self._lock:
                order.status = OrderStatus.FAILED
                order.updated_at = datetime.now(tz=timezone.utc)
            logger.error("order_submission_failed", local_id=local_id, error=str(e))
            return order

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _place_order_with_retry(self, order: Order) -> dict:
        """Place order with retry logic."""
        params: dict[str, Any] = {
            "clientOrderId": order.local_id[:36],
        }

        if order.order_type == "limit":
            result = await self._exchange.create_limit_order(
                order.symbol,
                order.side,
                order.quantity,
                order.price,
                params=params,
            )
        else:
            result = await self._exchange.create_market_order(
                order.symbol,
                order.side,
                order.quantity,
                params=params,
            )
        return result

    async def _place_sl_tp(self, order: Order, desired: DesiredOrder) -> None:
        """Place stop-loss and take-profit orders."""
        try:
            params: dict[str, Any] = {"reduceOnly": True}
            if desired.stop_loss:
                sl_side = "sell" if order.side == "buy" else "buy"
                await self._exchange.create_order(
                    order.symbol,
                    "stop",
                    sl_side,
                    order.quantity,
                    desired.stop_loss,
                    params={**params, "triggerPrice": desired.stop_loss, "stopLossPrice": desired.stop_loss},
                )
                logger.info("sl_placed", local_id=order.local_id, sl=desired.stop_loss)

            if desired.take_profit:
                tp_side = "sell" if order.side == "buy" else "buy"
                await self._exchange.create_order(
                    order.symbol,
                    "limit",
                    tp_side,
                    order.quantity,
                    desired.take_profit,
                    params={**params, "takeProfitPrice": desired.take_profit},
                )
                logger.info("tp_placed", local_id=order.local_id, tp=desired.take_profit)
        except Exception as e:
            logger.error("sl_tp_placement_failed", local_id=order.local_id, error=str(e))

    async def cancel_order(self, local_id: str) -> bool:
        """Cancel an order by local ID."""
        async with self._lock:
            order = self._orders.get(local_id)
        if not order or not order.bybit_order_id:
            return False
        try:
            await self._exchange.cancel_order(order.bybit_order_id, order.symbol)
            async with self._lock:
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.now(tz=timezone.utc)
            logger.info("order_cancelled", local_id=local_id)
            return True
        except Exception as e:
            logger.error("cancel_failed", local_id=local_id, error=str(e))
            return False

    async def update_order_status(self, local_id: str) -> Optional[Order]:
        """Fetch and update order status from exchange."""
        async with self._lock:
            order = self._orders.get(local_id)
        if not order or not order.bybit_order_id:
            return None
        try:
            result = await self._exchange.fetch_order(order.bybit_order_id, order.symbol)
            async with self._lock:
                status_map = {
                    "open": OrderStatus.OPEN,
                    "closed": OrderStatus.FILLED,
                    "canceled": OrderStatus.CANCELLED,
                    "partially_filled": OrderStatus.PARTIALLY_FILLED,
                    "rejected": OrderStatus.REJECTED,
                }
                order.status = status_map.get(result.get("status", ""), OrderStatus.PENDING)
                order.filled_quantity = float(result.get("filled", 0))
                order.avg_fill_price = result.get("average")
                order.updated_at = datetime.now(tz=timezone.utc)

                if order.status == OrderStatus.FILLED and order.avg_fill_price:
                    fill = Fill(
                        order_id=local_id,
                        bybit_order_id=order.bybit_order_id,
                        symbol=order.symbol,
                        side=order.side,
                        quantity=order.filled_quantity,
                        price=order.avg_fill_price,
                        timestamp=datetime.now(tz=timezone.utc),
                        fee=float(result.get("fee", {}).get("cost", 0)),
                    )
                    self._fills.append(fill)
            return order
        except Exception as e:
            logger.error("status_update_failed", local_id=local_id, error=str(e))
            return None

    @property
    def orders(self) -> dict[str, Order]:
        return dict(self._orders)

    @property
    def fills(self) -> list[Fill]:
        return list(self._fills)

    @property
    def active_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.is_active]
