"""Trend following strategy: EMA crossover + ATR stop."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog

from byby.strategies.base import BaseStrategy, DesiredOrder, OrderSide, OrderType

logger = structlog.get_logger(__name__)


class TrendFollowingStrategy(BaseStrategy):
    """EMA crossover with ATR-based stop loss."""

    def default_params(self) -> dict[str, Any]:
        return {
            "fast_ema": 10,
            "slow_ema": 30,
            "atr_period": 14,
            "atr_sl_multiplier": 2.0,
            "atr_tp_multiplier": 3.0,
            "min_candles": 60,
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
            }
        )

        fast = self.params["fast_ema"]
        slow = self.params["slow_ema"]
        atr_p = self.params["atr_period"]

        ema_fast = df["close"].ewm(span=fast, min_periods=fast).mean()
        ema_slow = df["close"].ewm(span=slow, min_periods=slow).mean()

        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"] - df["close"].shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(span=atr_p, min_periods=atr_p).mean()

        current_price = df["close"].iloc[-1]
        prev_fast = ema_fast.iloc[-2]
        prev_slow = ema_slow.iloc[-2]
        curr_fast = ema_fast.iloc[-1]
        curr_slow = ema_slow.iloc[-1]
        current_atr = atr.iloc[-1]

        if np.isnan(curr_fast) or np.isnan(curr_slow) or np.isnan(current_atr):
            return []

        orders = []
        sl_mult = self.params["atr_sl_multiplier"]
        tp_mult = self.params["atr_tp_multiplier"]

        # Bullish crossover
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            stop_loss = current_price - sl_mult * current_atr
            take_profit = current_price + tp_mult * current_atr
            orders.append(
                DesiredOrder(
                    symbol=market_state.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=0.0,  # will be sized by risk manager
                    stop_loss=round(stop_loss, 2),
                    take_profit=round(take_profit, 2),
                    strategy_id=self.strategy_id,
                    client_order_id=self._make_client_order_id("buy"),
                    metadata={"atr": current_atr, "ema_fast": curr_fast, "ema_slow": curr_slow},
                )
            )
            logger.info("trend_signal_buy", price=current_price, sl=stop_loss, tp=take_profit)

        # Bearish crossover
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
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
                    metadata={"atr": current_atr, "ema_fast": curr_fast, "ema_slow": curr_slow},
                )
            )
            logger.info("trend_signal_sell", price=current_price, sl=stop_loss, tp=take_profit)

        return orders
