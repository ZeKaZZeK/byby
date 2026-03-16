#!/usr/bin/env python3
"""Fetch historical OHLCV data from Bybit LIVE (no auth required for public data)."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import click
import pandas as pd
import ccxt.async_support as ccxt_async


@click.command()
@click.option("--symbol", default="BTC/USDT:USDT")
@click.option("--start", default="2026-01-13")
@click.option("--end", default="2026-03-13")
@click.option("--output", default="data/btc_live.csv")
@click.option("--timeframe", default="1m")
def main(symbol, start, end, output, timeframe):
    """Fetch historical data from Bybit LIVE (public data - no auth needed)."""
    
    async def fetch():
        # Use LIVE Bybit (not testnet) for real market data
        exchange = ccxt_async.bybit({
            'enableRateLimit': True,
        })
        
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        
        all_candles = []
        current_ms = start_ms
        
        try:
            while current_ms < end_ms:
                try:
                    candles = await exchange.fetch_ohlcv(symbol, timeframe, since=current_ms, limit=1000)
                    if not candles or len(candles) == 0:
                        print(f"No more data available")
                        break
                    
                    all_candles.extend(candles)
                    current_ms = int(candles[-1][0]) + 60000  # Move to next minute
                    
                    if len(candles) < 1000:
                        print(f"Fetched less than 1000 candles, stopping")
                        break
                    
                    print(f"Fetched {len(all_candles)} candles up to {datetime.fromtimestamp(current_ms/1000, tz=timezone.utc)}")
                    
                except Exception as e:
                    print(f"Error fetching data: {e}")
                    await asyncio.sleep(5)
                    continue
        finally:
            await exchange.close()
        
        return all_candles

    candles = asyncio.run(fetch())
    print(f"Total: {len(candles)} candles")

    if len(candles) == 0:
        print("No candles fetched!")
        return

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    df.to_csv(output, index=False)
    print(f"Saved {len(df)} candles to {output}")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")


if __name__ == "__main__":
    main()
