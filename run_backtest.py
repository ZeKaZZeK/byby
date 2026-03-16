#!/usr/bin/env python3
"""Quick backtest runner with configuration."""
import sys
import json
from pathlib import Path
from datetime import timezone
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from byby.config import get_settings
from byby.market_data.models import OHLCV
from byby.backtest.engine import BacktestEngine, BacktestConfig
from byby.strategy_manager.manager import StrategyManager

def quick_backtest(data_file: str = "data/btc_live.csv", capital: float = 10000):
    """Run quick backtest and display results."""
    
    # Load data
    df = pd.read_csv(data_file, parse_dates=['timestamp'])
    
    # Convert to OHLCV
    ohlcv_data = []
    for _, row in df.iterrows():
        ohlcv_data.append(OHLCV(
            timestamp=row['timestamp'].to_pydatetime().replace(tzinfo=timezone.utc),
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row['volume'])
        ))
    
    # Setup config
    settings = get_settings()
    config = BacktestConfig(
        initial_capital=capital,
        fee_rate=0.0006,
        slippage_bps=5.0,
        max_risk_per_trade=settings.max_risk_per_trade,
        max_daily_loss=settings.max_daily_loss,
        max_concurrent_trades=settings.max_concurrent_trades,
    )
    
    strategy_manager = StrategyManager(settings=settings)
    
    # Run backtest
    engine = BacktestEngine(
        strategy_manager=strategy_manager,
        config=config
    )
    
    result = engine.run(ohlcv_data)
    
    # Print summary
    print("\n" + "="*70)
    print("BACKTEST SUMMARY")
    print("="*70)
    print(f"  Data:              {data_file} ({len(ohlcv_data)} candles)")
    print(f"  Period:            {ohlcv_data[0].timestamp} to {ohlcv_data[-1].timestamp}")
    print(f"  Initial Capital:   ${capital:,.2f}")
    print(f"  Final Equity:      ${result.final_equity:,.2f}")
    print(f"  Total PnL:         ${result.total_pnl:,.2f}")
    print(f"  Return %:          {result.total_return_pct*100:,.2f}%")
    print(f"  Number of Trades:  {result.num_trades}")
    print(f"  Win Rate:          {result.win_rate*100:.2f}%")
    print(f"  Max Drawdown:      {result.max_drawdown*100:.2f}%")
    print(f"  Sharpe Ratio:      {result.sharpe_ratio:.2f}")
    print("="*70 + "\n")
    
    # Save reports
    report_dir = Path("reports")
    report_dir.mkdir(exist_ok=True)
    
    # Save equity curve
    equity_df = pd.DataFrame(result.equity_curve, columns=['timestamp', 'equity'])
    equity_df.to_csv(report_dir / 'equity_curve.csv', index=False)
    
    # Save trades
    if result.trades:
        trades_data = []
        for t in result.trades:
            trades_data.append({
                'entry_time': t.entry_time,
                'exit_time': t.exit_time,
                'symbol': t.symbol,
                'side': t.side,
                'entry_price': t.entry_price,
                'exit_price': t.exit_price,
                'quantity': t.quantity,
                'pnl': t.pnl,
                'fee': t.fee,
                'slippage': t.slippage,
            })
        trades_df = pd.DataFrame(trades_data)
        trades_df.to_csv(report_dir / 'trades.csv', index=False)
    
    # Save JSON summary
    summary = {
        'initial_capital': capital,
        'final_equity': result.final_equity,
        'total_pnl': result.total_pnl,
        'total_return_pct': result.total_return_pct,
        'num_trades': result.num_trades,
        'win_rate': result.win_rate,
        'sharpe_ratio': result.sharpe_ratio,
        'max_drawdown': result.max_drawdown,
    }
    
    with open(report_dir / 'backtest_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"Reports saved to {report_dir}/")

if __name__ == "__main__":
    data_file = sys.argv[1] if len(sys.argv) > 1 else "data/btc_live.csv"
    capital = float(sys.argv[2]) if len(sys.argv) > 2 else 10000.0
    quick_backtest(data_file, capital)
