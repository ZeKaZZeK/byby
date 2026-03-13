"""Unit tests for market data models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from byby.market_data.models import (
    OHLCV,
    MarketState,
    OrderBook,
    OrderBookEntry,
    OrderBookSide,
)


class TestOrderBook:
    def make_orderbook(self, bid_price=49990, ask_price=50010):
        return OrderBook(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            bids=[OrderBookEntry(price=bid_price, size=1.0, side=OrderBookSide.BID)],
            asks=[OrderBookEntry(price=ask_price, size=1.0, side=OrderBookSide.ASK)],
        )

    def test_best_bid_ask(self):
        ob = self.make_orderbook()
        assert ob.best_bid == 49990
        assert ob.best_ask == 50010

    def test_mid_price(self):
        ob = self.make_orderbook()
        assert ob.mid_price == pytest.approx(50000.0)

    def test_spread(self):
        ob = self.make_orderbook()
        assert ob.spread == pytest.approx(20.0)

    def test_spread_pct(self):
        ob = self.make_orderbook()
        assert ob.spread_pct == pytest.approx(0.0004, rel=0.01)

    def test_empty_orderbook(self):
        ob = OrderBook(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
        )
        assert ob.best_bid is None
        assert ob.best_ask is None
        assert ob.mid_price is None
        assert ob.spread is None

    def test_depth_imbalance(self):
        ob = OrderBook(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            bids=[OrderBookEntry(price=49990, size=3.0, side=OrderBookSide.BID)],
            asks=[OrderBookEntry(price=50010, size=1.0, side=OrderBookSide.ASK)],
        )
        # More bids than asks
        assert ob.depth_imbalance > 0


class TestMarketState:
    def test_last_price_from_orderbook(self):
        ob = OrderBook(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            bids=[OrderBookEntry(price=49990, size=1.0, side=OrderBookSide.BID)],
            asks=[OrderBookEntry(price=50010, size=1.0, side=OrderBookSide.ASK)],
        )
        state = MarketState(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            orderbook=ob,
        )
        assert state.last_price == pytest.approx(50000.0)

    def test_last_price_from_ohlcv(self):
        ohlcv = OHLCV(
            timestamp=datetime.now(tz=timezone.utc),
            open=50000,
            high=50100,
            low=49900,
            close=50050,
            volume=5.0,
            symbol="BTC/USDT:USDT",
        )
        state = MarketState(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            ohlcv_history=[ohlcv],
        )
        assert state.last_price == 50050

    def test_last_ohlcv(self):
        ohlcv1 = OHLCV(
            timestamp=datetime.now(tz=timezone.utc),
            open=1,
            high=2,
            low=0.5,
            close=1.5,
            volume=1,
            symbol="X",
        )
        ohlcv2 = OHLCV(
            timestamp=datetime.now(tz=timezone.utc),
            open=2,
            high=3,
            low=1.5,
            close=2.5,
            volume=1,
            symbol="X",
        )
        state = MarketState(
            symbol="X", timestamp=datetime.now(tz=timezone.utc), ohlcv_history=[ohlcv1, ohlcv2]
        )
        assert state.last_ohlcv == ohlcv2
