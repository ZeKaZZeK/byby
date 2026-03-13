"""Market data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderBookSide(str, Enum):
    BID = "bid"
    ASK = "ask"


@dataclass
class OHLCV:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str = ""
    timeframe: str = "1m"


@dataclass
class OrderBookEntry:
    price: float
    size: float
    side: OrderBookSide


@dataclass
class OrderBook:
    symbol: str
    timestamp: datetime
    bids: list[OrderBookEntry] = field(default_factory=list)
    asks: list[OrderBookEntry] = field(default_factory=list)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_pct(self) -> Optional[float]:
        if self.mid_price and self.spread:
            return self.spread / self.mid_price
        return None

    @property
    def bid_depth(self) -> float:
        return sum(e.size for e in self.bids)

    @property
    def ask_depth(self) -> float:
        return sum(e.size for e in self.asks)

    @property
    def depth_imbalance(self) -> Optional[float]:
        """Depth imbalance: positive = more bids, negative = more asks."""
        total = self.bid_depth + self.ask_depth
        if total == 0:
            return None
        return (self.bid_depth - self.ask_depth) / total


@dataclass
class Trade:
    timestamp: datetime
    symbol: str
    price: float
    size: float
    side: str  # "buy" or "sell"


@dataclass
class MarketState:
    """Aggregated market state for strategy consumption."""
    symbol: str
    timestamp: datetime
    ohlcv_history: list[OHLCV] = field(default_factory=list)
    orderbook: Optional[OrderBook] = None
    last_trade: Optional[Trade] = None

    @property
    def last_ohlcv(self) -> Optional[OHLCV]:
        return self.ohlcv_history[-1] if self.ohlcv_history else None

    @property
    def last_price(self) -> Optional[float]:
        if self.orderbook and self.orderbook.mid_price:
            return self.orderbook.mid_price
        if self.last_ohlcv:
            return self.last_ohlcv.close
        return None
