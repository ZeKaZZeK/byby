"""Backtest runner script."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import click
import pandas as pd
import structlog

from byby.backtest.engine import BacktestConfig, BacktestEngine
from byby.config import get_settings
from byby.logging_config import configure_logging
from byby.market_data.models import OHLCV
from byby.market_data.rest_client import BybitRESTClient
from byby.regime_detector.detector import RegimeDetector
from byby.strategy_manager.manager import StrategyManager

logger = structlog.get_logger(__name__)


async def fetch_data(symbol: str, start_date: str, end_date: str) -> list[OHLCV]:
    """Fetch historical OHLCV data for backtest."""
    settings = get_settings()
    client = BybitRESTClient(settings=settings)
    await client.connect()

    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    all_candles: list[OHLCV] = []
    current = start

    try:
        while current < end:
            candles = await client.fetch_ohlcv(symbol, "1m", since=current, limit=1000)
            if not candles:
                break
            all_candles.extend(candles)
            current = candles[-1].timestamp
            if len(candles) < 1000:
                break
            logger.info("fetched_data", count=len(all_candles), up_to=str(current))
    finally:
        await client.close()

    # Remove duplicates and sort
    seen = set()
    unique = []
    for c in all_candles:
        key = (c.timestamp, c.symbol)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return sorted(unique, key=lambda c: c.timestamp)


def save_report(result, output_dir: Path) -> None:
    """Save backtest report."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Summary JSON
    summary = result.summary()
    summary_path = output_dir / "backtest_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Trade log CSV
    trades_data = []
    for t in result.trades:
        trades_data.append({
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "symbol": t.symbol,
            "side": t.side,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "fee": t.fee,
            "exit_reason": t.exit_reason,
            "strategy_id": t.strategy_id,
        })
    if trades_data:
        pd.DataFrame(trades_data).to_csv(output_dir / "trades.csv", index=False)

    # Equity curve CSV
    equity_data = [{"timestamp": ts.isoformat(), "equity": eq} for ts, eq in result.equity_curve]
    pd.DataFrame(equity_data).to_csv(output_dir / "equity_curve.csv", index=False)

    logger.info("report_saved", path=str(output_dir))
    print(f"\n{'='*50}")
    print("BACKTEST REPORT")
    print('='*50)
    for k, v in summary.items():
        print(f"  {k:30s}: {v}")
    print('='*50)


@click.command()
@click.option("--symbol", default="BTC/USDT:USDT", help="Trading symbol")
@click.option("--start", default=None, help="Start date YYYY-MM-DD")
@click.option("--end", default=None, help="End date YYYY-MM-DD")
@click.option("--capital", default=10000.0, help="Initial capital")
@click.option("--output", default="reports", help="Output directory")
@click.option("--data-file", default=None, help="Load OHLCV data from CSV instead of fetching")
def main(symbol, start, end, capital, output, data_file):
    """Run backtest."""
    configure_logging()
    settings = get_settings()

    start_date = start or settings.backtest_start_date
    end_date = end or settings.backtest_end_date

    config = BacktestConfig(
        initial_capital=capital,
        max_risk_per_trade=settings.max_risk_per_trade,
        max_daily_loss=settings.max_daily_loss,
    )

    strategy_manager = StrategyManager(
        confidence_threshold=settings.regime_confidence_threshold,
    )

    async def run():
        if data_file:
            df = pd.read_csv(data_file, parse_dates=["timestamp"])
            candles = [
                OHLCV(
                    timestamp=row["timestamp"].to_pydatetime().replace(tzinfo=timezone.utc),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    symbol=symbol,
                )
                for _, row in df.iterrows()
            ]
        else:
            print(f"Fetching data for {symbol} from {start_date} to {end_date}...")
            candles = await fetch_data(symbol, start_date, end_date)

        print(f"Loaded {len(candles)} candles")

        engine = BacktestEngine(strategy_manager=strategy_manager, config=config)
        result = engine.run(candles)
        save_report(result, Path(output))

    asyncio.run(run())


if __name__ == "__main__":
    main()
