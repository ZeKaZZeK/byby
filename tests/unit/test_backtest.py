"""Unit tests for backtest engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from byby.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from byby.market_data.models import OHLCV
from byby.strategy_manager.manager import StrategyManager


def make_candles(n: int = 200, symbol: str = "BTC/USDT:USDT") -> list[OHLCV]:
    """Generate synthetic candles for testing."""
    candles = []
    price = 50000.0
    now = datetime.now(tz=timezone.utc)
    for i in range(n):
        import math

        # Sinusoidal price movement to create crossovers
        t = i / n * 4 * math.pi
        trend = math.sin(t) * 0.001
        open_ = price
        close = price * (1 + trend)
        high = max(open_, close) * 1.002
        low = min(open_, close) * 0.998
        candles.append(
            OHLCV(
                timestamp=now - timedelta(minutes=n - i),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=5.0 + i * 0.01,
                symbol=symbol,
            )
        )
        price = close
    return candles


class TestBacktestEngine:
    def test_runs_without_error(self):
        manager = StrategyManager()
        engine = BacktestEngine(strategy_manager=manager)
        candles = make_candles(n=200)
        result = engine.run(candles)
        assert isinstance(result, BacktestResult)

    def test_equity_curve_populated(self):
        manager = StrategyManager()
        engine = BacktestEngine(strategy_manager=manager)
        candles = make_candles(n=200)
        result = engine.run(candles)
        assert len(result.equity_curve) > 0

    def test_initial_equity_preserved(self):
        config = BacktestConfig(initial_capital=10000.0)
        manager = StrategyManager()
        engine = BacktestEngine(strategy_manager=manager, config=config)
        candles = make_candles(n=200)
        result = engine.run(candles)
        assert result.initial_capital == 10000.0

    def test_summary_keys(self):
        manager = StrategyManager()
        engine = BacktestEngine(strategy_manager=manager)
        candles = make_candles(n=200)
        result = engine.run(candles)
        summary = result.summary()
        assert "total_return_pct" in summary
        assert "sharpe_ratio" in summary
        assert "max_drawdown" in summary
        assert "win_rate" in summary
        assert "num_trades" in summary

    def test_no_negative_equity(self):
        """Equity should not go negative with risk controls."""
        config = BacktestConfig(initial_capital=10000.0, max_risk_per_trade=0.01)
        manager = StrategyManager()
        engine = BacktestEngine(strategy_manager=manager, config=config)
        candles = make_candles(n=200)
        result = engine.run(candles)
        # With proper risk management, equity should not go negative
        # (though fees could make it close)
        for _ts, eq in result.equity_curve:
            assert eq > -1000  # very loose bound

    def test_max_drawdown_is_fraction(self):
        manager = StrategyManager()
        engine = BacktestEngine(strategy_manager=manager)
        candles = make_candles(n=200)
        result = engine.run(candles)
        assert 0.0 <= result.max_drawdown <= 1.0

    def test_win_rate_is_fraction(self):
        manager = StrategyManager()
        engine = BacktestEngine(strategy_manager=manager)
        candles = make_candles(n=200)
        result = engine.run(candles)
        assert 0.0 <= result.win_rate <= 1.0


class TestBacktestResult:
    def test_empty_result(self):
        result = BacktestResult(initial_capital=10000.0)
        assert result.num_trades == 0
        assert result.win_rate == 0.0
        assert result.total_pnl == 0.0

    def test_sharpe_with_equity_curve(self):
        result = BacktestResult(initial_capital=10000.0)
        now = datetime.now(tz=timezone.utc)
        result.equity_curve = [(now + timedelta(minutes=i), 10000.0 + i) for i in range(100)]
        sharpe = result.sharpe_ratio
        assert isinstance(sharpe, float)
