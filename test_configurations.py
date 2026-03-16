#!/usr/bin/env python3
"""Test multiple configuration variations on real BTC data."""

import json
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
import re

@dataclass
class BacktestResult:
    config_name: str
    final_equity: float
    total_pnl: float
    total_return_pct: str
    num_trades: int
    win_rate: str
    sharpe_ratio: float
    max_drawdown: str

def run_backtest() -> dict:
    """Run backtest and extract results from output."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "byby.backtest.runner",
            "--data-file",
            "data/btc_live.csv",
            "--capital",
            "10000",
            "--output",
            "reports",
        ],
        capture_output=True,
        text=True,
        cwd="/Users/arseniy/byby"
    )
    
    # Extract JSON lines from output
    lines = result.stdout.split('\n')
    for line in reversed(lines):
        if '"event": "backtest_complete"' in line:
            try:
                return json.loads(line)
            except:
                continue
    
    return {}

def modify_config(confidence_threshold: float = None, 
                 max_risk_per_trade: float = None,
                 shorten_periods: bool = False):
    """Temporarily modify config.py for testing."""
    config_path = Path("/Users/arseniy/byby/byby/config.py")
    content = config_path.read_text()
    
    original_content = content
    
    if confidence_threshold is not None:
        content = re.sub(
            r'confidence_threshold:\s*float\s*=\s*[\d.]+',
            f'confidence_threshold: float = {confidence_threshold}',
            content
        )
    
    if max_risk_per_trade is not None:
        content = re.sub(
            r'max_risk_per_trade:\s*float\s*=\s*[\d.]+',
            f'max_risk_per_trade: float = {max_risk_per_trade}',
            content
        )
    
    config_path.write_text(content)
    return original_content

def restore_config(original_content: str):
    """Restore original config."""
    Path("/Users/arseniy/byby/byby/config.py").write_text(original_content)

def test_configuration(name: str, confidence: float = None, risk: float = None) -> BacktestResult:
    """Test a single configuration."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"{'='*60}")
    
    original = modify_config(confidence_threshold=confidence, max_risk_per_trade=risk)
    
    try:
        result = run_backtest()
        
        backtest_result = BacktestResult(
            config_name=name,
            final_equity=result.get('final_equity', 0),
            total_pnl=result.get('total_pnl', 0),
            total_return_pct=result.get('total_return_pct', '0%'),
            num_trades=result.get('num_trades', 0),
            win_rate=result.get('win_rate', '0%'),
            sharpe_ratio=result.get('sharpe_ratio', 0),
            max_drawdown=result.get('max_drawdown', '0%'),
        )
        
        print(f"Return: {backtest_result.total_return_pct}")
        print(f"Trades: {backtest_result.num_trades} (Win rate: {backtest_result.win_rate})")
        print(f"Sharpe: {backtest_result.sharpe_ratio}")
        
        return backtest_result
        
    finally:
        restore_config(original)

def main():
    """Run all configuration tests."""
    results = []
    
    # Test 1: Baseline (current configuration)
    results.append(test_configuration(
        "Baseline (conf=0.65, risk=0.003)",
        confidence=0.65,
        risk=0.003
    ))
    
    # Test 2: Lower confidence threshold
    results.append(test_configuration(
        "Lower confidence (conf=0.60)",
        confidence=0.60,
        risk=0.003
    ))
    
    # Test 3: Even lower confidence
    results.append(test_configuration(
        "Lower confidence (conf=0.55)",
        confidence=0.55,
        risk=0.003
    ))
    
    # Test 4: Much lower confidence to trade more
    results.append(test_configuration(
        "Lower confidence (conf=0.50)",
        confidence=0.50,
        risk=0.003
    ))
    
    # Test 5: Combined - lower confidence + reduced risk
    results.append(test_configuration(
        "Lower confidence (conf=0.55) + Lower risk (0.002)",
        confidence=0.55,
        risk=0.002
    ))
    
    # Print comparison table
    print(f"\n\n{'='*100}")
    print("CONFIGURATION COMPARISON")
    print(f"{'='*100}")
    
    print(f"{'Config':<45} {'Return':<12} {'Trades':<10} {'Win Rate':<12} {'Sharpe':<10}")
    print(f"{'-'*100}")
    
    for r in results:
        print(f"{r.config_name:<45} {r.total_return_pct:<12} {str(r.num_trades):<10} {r.win_rate:<12} {r.sharpe_ratio:<10.2f}")
    
    # Find best result
    best = max(results, key=lambda x: float(x.total_return_pct.rstrip('%')))
    print(f"\n{'='*100}")
    print(f"BEST CONFIGURATION: {best.config_name}")
    print(f"Return: {best.total_return_pct} | Trades: {best.num_trades} | Win Rate: {best.win_rate}")
    print(f"{'='*100}\n")

if __name__ == "__main__":
    main()
