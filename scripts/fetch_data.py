#!/usr/bin/env python3
"""Script to fetch historical OHLCV data and save to CSV."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import click
import pandas as pd

from byby.config import get_settings
from byby.logging_config import configure_logging
from byby.market_data.rest_client import BybitRESTClient


@click.command()
@click.option("--symbol", default="BTC/USDT:USDT")
@click.option("--start", default="2023-01-01")
@click.option("--end", default="2025-01-01")
@click.option("--output", default="data/btc_usdt_1m.csv")
@click.option("--timeframe", default="1m")
def main(symbol, start, end, output, timeframe):
    """Fetch historical data from Bybit."""
    configure_logging()
    settings = get_settings()

    async def fetch():
        client = BybitRESTClient(settings=settings)
        await client.connect()
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        all_candles = []
        current = start_dt
        try:
            while current < end_dt:
                candles = await client.fetch_ohlcv(symbol, timeframe, since=current, limit=1000)
                if not candles:
                    break
                all_candles.extend(candles)
                current = candles[-1].timestamp
                if len(candles) < 1000:
                    break
                print(f"Fetched {len(all_candles)} candles up to {current}")
        finally:
            await client.close()
        return all_candles

    candles = asyncio.run(fetch())
    print(f"Total: {len(candles)} candles")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([{
        "timestamp": c.timestamp.isoformat(),
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume,
    } for c in candles])
    df.to_csv(output, index=False)
    print(f"Saved to {output}")


if __name__ == "__main__":
    main()
