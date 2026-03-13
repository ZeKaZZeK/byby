"""Prometheus metrics for the trading bot."""
from __future__ import annotations

import time

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Trading metrics
ORDERS_SUBMITTED = Counter(
    "byby_orders_submitted_total",
    "Total orders submitted",
    ["symbol", "side", "strategy"],
)
ORDERS_FILLED = Counter(
    "byby_orders_filled_total",
    "Total orders filled",
    ["symbol", "side", "strategy"],
)
ORDERS_FAILED = Counter(
    "byby_orders_failed_total",
    "Total orders failed",
    ["symbol", "reason"],
)
DAILY_PNL = Gauge(
    "byby_daily_pnl_usdt",
    "Current daily PnL in USDT",
)
EQUITY = Gauge(
    "byby_equity_usdt",
    "Current account equity in USDT",
)
OPEN_POSITIONS = Gauge(
    "byby_open_positions",
    "Number of open positions",
)
TOTAL_EXPOSURE = Gauge(
    "byby_total_exposure_pct",
    "Total exposure as fraction of equity",
)
REGIME_LABEL = Gauge(
    "byby_market_regime",
    "Current market regime (encoded as integer)",
    ["regime"],
)
REGIME_CONFIDENCE = Gauge(
    "byby_regime_confidence",
    "Confidence of current regime detection",
)
WS_RECONNECTS = Counter(
    "byby_ws_reconnects_total",
    "WebSocket reconnection count",
)
ORDER_LATENCY = Histogram(
    "byby_order_latency_seconds",
    "Order submission latency",
    ["order_type"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0],
)
SIGNAL_GENERATED = Counter(
    "byby_signals_generated_total",
    "Total signals generated",
    ["strategy", "side"],
)


def start_metrics_server(port: int = 8000) -> None:
    """Start Prometheus metrics HTTP server."""
    start_http_server(port)


def record_order_submitted(symbol: str, side: str, strategy: str) -> None:
    ORDERS_SUBMITTED.labels(symbol=symbol, side=side, strategy=strategy).inc()


def record_order_filled(symbol: str, side: str, strategy: str) -> None:
    ORDERS_FILLED.labels(symbol=symbol, side=side, strategy=strategy).inc()


def record_order_failed(symbol: str, reason: str) -> None:
    ORDERS_FAILED.labels(symbol=symbol, reason=reason).inc()


def update_pnl_metrics(daily_pnl: float, equity: float) -> None:
    DAILY_PNL.set(daily_pnl)
    EQUITY.set(equity)


def update_position_metrics(open_positions: int, total_exposure: float) -> None:
    OPEN_POSITIONS.set(open_positions)
    TOTAL_EXPOSURE.set(total_exposure)


def update_regime_metrics(regime: str, confidence: float) -> None:
    REGIME_LABEL.labels(regime=regime).set(1)
    REGIME_CONFIDENCE.set(confidence)
