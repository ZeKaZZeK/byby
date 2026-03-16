#!/usr/bin/env python3
"""Analyze what signals are generated during backtest."""
import sys
import pandas as pd
import json
from pathlib import Path
from datetime import timezone
sys.path.insert(0, str(Path(__file__).parent))

from byby.config import get_settings
from byby.market_data.models import OHLCV
from byby.regime_detector.detector import RegimeDetector
from byby.strategy_manager.manager import StrategyManager

# Load data
data_file = Path("data/btc_live.csv")
df = pd.read_csv(data_file, parse_dates=['timestamp'])

# Setup
settings = get_settings()
regime_detector = RegimeDetector(settings=settings)
strategy_manager = StrategyManager(settings=settings)

# Sample candles to analyze
sample_indices = [10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000]
buys = 0
sells = 0

print("\n" + "="*80)
print("SIGNAL ANALYSIS - Sampling throughout backtest")
print("="*80)

for i in sample_indices:
    if i >= len(df):
        continue
    
    # Build order book history
    ohlcv_history = []
    for j in range(max(0, i-200), i+1):
        row = df.iloc[j]
        ohlcv_history.append(OHLCV(
            timestamp=row['timestamp'].to_pydatetime().replace(tzinfo=timezone.utc),
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row['volume'])
        ))
    
    # Create market state
    from byby.market_data.models import MarketState
    market_state = MarketState(
        symbol="BTC/USDT:USDT",
        timestamp=ohlcv_history[-1].timestamp,
        ohlcv_history=ohlcv_history
    )
    
    # Get regime
    regime_result = regime_detector.detect(market_state)
    
    # Generate signals
    signals = strategy_manager.generate_signals(market_state, regime_result)
    
    # Count by side
    buy_count = sum(1 for s in signals if hasattr(s, 'side') and str(s.side).endswith('BUY'))
    sell_count = sum(1 for s in signals if hasattr(s, 'side') and str(s.side).endswith('SELL'))
    buys += buy_count
    sells += sell_count
    
    # Log
    date_str = ohlcv_history[-1].timestamp.strftime('%Y-%m-%d %H:%M')
    price = ohlcv_history[-1].close
    
    if buy_count > 0 or sell_count > 0:
        print(f"\n[{i:>6}] {date_str} | Price: ${price:>10.2f}")
        print(f"  Regime: {regime_result.regime.name:<12} (conf: {regime_result.confidence:.3f})")
        if buy_count > 0:
            print(f"  BUY signals:  {buy_count}")
        if sell_count > 0:
            print(f"  SELL signals: {sell_count}")
        
        # Show each signal
        for sig in signals:
            if hasattr(sig, 'side'):
                side = str(sig.side)
                print(f"    - {side:<6} {sig.strategy_id if hasattr(sig, 'strategy_id') else 'N/A'}")
    else:
        print(f"[{i:>6}] {date_str} | Price: ${price:>10.2f} | Regime: {regime_result.regime.name:<12} | No signals")

print("\n" + "="*80)
print(f"SUMMARY: {buys} BUY signals, {sells} SELL signals across {len(sample_indices)} samples")
print("="*80 + "\n")
