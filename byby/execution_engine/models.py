"""Execution engine models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class Order:
    """Represents an order in the execution engine."""

    local_id: str
    symbol: str
    side: str  # "buy" or "sell"
    order_type: str  # "market" or "limit"
    quantity: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    bybit_order_id: str | None = None
    filled_quantity: float = 0.0
    avg_fill_price: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)

    @property
    def is_filled(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

    @property
    def is_active(self) -> bool:
        return self.status in (
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        )


@dataclass
class Fill:
    """Represents an order fill."""

    order_id: str
    bybit_order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: datetime
    fee: float = 0.0
    fee_currency: str = "USDT"
