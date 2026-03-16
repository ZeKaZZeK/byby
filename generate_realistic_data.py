#!/usr/bin/env python3
"""Generate realistic synthetic BTC data with trends."""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

start = datetime(2025, 9, 1, tzinfo=timezone.utc)
n_candles = 20000

times = [start + timedelta(minutes=i) for i in range(n_candles)]

np.random.seed(42)
price = 43000
ohlcv_data = []

for i, t in enumerate(times):
    # Phase 1: uptrend, Phase 2: downtrend, Phase 3: sideways
    if i < 6000:
        trend = 0.02  # +2% per day
    elif i < 12000:
        trend = -0.015  # -1.5% per day
    else:
        trend = 0.0  # flat
    
    daily_trend = trend / (24 * 60)
    volatility = np.random.normal(0, 0.005)  # 0.5% volatility
    
    change = price * (daily_trend + volatility)
    o = price
    c = price + change
    h = max(o, c) + abs(np.random.normal(0, price * 0.003))
    l = min(o, c) - abs(np.random.normal(0, price * 0.003))
    v = np.random.uniform(50, 300)
    
    ohlcv_data.append({
        'timestamp': t,
        'open': o,
        'high': h,
        'low': l,
        'close': c,
        'volume': v,
    })
    
    price = c

df = pd.DataFrame(ohlcv_data)
df.to_csv('data/btc_realistic.csv', index=False)
print(f"✓ Created {len(df)} realistic candles")
print(f"  Price range: {df['close'].min():.2f} - {df['close'].max():.2f}")
print(f"  Period: {df['timestamp'].min()} to {df['timestamp'].max()}")
