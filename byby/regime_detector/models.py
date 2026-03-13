"""Regime detection models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MarketRegime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOL = "HIGH_VOL"
    ILLIQUID = "ILLIQUID"
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeResult:
    regime: MarketRegime
    confidence: float
    timestamp: datetime
    features: dict[str, float] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)

    def is_confident(self, threshold: float = 0.7) -> bool:
        return self.confidence >= threshold
