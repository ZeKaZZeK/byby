# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-03-13

### Added

#### Core Architecture
- Modular Python package structure: `market_data`, `regime_detector`, `strategies`, `strategy_manager`, `execution_engine`, `risk_manager`, `persistence`, `monitoring`, `backtest`, `paper_trade`
- Pydantic-settings configuration with `.env.example`
- Structured logging via `structlog` (JSON and console output)

#### Market Data
- Bybit WebSocket client with automatic reconnection and exponential backoff
- Orderbook delta merging for real-time book maintenance
- Bybit REST client via `ccxt` for historical OHLCV data
- `MarketDataManager` combining WS and REST with bounded history deque

#### Regime Detector
- Rule-based detector using ADX, rolling volatility (std log-returns), bid-ask spread, depth imbalance, and momentum
- Five regimes: `TREND_UP`, `TREND_DOWN`, `RANGE`, `HIGH_VOL`, `ILLIQUID`
- Confidence score per detection
- Hysteresis to prevent rapid regime switching
- Regime history storage

#### Trading Strategies
- **TrendFollowing**: EMA crossover (fast/slow EMAs) with ATR-based stop-loss and take-profit
- **MeanReversion**: RSI + Bollinger Bands with ATR stop
- **MomentumBreakout**: Donchian channel breakout with volume confirmation and ATR stop
- All strategies implement `BaseStrategy` with `generate_signals()` interface
- Runtime parameter updates via `update_params()`

#### Strategy Manager
- Regime-to-strategy mapping with weights
- Automatic parameter overrides per regime (e.g., wider stops in HIGH_VOL)
- Confidence threshold gating for regime changes

#### Execution Engine
- `ccxt`-based async order placement (market + limit orders)
- Idempotency via `clientOrderId` mapping (`local_id ↔ bybitOrderId`)
- 3-attempt retry with exponential backoff via `tenacity`
- Stop-loss and take-profit bracket order placement
- Order status polling and fill tracking
- TWAP executor for large order slicing

#### Risk Manager
- Fixed-fractional + volatility-adjusted position sizing
- Hard daily loss limit with trading halt
- Max concurrent trades enforcement
- Max total exposure enforcement
- Minimum quantity enforcement

#### Backtest Engine
- Bar-by-bar simulation on minute OHLCV data
- Fee modeling (0.06% taker)
- Slippage modeling (configurable bps)
- SL/TP exit simulation
- Performance metrics: PnL, Sharpe ratio, MaxDrawdown, win rate, trade count
- CSV report output (equity curve, trade log)

#### Paper Trading
- Full live-data paper trading pipeline
- Regime detection → signal generation → paper fill → position tracking
- SL/TP monitoring with simulated exits
- Prometheus metrics integration
- Telegram alert integration

#### Persistence
- SQLAlchemy async ORM with Postgres/TimescaleDB
- Tables: `ohlcv`, `regime_history`, `orders`, `fills`, `pnl_history`
- Redis client for ephemeral regime/risk state caching
- Distributed leader lock via Redis NX/EX pattern

#### Monitoring
- Prometheus metrics (10+ counters, gauges, histograms)
- Prometheus HTTP server (configurable port)
- Telegram alerter for critical events

#### Infrastructure
- `Dockerfile` (python:3.11-slim, non-root user)
- `docker-compose.yml` with bot, TimescaleDB, Redis, Prometheus, Grafana
- GitHub Actions CI: lint (ruff), tests (pytest + coverage ≥ 60%), build, Docker build
- `.gitignore` with comprehensive exclusions

#### Tests
- 53 unit and integration tests
- Coverage ≥ 53% overall; core modules (regime detector, risk manager, strategies): 83–100%
- Mocked integration tests for paper trading scenarios

#### Documentation
- Comprehensive `README.md` with architecture diagram, setup, configuration, and deployment
- `CHANGELOG.md` (this file)
- `.env.example` with all configuration options
