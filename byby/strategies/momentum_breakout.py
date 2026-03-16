"""Momentum breakout strategy: Donchian channel + ATR stop."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog

from byby.strategies.base import BaseStrategy, DesiredOrder, OrderSide, OrderType

logger = structlog.get_logger(__name__)


class MomentumBreakoutStrategy(BaseStrategy):
    """Donchian channel breakout with ATR stop."""

    def default_params(self) -> dict[str, Any]:
        return {
            "donchian_period": 80,  # Much longer = fewer but better breakouts
            "atr_period": 20,
            "atr_sl_multiplier": 2.5,
            "atr_tp_multiplier": 4.0,  # 1.6:1 reward ratio
            "volume_confirmation": True,
            "volume_multiplier": 2.0,  # Stricter volume filter
            "min_candles": 100,
        }

    def generate_signals(self, market_state, regime_result=None) -> list[DesiredOrder]:
        candles = market_state.ohlcv_history
        min_c = self.params["min_candles"]
        if len(candles) < min_c:
            return []

        df = pd.DataFrame(
            {
                "high": [c.high for c in candles],
                "low": [c.low for c in candles],
                "close": [c.close for c in candles],
                "volume": [c.volume for c in candles],
            }
        )

        don_p = self.params["donchian_period"]
        atr_p = self.params["atr_period"]

        # Donchian channel (use previous period to avoid look-ahead)
        upper_channel = df["high"].rolling(don_p).max().shift(1)
        lower_channel = df["low"].rolling(don_p).min().shift(1)

        # ATR
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"] - df["close"].shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(span=atr_p, min_periods=atr_p).mean()

        # Volume filter
        avg_volume = df["volume"].rolling(20).mean()

        current_price = df["close"].iloc[-1]
        current_high = df["high"].iloc[-1]
        current_low = df["low"].iloc[-1]
        current_upper = upper_channel.iloc[-1]
        current_lower = lower_channel.iloc[-1]
        current_atr = atr.iloc[-1]
        current_volume = df["volume"].iloc[-1]
        avg_vol = avg_volume.iloc[-1]

        if any(np.isnan(v) for v in [current_upper, current_lower, current_atr]):
            return []

        volume_ok = True
        if self.params["volume_confirmation"] and not np.isnan(avg_vol) and avg_vol > 0:
            volume_ok = current_volume >= avg_vol * self.params["volume_multiplier"]

        sl_mult = self.params["atr_sl_multiplier"]
        tp_mult = self.params["atr_tp_multiplier"]
        orders = []

        # Upside breakout
        if current_high > current_upper and volume_ok:
            stop_loss = current_price - sl_mult * current_atr
            take_profit = current_price + tp_mult * current_atr
            orders.append(
                DesiredOrder(
                    symbol=market_state.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=0.0,
                    stop_loss=round(stop_loss, 2),
                    take_profit=round(take_profit, 2),
                    strategy_id=self.strategy_id,
                    client_order_id=self._make_client_order_id("buy"),
                    metadata={"donchian_upper": current_upper, "atr": current_atr},
                )
            )
            logger.info("breakout_signal_buy", price=current_price, channel_upper=current_upper)

        # Downside breakout
        elif current_low < current_lower and volume_ok:
            stop_loss = current_price + sl_mult * current_atr
            take_profit = current_price - tp_mult * current_atr
            orders.append(
                DesiredOrder(
                    symbol=market_state.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=0.0,
                    stop_loss=round(stop_loss, 2),
                    take_profit=round(take_profit, 2),
                    strategy_id=self.strategy_id,
                    client_order_id=self._make_client_order_id("sell"),
                    metadata={"donchian_lower": current_lower, "atr": current_atr},
                )
            )
            logger.info("breakout_signal_sell", price=current_price, channel_lower=current_lower)

        return orders
