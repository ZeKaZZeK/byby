# byby 🤖

**Adaptive trading bot for Bybit** — regime-aware strategy manager with backtest, paper-trading, CI, and monitoring.

[![CI](https://github.com/ZeKaZZeK/byby/actions/workflows/ci.yml/badge.svg)](https://github.com/ZeKaZZeK/byby/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview

`byby` is a modular, Python-based algorithmic trading bot that:

1. **Detects market regime** (TREND_UP, TREND_DOWN, RANGE, HIGH_VOL, ILLIQUID) using technical indicators
2. **Selects strategies** automatically based on the current regime
3. **Manages risk** with hard limits on per-trade risk, daily loss, and total exposure
4. **Executes orders** on Bybit (testnet by default) with idempotency and retry logic
5. **Monitors** performance via Prometheus metrics and Telegram alerts

## Architecture

```
byby/
├── market_data/          # WebSocket + REST client, data aggregation
│   ├── ws_client.py      # Real-time data via Bybit WS
│   ├── rest_client.py    # Historical OHLCV via ccxt
│   └── data_manager.py   # Combines WS + REST; maintains rolling history
├── regime_detector/      # Rule-based regime classification
│   ├── detector.py       # ADX + volatility + spread + momentum → regime
│   └── models.py         # MarketRegime enum, RegimeResult
├── strategies/           # Strategy plugins
│   ├── base.py           # BaseStrategy ABC + DesiredOrder
│   ├── trend_following.py# EMA crossover + ATR stop
│   ├── mean_reversion.py # RSI + Bollinger Bands
│   └── momentum_breakout.py # Donchian channel breakout
├── strategy_manager/     # Regime → strategy selector
│   └── manager.py        # Weights, param overrides, hysteresis
├── execution_engine/     # Order placement and tracking
│   ├── engine.py         # ccxt-based engine with retry + idempotency
│   ├── models.py         # Order, Fill dataclasses
│   └── twap.py           # TWAP slicer for large orders
├── risk_manager/         # Position sizing and risk controls
│   └── manager.py        # Fixed-fractional + vol-adjusted sizing
├── persistence/          # Storage
│   ├── database.py       # SQLAlchemy async ORM (Postgres/TimescaleDB)
│   └── redis_client.py   # Redis ephemeral state + leader lock
├── monitoring/           # Observability
│   ├── metrics.py        # Prometheus counters, gauges, histograms
│   └── alerts.py         # Telegram bot alerts
├── backtest/             # Backtesting harness
│   ├── engine.py         # Bar-by-bar simulation with fees/slippage
│   └── runner.py         # CLI runner + report generation
├── paper_trade/          # Paper trading pipeline
│   └── runner.py         # Full live-data paper trading loop
├── config.py             # Pydantic-settings configuration
└── cli.py                # Main CLI entry point
```

## Regime Detection

The regime detector uses rule-based logic on these features:

| Feature | Description |
|---------|-------------|
| **Volatility** | Rolling std of log-returns over `VOLATILITY_PERIOD` bars |
| **ADX** | Average Directional Index — trend strength |
| **+DI / -DI** | Directional indicators — trend direction |
| **Momentum** | 5-bar and 20-bar rolling returns |
| **Spread %** | Bid-ask spread as fraction of mid-price |
| **Depth Imbalance** | (bid_depth - ask_depth) / total |

### Regime Classification Rules

```
ILLIQUID  → spread_pct > 0.5% OR volume_ratio < 0.1
HIGH_VOL  → volatility > VOLATILITY_HIGH_THRESHOLD
TREND_UP  → ADX > threshold AND +DI > -DI
TREND_DOWN→ ADX > threshold AND -DI > +DI
RANGE     → ADX ≤ threshold (default)
```

Hysteresis prevents rapid regime switching: a new regime must persist for `REGIME_HYSTERESIS_PERIODS` before becoming active.

## Strategy → Regime Mapping

| Regime | Strategies (weight) | Notes |
|--------|---------------------|-------|
| TREND_UP | TrendFollowing (0.8), MomentumBreakout (0.2) | |
| TREND_DOWN | TrendFollowing (0.8), MomentumBreakout (0.2) | |
| RANGE | MeanReversion (1.0) | |
| HIGH_VOL | MeanReversion (0.5) | Wider stops (2.5× ATR) |
| ILLIQUID | — | No trading |
| UNKNOWN | — | No trading |

## Quick Start

### Prerequisites

- Python 3.10+
- Docker & Docker Compose (for full stack)
- Bybit testnet API keys (for paper trading)

### 1. Clone and install

```bash
git clone https://github.com/ZeKaZZeK/byby.git
cd byby
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your Bybit testnet API keys and settings
```

Key settings:

```env
BYBIT_API_KEY=your_testnet_key
BYBIT_API_SECRET=your_testnet_secret
BYBIT_TESTNET=true
TRADING_SYMBOL=BTC/USDT:USDT
MAX_RISK_PER_TRADE=0.005   # 0.5% per trade
MAX_DAILY_LOSS=0.03        # 3% daily loss limit
```

### 3. Run tests

```bash
pytest tests/unit/ tests/integration/ -v
```

### 4. Run backtest

```bash
# With data from Bybit (requires API access):
byby-backtest --symbol BTC/USDT:USDT --start 2023-01-01 --end 2025-01-01 --capital 10000

# With local CSV:
byby-backtest --data-file data/btc_usdt_1m.csv --capital 10000 --output reports/

# Fetch data first:
python scripts/fetch_data.py --symbol BTC/USDT:USDT --start 2023-01-01 --end 2025-01-01
```

### 5. Run paper trading

```bash
byby paper
# or
byby-paper
```

## Docker Deployment

### Full stack (bot + DB + Redis + Prometheus + Grafana)

```bash
cp .env.example .env
# Edit .env

docker-compose up -d
```

Services:
- **Bot**: `localhost:8000` (Prometheus metrics)
- **Prometheus**: `localhost:9090`
- **Grafana**: `localhost:3000` (admin/admin)
- **PostgreSQL**: `localhost:5432`
- **Redis**: `localhost:6379`

### Bot only

```bash
docker build -t byby .
docker run --env-file .env byby
```

## Configuration Reference

All settings can be provided via environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `BYBIT_API_KEY` | | Bybit API key |
| `BYBIT_API_SECRET` | | Bybit API secret |
| `BYBIT_TESTNET` | `true` | Use testnet |
| `TRADING_SYMBOL` | `BTC/USDT:USDT` | Trading pair |
| `MAX_RISK_PER_TRADE` | `0.005` | Max risk per trade (0.5%) |
| `MAX_DAILY_LOSS` | `0.03` | Daily loss limit (3%) |
| `MAX_LEVERAGE` | `5` | Maximum leverage |
| `MAX_CONCURRENT_TRADES` | `3` | Max open positions |
| `TELEGRAM_BOT_TOKEN` | | Telegram bot token for alerts |
| `TELEGRAM_CHAT_ID` | | Telegram chat ID |
| `PROMETHEUS_PORT` | `8000` | Metrics server port |
| `DATABASE_URL` | PostgreSQL URL | Database connection |
| `REDIS_URL` | Redis URL | Redis connection |

See `.env.example` for the full list.

## Risk Management

- **Per-trade sizing**: `risk_amount = equity × MAX_RISK_PER_TRADE`; `quantity = risk_amount / stop_distance`
- **Daily loss limit**: Trading halts when `daily_pnl / equity ≥ MAX_DAILY_LOSS`
- **Max concurrent trades**: Hard limit on open positions
- **Max exposure**: Total notional / equity capped at `MAX_TOTAL_EXPOSURE`
- **SL/TP**: Every order includes stop-loss and take-profit levels

## Monitoring & Alerts

### Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `byby_orders_submitted_total` | Counter | Orders submitted |
| `byby_orders_filled_total` | Counter | Orders filled |
| `byby_daily_pnl_usdt` | Gauge | Daily PnL |
| `byby_equity_usdt` | Gauge | Account equity |
| `byby_open_positions` | Gauge | Open positions |
| `byby_market_regime` | Gauge | Current regime |
| `byby_regime_confidence` | Gauge | Regime confidence |
| `byby_order_latency_seconds` | Histogram | Order latency |

### Telegram Alerts

- 🚨 Daily loss limit hit — trading suspended
- ⚠️ WebSocket disconnection
- 🔴 Unhandled exception
- 📈/📉 Regime change
- 🟢/🔴 Order filled with PnL
- 🚀 Bot deployment

## Development

```bash
# Lint
ruff check byby/ tests/
ruff format byby/ tests/

# Type check
mypy byby/

# Tests with coverage
pytest tests/ --cov=byby --cov-report=term-missing
```

## Security

- **Never commit API keys** — use environment variables or `.env` (git-ignored)
- **Testnet by default** — `BYBIT_TESTNET=true` by default
- **Least privilege** — use read-only + order keys, no withdrawal permissions
- **Structured logging** — secrets are never logged

## License

MIT License. See [LICENSE](LICENSE).