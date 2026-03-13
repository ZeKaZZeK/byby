"""TWAP/VWAP execution for large orders."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from byby.execution_engine.models import Order
from byby.strategies.base import DesiredOrder, OrderType

if TYPE_CHECKING:
    from byby.execution_engine.engine import ExecutionEngine

logger = structlog.get_logger(__name__)


class TWAPExecutor:
    """Splits large orders into slices for TWAP execution."""

    def __init__(
        self,
        engine: ExecutionEngine,
        num_slices: int = 5,
        interval_seconds: float = 60.0,
    ) -> None:
        self.engine = engine
        self.num_slices = num_slices
        self.interval_seconds = interval_seconds

    async def execute(self, desired: DesiredOrder) -> list[Order]:
        """Execute order using TWAP over multiple slices."""
        total_qty = desired.quantity
        slice_qty = round(total_qty / self.num_slices, 6)
        orders = []

        logger.info(
            "twap_start",
            symbol=desired.symbol,
            total_qty=total_qty,
            slices=self.num_slices,
            interval=self.interval_seconds,
        )

        for i in range(self.num_slices):
            qty = (
                slice_qty
                if i < self.num_slices - 1
                else total_qty - slice_qty * (self.num_slices - 1)
            )
            slice_order = DesiredOrder(
                symbol=desired.symbol,
                side=desired.side,
                order_type=OrderType.MARKET,
                quantity=max(qty, 0.001),
                strategy_id=desired.strategy_id,
                client_order_id=f"{desired.client_order_id}_twap_{i}"[:36],
                metadata={**desired.metadata, "twap_slice": i, "twap_total": self.num_slices},
            )
            order = await self.engine.submit_order(slice_order)
            if order:
                orders.append(order)
                logger.info("twap_slice_submitted", slice=i, qty=qty, order_id=order.local_id)

            if i < self.num_slices - 1:
                await asyncio.sleep(self.interval_seconds)

        logger.info("twap_complete", total_slices=len(orders))
        return orders
