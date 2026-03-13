"""Unit tests for trading strategies."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from byby.market_data.models import OHLCV, MarketState
from byby.strategies.base import OrderSide, OrderType
from byby.strategies.mean_reversion import MeanReversionStrategy
from byby.strategies.momentum_breakout import MomentumBreakoutStrategy
from byby.strategies.trend_following import TrendFollowingStrategy


def make_trending_candles(n: int = 100, direction: str = "up") -> list[OHLCV]:
    """Generate strongly trending OHLCV data."""
    candles = []
    price = 50000.0
    now = datetime.now(tz=timezone.utc)
    for i in range(n):
        if direction == "up":
            trend = 0.002
        else:
            trend = -0.002
        open_ = price
        close = price * (1 + trend)
        high = max(open_, close) * 1.001
        low = min(open_, close) * 0.999
        candles.append(
            OHLCV(
                timestamp=now - timedelta(minutes=n - i),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=5.0,
                symbol="BTC/USDT:USDT",
            )
        )
        price = close
    return candles


def make_ranging_candles(n: int = 100) -> list[OHLCV]:
    """Generate ranging OHLCV data."""
    import random
    random.seed(123)
    candles = []
    price = 50000.0
    now = datetime.now(tz=timezone.utc)
    for i in range(n):
        open_ = price
        close = 50000.0 + random.uniform(-200, 200)
        high = max(open_, close) * 1.0005
        low = min(open_, close) * 0.9995
        candles.append(
            OHLCV(
                timestamp=now - timedelta(minutes=n - i),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=3.0,
                symbol="BTC/USDT:USDT",
            )
        )
        price = close
    return candles


def make_market_state(candles: list[OHLCV]) -> MarketState:
    return MarketState(
        symbol="BTC/USDT:USDT",
        timestamp=datetime.now(tz=timezone.utc),
        ohlcv_history=candles,
    )


class TestTrendFollowingStrategy:
    def test_insufficient_data_returns_empty(self):
        strategy = TrendFollowingStrategy("test_trend")
        state = make_market_state(make_trending_candles(n=10))
        orders = strategy.generate_signals(state)
        assert orders == []

    def test_default_params(self):
        strategy = TrendFollowingStrategy("test_trend")
        params = strategy.default_params()
        assert "fast_ema" in params
        assert "slow_ema" in params
        assert "atr_period" in params

    def test_update_params(self):
        strategy = TrendFollowingStrategy("test_trend")
        strategy.update_params({"fast_ema": 5})
        assert strategy.params["fast_ema"] == 5

    def test_generates_orders_or_empty(self):
        strategy = TrendFollowingStrategy("test_trend")
        candles = make_trending_candles(n=100)
        state = make_market_state(candles)
        orders = strategy.generate_signals(state)
        assert isinstance(orders, list)

    def test_order_structure(self):
        strategy = TrendFollowingStrategy("test_trend")
        candles = make_trending_candles(n=100)
        state = make_market_state(candles)
        orders = strategy.generate_signals(state)
        for order in orders:
            assert order.symbol == "BTC/USDT:USDT"
            assert order.side in (OrderSide.BUY, OrderSide.SELL)
            assert order.order_type in (OrderType.MARKET, OrderType.LIMIT)
            assert order.stop_loss is not None
            assert order.take_profit is not None
            assert order.strategy_id == "test_trend"


class TestMeanReversionStrategy:
    def test_insufficient_data_returns_empty(self):
        strategy = MeanReversionStrategy("test_mr")
        state = make_market_state(make_ranging_candles(n=5))
        orders = strategy.generate_signals(state)
        assert orders == []

    def test_default_params(self):
        strategy = MeanReversionStrategy("test_mr")
        params = strategy.default_params()
        assert "rsi_period" in params
        assert "bb_period" in params
        assert "rsi_oversold" in params

    def test_generates_valid_orders(self):
        strategy = MeanReversionStrategy("test_mr")
        candles = make_ranging_candles(n=100)
        state = make_market_state(candles)
        orders = strategy.generate_signals(state)
        assert isinstance(orders, list)
        for order in orders:
            assert order.symbol == "BTC/USDT:USDT"

    def test_buy_signal_has_sl_below_price(self):
        strategy = MeanReversionStrategy("test_mr")
        candles = make_ranging_candles(n=100)
        state = make_market_state(candles)
        orders = strategy.generate_signals(state)
        for order in orders:
            if order.side == OrderSide.BUY and order.stop_loss:
                # SL should be below entry for buys
                assert order.stop_loss < (order.price or candles[-1].close)


class TestMomentumBreakoutStrategy:
    def test_insufficient_data_returns_empty(self):
        strategy = MomentumBreakoutStrategy("test_mb")
        state = make_market_state(make_trending_candles(n=10))
        orders = strategy.generate_signals(state)
        assert orders == []

    def test_default_params(self):
        strategy = MomentumBreakoutStrategy("test_mb")
        params = strategy.default_params()
        assert "donchian_period" in params
        assert "atr_sl_multiplier" in params

    def test_generates_valid_orders(self):
        strategy = MomentumBreakoutStrategy("test_mb")
        candles = make_trending_candles(n=100)
        state = make_market_state(candles)
        orders = strategy.generate_signals(state)
        assert isinstance(orders, list)

    def test_no_volume_filter_when_disabled(self):
        strategy = MomentumBreakoutStrategy("test_mb")
        strategy.update_params({"volume_confirmation": False})
        candles = make_trending_candles(n=100)
        state = make_market_state(candles)
        # Should still work without volume filter
        orders = strategy.generate_signals(state)
        assert isinstance(orders, list)
