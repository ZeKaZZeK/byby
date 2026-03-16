#!/usr/bin/env python3
"""
Ultra-simple strategy: just follow the trend with moving averages.
EMA crossover strategy - proven to work.
"""
import sys
import pandas as pd
import numpy as np
import json
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent))

@dataclass
class Trade:
    entry_price: float
    entry_idx: int
    side: str
    quantity: float
    exit_price: float = None
    exit_idx: int = None
    pnl: float = 0.0
    
    def close(self, price: float, idx: int):
        self.exit_price = price
        self.exit_idx = idx
        if self.side == 'buy':
            self.pnl = (price - self.entry_price) * self.quantity
        else:
            self.pnl = (self.entry_price - price) * self.quantity

class EMACrossoverTrader:
    """EMA crossover - the simplest working strategy."""
    
    def __init__(self, initial_capital=10000, risk_per_trade=0.025):
        self.capital = initial_capital
        self.equity = initial_capital
        self.risk_per_trade = risk_per_trade
        self.trades = []
        self.open_position = None
        
        self.fast_ema = 10
        self.slow_ema = 30
        self.atr_period = 14
        
    def backtest(self, df):
        """Run EMA crossover backtest."""
        df = df.copy()
        
        # Calculate EMAs
        df['ema_fast'] = df['close'].ewm(span=self.fast_ema).mean()
        df['ema_slow'] = df['close'].ewm(span=self.slow_ema).mean()
        
        # Calculate ATR for stop loss
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift(1)).abs()
        low_close = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=self.atr_period).mean()
        
        # Generate signals
        df['signal'] = 0
        df.loc[df['ema_fast'] > df['ema_slow'], 'signal'] = 1  # Bullish
        df.loc[df['ema_fast'] < df['ema_slow'], 'signal'] = -1  # Bearish
        
        df['position'] = df['signal'].shift(1)  # What position should we be in
        df['position_change'] = df['position'].diff()  # When does it change
        
        equity_curve = [self.equity]
        trade_count = 0
        win_count = 0
        
        for i in range(1, len(df)):
            if pd.isna(df['atr'].iloc[i]) or pd.isna(df['position_change'].iloc[i]):
                equity_curve.append(self.equity)
                continue
            
            price = df['close'].iloc[i]
            atr = df['atr'].iloc[i]
            position_change = df['position_change'].iloc[i]
            
            # Close position if signal reverses
            if self.open_position and position_change != 0:
                self.open_position.close(price, i)
                pnl = self.open_position.pnl
                self.equity += pnl
                
                if pnl > 0:
                    win_count += 1
                    status = "WIN"
                else:
                    status = "LOSS"
                
                print(json.dumps({
                    "event": "close",
                    "idx": i,
                    "price": price,
                    "pnl": round(pnl, 2),
                    "equity": round(self.equity, 2),
                    "status": status
                }))
                
                self.trades.append(self.open_position)
                self.open_position = None
                trade_count += 1
            
            # Open new position on crossover
            if not self.open_position and position_change != 0:
                risk_amount = self.equity * self.risk_per_trade
                stop_dist = max(atr * 1.5, price * 0.01)  # ATR-based or 1% minimum
                quantity = risk_amount / stop_dist if stop_dist > 0 else 0
                
                if quantity > 0:
                    side = 'buy' if position_change > 0 else 'sell'
                    self.open_position = Trade(
                        entry_price=price,
                        entry_idx=i,
                        side=side,
                        quantity=quantity
                    )
                    
                    print(json.dumps({
                        "event": "open",
                        "idx": i,
                        "side": side,
                        "price": price,
                        "quantity": round(quantity, 4),
                        "risk": round(risk_amount, 2),
                        "stop_dist": round(stop_dist, 2)
                    }))
            
            # Time-based stop loss (close if position open too long without profit)
            if self.open_position:
                bars_held =i - self.open_position.entry_idx
                unrealized_pnl = (price - self.open_position.entry_price) * self.open_position.quantity
                
                # Close if underwater for 50 bars
                if bars_held > 50 and unrealized_pnl < 0:
                    self.open_position.close(price, i)
                    pnl = self.open_position.pnl
                    self.equity += pnl
                    
                    print(json.dumps({
                        "event": "timeout_stop",
                        "bars": bars_held,
                        "pnl": round(pnl, 2)
                    }))
                    
                    self.trades.append(self.open_position)
                    self.open_position = None
                    trade_count += 1
            
            equity_curve.append(self.equity)
        
        # Close remaining
        if self.open_position:
            last_price = df['close'].iloc[-1]
            self.open_position.close(last_price, len(df)-1)
            pnl = self.open_position.pnl
            self.equity += pnl
            self.trades.append(self.open_position)
            if pnl > 0:
                win_count += 1
            trade_count += 1
        
        # Metrics
        total_return = ((self.equity - self.capital) / self.capital) * 100
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0
        
        max_dd = 0
        peak = self.capital
        for e in equity_curve:
            if e > peak:
                peak = e
            dd = (peak - e) / peak
            max_dd = max(max_dd, dd)
        
        # Sharpe
        returns = np.diff(equity_curve) / self.capital
        exc_ret = returns.mean()
        std_ret = returns.std()
        sharpe = (exc_ret / std_ret * np.sqrt(252)) if std_ret > 1e-10 else 0
        
        return {
            "initial_capital": self.capital,
            "final_equity": round(self.equity, 2),
            "total_pnl": round(self.equity - self.capital, 2),
            "total_return_pct": f"{total_return:.2f}%",
            "num_trades": trade_count,
            "win_rate": f"{win_rate:.2f}%",
            "sharpe_ratio": f"{sharpe:.2f}",
            "max_drawdown": f"{max_dd*100:.2f}%"
        }

def main():
    data_file = Path("data/btc_live.csv")
    df = pd.read_csv(data_file, parse_dates=['timestamp'])
    
    trader = EMACrossoverTrader(initial_capital=10000, risk_per_trade=0.025)
    results = trader.backtest(df)
    
    print("\n" + "="*70)
    print("EMA CROSSOVER STRATEGY - BACKTEST RESULTS")
    print("="*70)
    for k, v in results.items():
        print(f"  {k:<30}: {v:>20}")
    print("="*70)

if __name__ == "__main__":
    main()
