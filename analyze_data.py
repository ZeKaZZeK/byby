#!/usr/bin/env python3
"""Analyze data to understand market periods."""
import pandas as pd
from pathlib import Path

data_file = Path("data/btc_live.csv")
df = pd.read_csv(data_file, parse_dates=['timestamp'])

print("Data overview:")
print(f"Total candles: {len(df)}")
print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
print(f"Price range: ${df['low'].min():.2f} to ${df['high'].max():.2f}")
print(f"Starting price: ${df['close'].iloc[0]:.2f}")
print(f"Ending price: ${df['close'].iloc[-1]:.2f}")
print(f"Total move: {((df['close'].iloc[-1] / df['close'].iloc[0]) - 1) * 100:.2f}%")

# Split into periods
df['date'] = df['timestamp'].dt.date
dates = df.groupby('date').agg({
    'close': ['first', 'last'],
    'high': 'max',
    'low': 'min',
    'volume': 'sum'
})

dates.columns = ['open', 'close', 'high', 'low', 'volume']
dates['daily_return'] = ((dates['close'] - dates['open']) / dates['open'] * 100).round(2)

print("\nDaily returns:")
print(dates['daily_return'].describe())

print("\nFirst 10 days:")
print(dates.head(10))

print("\nLast 10 days:")
print(dates.tail(10))

# Find turning points
mid_idx = len(df) // 2
print(f"\nMid-period price: ${df['close'].iloc[mid_idx]:.2f} at {df['timestamp'].iloc[mid_idx]}")

# Find local peaks
for i in range(1000, len(df)-1000, 5000):
    print(f"At {i} ({df['timestamp'].iloc[i]}): ${df['close'].iloc[i]:.2f}")
