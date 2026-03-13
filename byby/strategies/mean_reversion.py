"""Mean reversion strategy: RSI + Bollinger Bands."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog

from byby.strategies.base import BaseStrategy, DesiredOrder, OrderSide, OrderType

logger = structlog.get_logger(__name__)


class MeanReversionStrategy(BaseStrategy):
    """RSI/Bollinger Bands mean reversion strategy."""

    def default_params(self) -> dict[str, Any]:
        return {
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "bb_period": 20,
            "bb_std": 2.0,
            "atr_period": 14,
            "atr_sl_multiplier": 1.5,
            "min_candles": 50,
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

        rsi_p = self.params["rsi_period"]
        bb_p = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        atr_p = self.params["atr_period"]

        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(span=rsi_p, min_periods=rsi_p).mean()
        avg_loss = loss.ewm(span=rsi_p, min_periods=rsi_p).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        # Bollinger Bands
        sma = df["close"].rolling(bb_p).mean()
        std = df["close"].rolling(bb_p).std()
        upper_band = sma + bb_std * std
        lower_band = sma - bb_std * std

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

        current_price = df["close"].iloc[-1]
        current_rsi = rsi.iloc[-1]
        current_upper = upper_band.iloc[-1]
        current_lower = lower_band.iloc[-1]
        current_sma = sma.iloc[-1]
        current_atr = atr.iloc[-1]

        if any(np.isnan(v) for v in [current_rsi, current_upper, current_lower, current_atr]):
            return []

        sl_mult = self.params["atr_sl_multiplier"]
        orders = []

        # Oversold: price below lower band AND RSI oversold
        if current_price < current_lower and current_rsi < self.params["rsi_oversold"]:
            stop_loss = current_price - sl_mult * current_atr
            take_profit = current_sma  # target mean
            orders.append(
                DesiredOrder(
                    symbol=market_state.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=0.0,
                    price=round(current_lower, 2),
                    stop_loss=round(stop_loss, 2),
                    take_profit=round(take_profit, 2),
                    strategy_id=self.strategy_id,
                    client_order_id=self._make_client_order_id("buy"),
                    metadata={"rsi": current_rsi, "bb_lower": current_lower},
                )
            )
            logger.info("mean_rev_signal_buy", rsi=current_rsi, price=current_price)

        # Overbought: price above upper band AND RSI overbought
        elif current_price > current_upper and current_rsi > self.params["rsi_overbought"]:
            stop_loss = current_price + sl_mult * current_atr
            take_profit = current_sma
            orders.append(
                DesiredOrder(
                    symbol=market_state.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=0.0,
                    price=round(current_upper, 2),
                    stop_loss=round(stop_loss, 2),
                    take_profit=round(take_profit, 2),
                    strategy_id=self.strategy_id,
                    client_order_id=self._make_client_order_id("sell"),
                    metadata={"rsi": current_rsi, "bb_upper": current_upper},
                )
            )
            logger.info("mean_rev_signal_sell", rsi=current_rsi, price=current_price)

        return orders
