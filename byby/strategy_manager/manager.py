"""Strategy manager: selects strategies based on market regime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from byby.regime_detector.models import MarketRegime, RegimeResult
from byby.strategies.base import BaseStrategy, DesiredOrder
from byby.strategies.mean_reversion import MeanReversionStrategy
from byby.strategies.momentum_breakout import MomentumBreakoutStrategy
from byby.strategies.trend_following import TrendFollowingStrategy

logger = structlog.get_logger(__name__)


@dataclass
class StrategyWeight:
    strategy: BaseStrategy
    weight: float = 1.0
    param_overrides: dict[str, Any] = field(default_factory=dict)


# Default regime -> strategy mapping with weights and parameter adjustments
REGIME_STRATEGY_MAP: dict[MarketRegime, list[StrategyWeight]] = {
    MarketRegime.TREND_UP: [
        StrategyWeight(
            strategy=TrendFollowingStrategy("trend_follow_up"),
            weight=0.8,
        ),
        StrategyWeight(
            strategy=MomentumBreakoutStrategy("momentum_up"),
            weight=0.2,
        ),
    ],
    MarketRegime.TREND_DOWN: [
        StrategyWeight(
            strategy=TrendFollowingStrategy("trend_follow_down"),
            weight=0.8,
        ),
        StrategyWeight(
            strategy=MomentumBreakoutStrategy("momentum_down"),
            weight=0.2,
        ),
    ],
    MarketRegime.RANGE: [
        StrategyWeight(
            strategy=MeanReversionStrategy("mean_rev_range"),
            weight=1.0,
        ),
    ],
    MarketRegime.HIGH_VOL: [
        # In high volatility, use mean reversion with tighter params
        StrategyWeight(
            strategy=MeanReversionStrategy("mean_rev_highvol"),
            weight=0.5,
            param_overrides={
                "atr_sl_multiplier": 2.5,  # wider stops
                "rsi_oversold": 20,
                "rsi_overbought": 80,
            },
        ),
    ],
    MarketRegime.ILLIQUID: [],  # No trading in illiquid markets
    MarketRegime.UNKNOWN: [],  # No trading in unknown regime
}


class StrategyManager:
    """Selects and manages active strategies based on market regime."""

    def __init__(
        self,
        regime_strategy_map: dict[MarketRegime, list[StrategyWeight]] | None = None,
        confidence_threshold: float = 0.65,  # Higher threshold = only strongest signals
        settings=None,
    ) -> None:
        from byby.config import get_settings

        self.settings = settings or get_settings()
        self.regime_strategy_map = regime_strategy_map or REGIME_STRATEGY_MAP
        self.confidence_threshold = confidence_threshold
        self._current_regime: MarketRegime | None = None
        self._active_strategies: list[StrategyWeight] = []

    def _get_active_strategies(self, regime: MarketRegime) -> list[StrategyWeight]:
        """Get active strategies for regime."""
        return self.regime_strategy_map.get(regime, [])

    def _apply_param_overrides(self, sw: StrategyWeight) -> None:
        """Apply parameter overrides to strategy."""
        if sw.param_overrides:
            sw.strategy.update_params(sw.param_overrides)

    def generate_signals(
        self,
        market_state,
        regime_result: RegimeResult,
    ) -> list[DesiredOrder]:
        """Generate signals based on current regime."""
        if not regime_result.is_confident(self.confidence_threshold):
            logger.info(
                "low_confidence_regime",
                regime=regime_result.regime,
                confidence=regime_result.confidence,
            )
            return []

        regime = regime_result.regime

        if regime != self._current_regime:
            logger.info(
                "regime_change",
                from_regime=self._current_regime,
                to_regime=regime,
                confidence=regime_result.confidence,
            )
            self._current_regime = regime
            self._active_strategies = self._get_active_strategies(regime)
            for sw in self._active_strategies:
                self._apply_param_overrides(sw)

        if not self._active_strategies:
            logger.info("no_active_strategies", regime=regime)
            return []

        all_orders: list[DesiredOrder] = []
        for sw in self._active_strategies:
            try:
                orders = sw.strategy.generate_signals(market_state, regime_result)
                # Scale quantity by weight (if already sized)
                for order in orders:
                    order.metadata["weight"] = sw.weight
                all_orders.extend(orders)
                logger.debug(
                    "strategy_signals",
                    strategy=sw.strategy.strategy_id,
                    count=len(orders),
                )
            except Exception as e:
                logger.error(
                    "strategy_error",
                    strategy=sw.strategy.strategy_id,
                    error=str(e),
                )

        return all_orders

    @property
    def current_regime(self) -> MarketRegime | None:
        return self._current_regime

    @property
    def active_strategy_ids(self) -> list[str]:
        return [sw.strategy.strategy_id for sw in self._active_strategies]
