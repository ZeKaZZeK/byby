#!/usr/bin/env python3
"""Test multiple configuration variations on live data."""
import subprocess
import json
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

@dataclass
class TestConfig:
    name: str
    confidence_threshold: float
    risk_per_trade: float
    strategy_params: dict  # Strategy-specific params
    
def run_backtest(config: TestConfig, data_file: str = "data/btc_live.csv") -> dict:
    """Run backtest with custom config."""
    
    # Temporarily modify config.py
    config_file = Path("byby/config.py")
    original_content = config_file.read_text()
    
    try:
        # Update risk_per_trade
        modified = original_content.replace(
            f"max_risk_per_trade: float = ",
            f"max_risk_per_trade: float = {config.risk_per_trade}  # {config.name}"
        )
        
        # Update confidence_threshold in strategy_manager
        modified = modified.replace(
            "confidence_threshold: float = 0.65",
            f"confidence_threshold: float = {config.confidence_threshold}  # {config.name}"
        )
        
        config_file.write_text(modified)
        
        # Run backtest
        result = subprocess.run(
            [
                sys.executable, "-m", "byby.backtest.runner",
                "--data-file", data_file,
                "--capital", "10000",
                "--output", "reports"
            ],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        # Extract final metrics
        output = result.stderr + result.stdout
        last_line = [l for l in output.split('\n') if '"initial_capital"' in l]
        
        if last_line:
            metrics = json.loads(last_line[-1])
            return {
                "config": config.name,
                "confidence_threshold": config.confidence_threshold,
                "risk_per_trade": config.risk_per_trade,
                **{k: v for k, v in metrics.items() if k in [
                    "total_return_pct", "num_trades", "win_rate", 
                    "sharpe_ratio", "max_drawdown", "final_equity"
                ]}
            }
        return {"error": "Failed to parse output"}
        
    finally:
        # Restore original
        config_file.write_text(original_content)

def main():
    """Test multiple variations."""
    
    variations = [
        # Current config
        TestConfig("baseline_0.65_0.3%", confidence_threshold=0.65, risk_per_trade=0.003, strategy_params={}),
        
        # Lower confidence threshold - more trades
        TestConfig("threshold_0.50", confidence_threshold=0.50, risk_per_trade=0.003, strategy_params={}),
        TestConfig("threshold_0.55", confidence_threshold=0.55, risk_per_trade=0.003, strategy_params={}),
        TestConfig("threshold_0.60", confidence_threshold=0.60, risk_per_trade=0.003, strategy_params={}),
        
        # Different risk levels
        TestConfig("risk_0.5%", confidence_threshold=0.65, risk_per_trade=0.005, strategy_params={}),
        TestConfig("risk_1%", confidence_threshold=0.65, risk_per_trade=0.01, strategy_params={}),
        
        # Combined: lower threshold + higher risk
        TestConfig("aggressive_0.50_1%", confidence_threshold=0.50, risk_per_trade=0.01, strategy_params={}),
        TestConfig("balanced_0.55_0.5%", confidence_threshold=0.55, risk_per_trade=0.005, strategy_params={}),
    ]
    
    results = []
    print("\n" + "="*100)
    print("TESTING MULTIPLE VARIATIONS ON LIVE DATA")
    print("="*100 + "\n")
    
    for i, config in enumerate(variations, 1):
        print(f"[{i}/{len(variations)}] Testing: {config.name}")
        result = run_backtest(config)
        results.append(result)
        
        if "error" not in result:
            print(f"  Return: {result['total_return_pct']}")
            print(f"  Trades: {result['num_trades']}")
            print(f"  Win Rate: {result['win_rate']}")
            print(f"  Sharpe: {result['sharpe_ratio']}")
        else:
            print(f"  ERROR: {result['error']}")
        print()
    
    # Summary comparison
    print("\n" + "="*100)
    print("SUMMARY - RANKED BY RETURN")
    print("="*100 + "\n")
    
    valid_results = [r for r in results if "error" not in r]
    sorted_results = sorted(
        valid_results,
        key=lambda x: float(x['total_return_pct'].rstrip('%')),
        reverse=True
    )
    
    for rank, result in enumerate(sorted_results, 1):
        return_pct = result['total_return_pct']
        print(f"{rank}. {result['config']:<30} Return: {return_pct:>8} | Trades: {result['num_trades']:>3} | Win Rate: {result['win_rate']:>7} | Sharpe: {result['sharpe_ratio']:>7}")
    
    print("\n" + "="*100)

if __name__ == "__main__":
    main()
