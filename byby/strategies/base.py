"""Base strategy interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class DesiredOrder:
    """Represents a desired order from a strategy."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None  # None for market orders
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy_id: str = ""
    client_order_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base strategy."""

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None) -> None:
        self.strategy_id = strategy_id
        self.params: dict[str, Any] = params or self.default_params()

    @abstractmethod
    def default_params(self) -> dict[str, Any]:
        """Return default parameters."""
        ...

    @abstractmethod
    def generate_signals(self, market_state, regime_result=None) -> list[DesiredOrder]:
        """Generate trading signals."""
        ...

    def update_params(self, new_params: dict[str, Any]) -> None:
        """Update parameters at runtime."""
        self.params.update(new_params)

    def _make_client_order_id(self, suffix: str = "") -> str:
        ts = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        return f"{self.strategy_id}_{ts}_{suffix}"[:36]
