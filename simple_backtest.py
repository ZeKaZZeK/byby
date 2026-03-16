#!/usr/bin/env python3
"""
Simple direct trading strategy - no regime detection.
Just pure technical analysis: Donchian breakouts + RSI mean reversion.
"""
import sys
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import timezone
from dataclasses import dataclass
import logging

# Setup
sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Trade:
    entry_price: float
    entry_time: int
    side: str  # 'buy' or 'sell'
    quantity: float
    exit_price: float = None
    exit_time: int = None
    pnl: float = 0.0
    
    def close(self, price: float, time: int):
        self.exit_price = price
        self.exit_time = time
        if self.side == 'buy':
            self.pnl = (price - self.entry_price) * self.quantity
        else:
            self.pnl = (self.entry_price - price) * self.quantity

class SimpleTrader:
    """Pure technical analysis trader without regime complexity."""
    
    def __init__(self, initial_capital=10000, risk_per_trade=0.02):
        self.capital = initial_capital
        self.equity = initial_capital
        self.risk_per_trade = risk_per_trade
        self.trades = []
        self.daily_pnl = 0.0
        self.current_date = None
        self.open_position = None
        
        # Strategy params
        self.donchian_period = 20
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        
    def calculate_rsi(self, closes, period=14):
        """Calculate RSI."""
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def generate_signals(self, df):
        """Generate buy/sell signals."""
        # Donchian breakouts
        high_20 = df['high'].rolling(window=self.donchian_period).max()
        low_20 = df['low'].rolling(window=self.donchian_period).min()
        
        # RSI
        rsi = self.calculate_rsi(df['close'], self.rsi_period)
        
        # Find signals
        buy_signals = []
        sell_signals = []
        
        for i in range(self.donchian_period, len(df)):
            price = df['close'].iloc[i]
            high_20_val = high_20.iloc[i]
            low_20_val = low_20.iloc[i]
            rsi_val = rsi.iloc[i]
            
            # Signal 1: Breakout above 20-period high
            if price > high_20_val and not pd.isna(high_20_val):
                buy_signals.append((i, price, 'breakout_buy'))
            
            # Signal 2: RSI oversold with price at lower band
            if rsi_val < self.rsi_oversold and price < low_20_val and not pd.isna(rsi_val):
                buy_signals.append((i, price, 'mean_rev_buy'))
            
            # Sell when reversing or hitting moving average
            if price < low_20_val and not pd.isna(low_20_val):
                sell_signals.append((i, price, 'breakout_sell'))
                
            if rsi_val > self.rsi_overbought and not pd.isna(rsi_val):
                sell_signals.append((i, price, 'mean_rev_sell'))
        
        return buy_signals, sell_signals, high_20, low_20, rsi
    
    def backtest(self, df):
        """Run simple backtest."""
        df = df.copy()
        df['date'] = pd.to_datetime(df['timestamp']).dt.date
        
        buy_signals, sell_signals, high20, low20, rsi = self.generate_signals(df)
        
        buy_set = set(i for i, _, _ in buy_signals)
        sell_set = set(i for i, _, _ in sell_signals)
        
        equity_curve = [self.equity]
        pnl_list = []
        trade_count = 0
        win_count = 0
        
        for i in range(len(df)):
            current_date = df['date'].iloc[i]
            if current_date != self.current_date:
                self.current_date = current_date
                self.daily_pnl = 0.0
            
            price = df['close'].iloc[i]
            
            # Close position if sell signal
            if self.open_position and i in sell_set:
                self.open_position.close(price, i)
                self.equity += self.open_position.pnl
                self.daily_pnl += self.open_position.pnl
                
                if self.open_position.pnl > 0:
                    win_count += 1
                
                logger.info(json.dumps({
                    "event": "trade_close",
                    "side": self.open_position.side,
                    "entry": self.open_position.entry_price,
                    "exit": price,
                    "quantity": self.open_position.quantity,
                    "pnl": self.open_position.pnl,
                    "equity": self.equity
                }))
                
                self.trades.append(self.open_position)
                self.open_position = None
                trade_count += 1
            
            # Open new position if buy signal and no position
            if not self.open_position and i in buy_set:
                # Simple position sizing: risk_per_trade of equity
                risk_amount = self.equity * self.risk_per_trade
                
                # Use ATR for stop loss (simplified: 2% of price)
                stop_loss_pct = 0.02
                stop_loss_price = price * (1 - stop_loss_pct)
                
                risk_distance = price - stop_loss_price
                quantity = risk_amount / risk_distance if risk_distance > 0 else 0
                
                if quantity > 0:
                    self.open_position = Trade(
                        entry_price=price,
                        entry_time=i,
                        side='buy',
                        quantity=quantity
                    )
                    
                    logger.info(json.dumps({
                        "event": "trade_open",
                        "price": price,
                        "quantity": quantity,
                        "risk_amount": risk_amount,
                        "stop_loss": stop_loss_price,
                        "equity": self.equity
                    }))
            
            # Check stop loss
            if self.open_position:
                stop_loss = self.open_position.entry_price * (1 - 0.02)
                if price < stop_loss:
                    self.open_position.close(price, i)
                    self.equity += self.open_position.pnl
                    self.daily_pnl += self.open_position.pnl
                    
                    logger.info(json.dumps({
                        "event": "stop_loss_hit",
                        "price": price,
                        "pnl": self.open_position.pnl
                    }))
                    
                    self.trades.append(self.open_position)
                    self.open_position = None
                    trade_count += 1
            
            equity_curve.append(self.equity)
            pnl_list.append(self.equity - self.capital)
        
        # Close any remaining position
        if self.open_position:
            last_price = df['close'].iloc[-1]
            self.open_position.close(last_price, len(df)-1)
            self.equity += self.open_position.pnl
            self.trades.append(self.open_position)
            trade_count += 1
        
        # Calculate metrics
        total_return_pct = ((self.equity - self.capital) / self.capital) * 100
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0
        
        max_drawdown = 0
        peak = self.capital
        for e in equity_curve:
            if e > peak:
                peak = e
            dd = (peak - e) / peak
            if dd > max_drawdown:
                max_drawdown = dd
        
        # Sharpe ratio (simplified)
        returns = np.diff(equity_curve) / self.capital
        excess_return = returns.mean()
        std_return = returns.std()
        sharpe = (excess_return / std_return * np.sqrt(252)) if std_return > 0 else 0
        
        return {
            "initial_capital": self.capital,
            "final_equity": round(self.equity, 2),
            "total_pnl": round(self.equity - self.capital, 2),
            "total_return_pct": f"{total_return_pct:.2f}%",
            "num_trades": trade_count,
            "win_rate": f"{win_rate:.2f}%",
            "sharpe_ratio": f"{sharpe:.2f}",
            "max_drawdown": f"{max_drawdown*100:.2f}%"
        }

def main():
    # Load data
    data_file = Path("data/btc_live.csv")
    if not data_file.exists():
        print(f"Error: {data_file} not found")
        return
    
    df = pd.read_csv(data_file, parse_dates=['timestamp'])
    
    # Run backtest
    trader = SimpleTrader(initial_capital=10000, risk_per_trade=0.02)
    results = trader.backtest(df)
    
    # Print results
    print("\n" + "="*60)
    print("SIMPLE TRADER BACKTEST RESULTS")
    print("="*60)
    for k, v in results.items():
        print(f"  {k:<30}: {v}")
    print("="*60)

if __name__ == "__main__":
    main()
