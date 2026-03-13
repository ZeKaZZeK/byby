"""Rule-based market regime detector."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import structlog

from byby.config import get_settings
from byby.market_data.models import MarketState
from byby.regime_detector.models import MarketRegime, RegimeResult

logger = structlog.get_logger(__name__)


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Average Directional Index."""
    delta_high = high.diff()
    delta_low = low.diff()

    plus_dm = pd.Series(
        np.where((delta_high > delta_low.abs()) & (delta_high > 0), delta_high, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((delta_low.abs() > delta_high) & (delta_low < 0), delta_low.abs(), 0.0),
        index=low.index,
    )

    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(span=period, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(span=period, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, min_periods=period).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(span=period, min_periods=period).mean()
    return adx, plus_di, minus_di


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=period, min_periods=period).mean()


class RegimeDetector:
    """Rule-based market regime detector with hysteresis."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self._history: deque[RegimeResult] = deque(maxlen=100)
        self._current_regime: Optional[MarketRegime] = None
        self._regime_count: int = 0  # consecutive periods with same candidate

    def detect(self, market_state: MarketState) -> RegimeResult:
        """Detect market regime from market state."""
        candles = market_state.ohlcv_history
        min_candles = max(
            self.settings.adx_period * 2,
            self.settings.volatility_period * 2,
        )

        if len(candles) < min_candles:
            result = RegimeResult(
                regime=MarketRegime.UNKNOWN,
                confidence=0.0,
                timestamp=datetime.now(tz=timezone.utc),
                features={},
                details={"reason": "insufficient_data"},
            )
            self._history.append(result)
            return result

        df = pd.DataFrame(
            {
                "open": [c.open for c in candles],
                "high": [c.high for c in candles],
                "low": [c.low for c in candles],
                "close": [c.close for c in candles],
                "volume": [c.volume for c in candles],
            }
        )

        features = self._compute_features(df, market_state)
        regime, confidence = self._classify(features, market_state)
        regime = self._apply_hysteresis(regime)

        result = RegimeResult(
            regime=regime,
            confidence=confidence,
            timestamp=datetime.now(tz=timezone.utc),
            features=features,
        )
        self._history.append(result)
        self._current_regime = regime
        return result

    def _compute_features(self, df: pd.DataFrame, market_state: MarketState) -> dict[str, float]:
        """Compute regime features."""
        features: dict[str, float] = {}

        # Rolling volatility (std of log returns)
        log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        period = self.settings.volatility_period
        if len(log_returns) >= period:
            features["volatility"] = float(log_returns.tail(period).std())
            # Annualize based on bars per year for common timeframes; default assumes 1m bars
            timeframe = getattr(market_state, "timeframe", None)
            if timeframe is None and market_state.ohlcv_history:
                timeframe = market_state.ohlcv_history[0].timeframe
            bars_per_year = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760, "4h": 2190, "1d": 365}
            multiplier = bars_per_year.get(timeframe or "1m", 525600)
            features["volatility_annualized"] = features["volatility"] * np.sqrt(multiplier)
        else:
            features["volatility"] = 0.0
            features["volatility_annualized"] = 0.0

        # ADX
        adx_period = self.settings.adx_period
        if len(df) >= adx_period * 2:
            adx, plus_di, minus_di = _compute_adx(df["high"], df["low"], df["close"], adx_period)
            features["adx"] = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 0.0
            features["plus_di"] = float(plus_di.iloc[-1]) if not np.isnan(plus_di.iloc[-1]) else 0.0
            features["minus_di"] = float(minus_di.iloc[-1]) if not np.isnan(minus_di.iloc[-1]) else 0.0
        else:
            features["adx"] = 0.0
            features["plus_di"] = 0.0
            features["minus_di"] = 0.0

        # Momentum (rolling returns)
        if len(df) >= 20:
            features["momentum_5"] = float((df["close"].iloc[-1] / df["close"].iloc[-6]) - 1)
            features["momentum_20"] = float((df["close"].iloc[-1] / df["close"].iloc[-21]) - 1)
        else:
            features["momentum_5"] = 0.0
            features["momentum_20"] = 0.0

        # Bid-ask spread and order book depth
        ob = market_state.orderbook
        if ob:
            features["spread_pct"] = ob.spread_pct or 0.0
            features["bid_depth"] = ob.bid_depth
            features["ask_depth"] = ob.ask_depth
            features["depth_imbalance"] = ob.depth_imbalance or 0.0
        else:
            features["spread_pct"] = 0.0
            features["bid_depth"] = 0.0
            features["ask_depth"] = 0.0
            features["depth_imbalance"] = 0.0

        # Volume activity
        if len(df) >= 20:
            avg_vol = df["volume"].tail(20).mean()
            features["volume_ratio"] = float(df["volume"].iloc[-1] / avg_vol) if avg_vol > 0 else 1.0
        else:
            features["volume_ratio"] = 1.0

        return features

    def _classify(
        self, features: dict[str, float], market_state: MarketState
    ) -> tuple[MarketRegime, float]:
        """Classify market regime from features."""
        vol = features.get("volatility", 0.0)
        adx = features.get("adx", 0.0)
        plus_di = features.get("plus_di", 0.0)
        minus_di = features.get("minus_di", 0.0)
        spread_pct = features.get("spread_pct", 0.0)
        volume_ratio = features.get("volume_ratio", 1.0)
        momentum_20 = features.get("momentum_20", 0.0)

        # ILLIQUID: very high spread or very low volume
        if spread_pct > 0.005 or volume_ratio < 0.1:
            confidence = min(1.0, max(spread_pct / 0.005, (0.1 - volume_ratio) / 0.1) * 0.8 + 0.5)
            return MarketRegime.ILLIQUID, min(confidence, 1.0)

        # HIGH_VOL: volatility above threshold
        high_vol_threshold = self.settings.volatility_high_threshold
        if vol > high_vol_threshold:
            confidence = min(1.0, 0.5 + (vol - high_vol_threshold) / high_vol_threshold * 0.5)
            return MarketRegime.HIGH_VOL, confidence

        # TREND: strong ADX
        trend_threshold = self.settings.adx_trend_threshold
        if adx > trend_threshold:
            if plus_di > minus_di:
                confidence = min(1.0, 0.5 + (adx - trend_threshold) / trend_threshold * 0.5)
                # Boost confidence with momentum
                if momentum_20 > 0.01:
                    confidence = min(1.0, confidence + 0.1)
                return MarketRegime.TREND_UP, confidence
            else:
                confidence = min(1.0, 0.5 + (adx - trend_threshold) / trend_threshold * 0.5)
                if momentum_20 < -0.01:
                    confidence = min(1.0, confidence + 0.1)
                return MarketRegime.TREND_DOWN, confidence

        # RANGE: low ADX, low volatility
        confidence = min(1.0, 0.5 + (trend_threshold - adx) / trend_threshold * 0.5)
        return MarketRegime.RANGE, confidence

    def _apply_hysteresis(self, candidate: MarketRegime) -> MarketRegime:
        """Apply hysteresis to avoid rapid regime switching."""
        hysteresis = self.settings.regime_hysteresis_periods
        if self._current_regime is None:
            return candidate
        if candidate == self._current_regime:
            self._regime_count = 0
            return self._current_regime
        self._regime_count += 1
        if self._regime_count >= hysteresis:
            self._regime_count = 0
            return candidate
        return self._current_regime

    @property
    def regime_history(self) -> list[RegimeResult]:
        return list(self._history)

    @property
    def current_regime(self) -> Optional[MarketRegime]:
        return self._current_regime
