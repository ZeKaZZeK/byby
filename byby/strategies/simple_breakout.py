"""
Simple breakout strategy without regime complexity.
Just tracks price action directly - no regime detection overhead.
"""
import pandas as pd
import numpy as np
from typing import Optional
from byby.strategies.base import BaseStrategy
from byby.regime_detector.models import MarketRegime


class SimpleBreakoutStrategy(BaseStrategy):
    """
    Pure breakout strategy:
    - Buy: Price breaks above 20-period Donchian high + volume
    - Sell: Price breaks below 20-period Donchian low OR hits stop/take profit
    
    This avoids regime detection complexity and trades on simple patterns.
    """
    
    def __init__(self, symbol: str = "BTC/USDT:USDT", timeframe: str = "1m"):
        super().__init__(symbol, timeframe)
        self.donchian_high_period = 20  # Shorter for more frequent trades
        self.donchian_low_period = 20
        self.volume_sma_period = 20
        self.volume_threshold = 1.3  # More lenient
        self.atr_period = 14
        self.atr_sl_multiplier = 1.5  # Tighter stop loss
        self.atr_tp_multiplier = 2.0  # 1.33:1 reward ratio
        
    def analyze(self, data: pd.DataFrame) -> dict:
        """Simple technical analysis without regime."""
        
        if len(data) < max(self.donchian_high_period, self.atr_period) + 1:
            return {"signal": "NO_SIGNAL", "confidence": 0.0}
        
        # Donchian breakout
        high_20 = data['high'].rolling(window=self.donchian_high_period).max()
        low_20 = data['low'].rolling(window=self.donchian_low_period).min()
        
        # Volume analysis
        vol_sma = data['volume'].rolling(window=self.volume_sma_period).mean()
        volume_ratio = data['volume'] / vol_sma
        
        # ATR for stop loss sizing
        high_low = data['high'] - data['low']
        high_close = (data['high'] - data['close'].shift(1)).abs()
        low_close = (data['low'] - data['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=self.atr_period).mean()
        
        current_price = data['close'].iloc[-1]
        current_high_20 = high_20.iloc[-1]
        current_low_20 = low_20.iloc[-1]
        current_volume = volume_ratio.iloc[-1]
        current_atr = atr.iloc[-1]
        
        # Check for breakout signals
        if pd.isna(current_high_20) or pd.isna(current_atr):
            return {"signal": "NO_SIGNAL", "confidence": 0.0}
        
        # BUY SIGNAL: Break above 20-period high + higher than average volume
        if current_price > current_high_20 and current_volume > self.volume_threshold:
            stop_loss = current_price - (self.atr_sl_multiplier * current_atr)
            take_profit = current_price + (self.atr_tp_multiplier * current_atr)
            
            # Confidence based on how far we are into the breakout
            distance_pct = (current_price - high_20.iloc[-20:-1].max()) / high_20.iloc[-20:-1].max()
            # Cap at recent high, normalize to 0.5-0.9 confidence
            confidence = min(0.9, 0.5 + distance_pct * 2)
            
            return {
                "signal": "BUY",
                "confidence": confidence,
                "entry": current_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "atr": current_atr,
            }
        
        # SELL SIGNAL: Break below 20-period low
        if current_price < current_low_20:
            stop_loss = current_price + (self.atr_sl_multiplier * current_atr)
            take_profit = current_price - (self.atr_tp_multiplier * current_atr)
            
            confidence = 0.7  # Lower for shorts
            
            return {
                "signal": "SELL",
                "confidence": confidence,
                "entry": current_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "atr": current_atr,
            }
        
        return {"signal": "NO_SIGNAL", "confidence": 0.0}
    
    def on_candle(self, candle: dict) -> Optional[dict]:
        """Process single candle."""
        self.candles.append(candle)
        
        if len(self.candles) < 21:
            return None  # Need enough data
        
        df = pd.DataFrame(self.candles)
        analysis = self.analyze(df)
        
        if analysis["signal"] in ["BUY", "SELL"]:
            return {
                "action": analysis["signal"],
                "confidence": analysis["confidence"],
                "entry_price": analysis.get("entry", candle["close"]),
            }
        
        return None


class ReverseStrategy(BaseStrategy):
    """
    Mean reversion focused - targets pullbacks in trends.
    Buy on oversold, sell on overbought.
    Simpler than current mean_reversion with better thresholds.
    """
    
    def __init__(self, symbol: str = "BTC/USDT:USDT", timeframe: str = "1m"):
        super().__init__(symbol, timeframe)
        self.rsi_period = 14
        self.rsi_oversold = 25  # More strict
        self.rsi_overbought = 75
        self.bb_period = 20
        self.bb_std = 2.0
        self.min_volume_ratio = 1.1
        
    def analyze(self, data: pd.DataFrame) -> dict:
        """Mean reversion analysis."""
        
        if len(data) < max(self.rsi_period, self.bb_period) + 1:
            return {"signal": "NO_SIGNAL", "confidence": 0.0}
        
        # RSI
        delta = data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / (loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        # Bollinger Bands
        sma = data['close'].rolling(window=self.bb_period).mean()
        std = data['close'].rolling(window=self.bb_period).std()
        bb_upper = sma + self.bb_std * std
        bb_lower = sma - self.bb_std * std
        
        # Volume
        vol_sma = data['volume'].rolling(window=self.bb_period).mean()
        vol_ratio = data['volume'] / (vol_sma + 1e-10)
        
        current_price = data['close'].iloc[-1]
        current_rsi = rsi.iloc[-1]
        current_vol_ratio = vol_ratio.iloc[-1]
        current_bb_upper = bb_upper.iloc[-1]
        current_bb_lower = bb_lower.iloc[-1]
        
        if pd.isna(current_rsi) or pd.isna(current_bb_upper):
            return {"signal": "NO_SIGNAL", "confidence": 0.0}
        
        # BUY: Oversold + near lower band + higher volume
        if current_rsi < self.rsi_oversold and current_price < current_bb_lower:
            distance_to_lower = (current_bb_lower - current_price) / (current_bb_upper - current_bb_lower + 1e-10)
            confidence = min(0.85, 0.5 + distance_to_lower)
            
            return {
                "signal": "BUY",
                "confidence": confidence,
                "rsi": current_rsi,
                "bb_lower": current_bb_lower,
            }
        
        # SELL: Overbought + near upper band
        if current_rsi > self.rsi_overbought and current_price > current_bb_upper:
            distance_to_upper = (current_price - current_bb_upper) / (current_bb_upper - current_bb_lower + 1e-10)
            confidence = min(0.85, 0.5 + distance_to_upper)
            
            return {
                "signal": "SELL",
                "confidence": confidence,
                "rsi": current_rsi,
                "bb_upper": current_bb_upper,
            }
        
        return {"signal": "NO_SIGNAL", "confidence": 0.0}
    
    def on_candle(self, candle: dict) -> Optional[dict]:
        """Process single candle."""
        self.candles.append(candle)
        
        if len(self.candles) < 21:
            return None
        
        df = pd.DataFrame(self.candles)
        analysis = self.analyze(df)
        
        if analysis["signal"] in ["BUY", "SELL"]:
            return {
                "action": analysis["signal"],
                "confidence": analysis["confidence"],
            }
        
        return None
