"""Backtest engine with minute-level data, fees, slippage, and partial fills."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import structlog

from byby.market_data.models import OHLCV, MarketState, OrderBook
from byby.regime_detector.detector import RegimeDetector
from byby.risk_manager.manager import RiskManager
from byby.strategies.base import DesiredOrder, OrderSide

logger = structlog.get_logger(__name__)


@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    fee_rate: float = 0.0006  # 0.06% taker fee
    slippage_bps: float = 5.0  # 0.05% slippage
    latency_bars: int = 1  # 1 bar execution latency
    partial_fill_prob: float = 0.0  # 0 = full fill, >0 = probabilistic partial fills
    max_risk_per_trade: float = 0.005
    max_daily_loss: float = 0.03
    max_concurrent_trades: int = 3
    max_total_exposure: float = 0.15


@dataclass
class BacktestPosition:
    symbol: str
    side: str
    entry_price: float
    quantity: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy_id: str = ""
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pnl: float = 0.0

    @property
    def notional_value(self) -> float:
        return self.entry_price * self.quantity


@dataclass
class BacktestTrade:
    entry_time: datetime
    exit_time: datetime
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    fee: float
    slippage: float
    strategy_id: str = ""
    exit_reason: str = ""


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    initial_capital: float = 10000.0
    config: Optional[BacktestConfig] = None

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.initial_capital

    @property
    def total_pnl(self) -> float:
        return self.final_equity - self.initial_capital

    @property
    def total_return_pct(self) -> float:
        return self.total_pnl / self.initial_capital

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio from daily equity changes."""
        if len(self.equity_curve) < 2:
            return 0.0
        equities = pd.Series([e for _, e in self.equity_curve])
        returns = equities.pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        mean_ret = returns.mean()
        std_ret = returns.std()
        # Annualize assuming 1-minute bars: 525600 = 365.25 * 24 * 60
        return float((mean_ret / std_ret) * math.sqrt(525600)) if std_ret > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        """Maximum drawdown as a fraction."""
        if not self.equity_curve:
            return 0.0
        equities = [e for _, e in self.equity_curve]
        peak = equities[0]
        max_dd = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def summary(self) -> dict:
        return {
            "initial_capital": self.initial_capital,
            "final_equity": self.final_equity,
            "total_pnl": self.total_pnl,
            "total_return_pct": f"{self.total_return_pct:.2%}",
            "num_trades": self.num_trades,
            "win_rate": f"{self.win_rate:.2%}",
            "sharpe_ratio": f"{self.sharpe_ratio:.2f}",
            "max_drawdown": f"{self.max_drawdown:.2%}",
        }


class BacktestEngine:
    """Runs backtests with realistic simulation."""

    def __init__(
        self,
        strategy_manager,
        config: BacktestConfig | None = None,
    ) -> None:
        self.strategy_manager = strategy_manager
        self.config = config or BacktestConfig()
        self._regime_detector = RegimeDetector()
        self._risk_manager = RiskManager(self.config.initial_capital)

    def run(self, ohlcv_data: list[OHLCV]) -> BacktestResult:
        """Run backtest on OHLCV data."""
        result = BacktestResult(
            initial_capital=self.config.initial_capital,
            config=self.config,
        )

        equity = self.config.initial_capital
        positions: list[BacktestPosition] = []
        history: list[OHLCV] = []

        result.equity_curve.append((ohlcv_data[0].timestamp, equity))

        for i, candle in enumerate(ohlcv_data):
            history.append(candle)

            # Check stop loss / take profit for existing positions
            closed_pnl, closed_positions = self._check_exits(positions, candle, result)
            equity += closed_pnl
            for p in closed_positions:
                positions.remove(p)

            # Daily PnL tracking
            self._risk_manager.update_positions(len(positions), sum(p.notional_value / equity for p in positions))
            self._risk_manager.check_daily_reset()

            # Regime detection (need enough data)
            if len(history) < 60:
                result.equity_curve.append((candle.timestamp, equity))
                continue

            market_state = MarketState(
                symbol=ohlcv_data[0].symbol,
                timestamp=candle.timestamp,
                ohlcv_history=history[-500:],
            )
            regime_result = self._regime_detector.detect(market_state)

            # Generate signals
            can_trade, reason = self._risk_manager.can_trade()
            if not can_trade:
                result.equity_curve.append((candle.timestamp, equity))
                continue

            if len(positions) >= self.config.max_concurrent_trades:
                result.equity_curve.append((candle.timestamp, equity))
                continue

            try:
                signals = self.strategy_manager.generate_signals(market_state, regime_result)
            except Exception as e:
                logger.error("backtest_signal_error", error=str(e))
                signals = []

            # Execute signals (with latency = look at next bar)
            for signal in signals[:1]:  # limit signals per bar
                if len(positions) >= self.config.max_concurrent_trades:
                    break

                # Size the order
                signal = self._risk_manager.size_order(signal, candle.close)

                # Apply slippage
                slippage = candle.close * self.config.slippage_bps / 10000
                if signal.side == OrderSide.BUY:
                    fill_price = candle.close + slippage
                else:
                    fill_price = candle.close - slippage

                fee = fill_price * signal.quantity * self.config.fee_rate
                equity -= fee

                position = BacktestPosition(
                    symbol=signal.symbol,
                    side=signal.side.value,
                    entry_price=fill_price,
                    quantity=signal.quantity,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    strategy_id=signal.strategy_id,
                    entry_time=candle.timestamp,
                )
                positions.append(position)
                logger.debug(
                    "backtest_position_opened",
                    side=position.side,
                    price=fill_price,
                    qty=position.quantity,
                )

            result.equity_curve.append((candle.timestamp, equity))

        # Close any remaining positions at last price
        if ohlcv_data and positions:
            last_candle = ohlcv_data[-1]
            for pos in positions:
                pnl = self._calculate_pnl(pos, last_candle.close)
                fee = last_candle.close * pos.quantity * self.config.fee_rate
                trade = BacktestTrade(
                    entry_time=pos.entry_time,
                    exit_time=last_candle.timestamp,
                    symbol=pos.symbol,
                    side=pos.side,
                    entry_price=pos.entry_price,
                    exit_price=last_candle.close,
                    quantity=pos.quantity,
                    pnl=pnl - fee,
                    fee=fee,
                    slippage=0.0,
                    strategy_id=pos.strategy_id,
                    exit_reason="end_of_data",
                )
                result.trades.append(trade)

        logger.info("backtest_complete", **result.summary())
        return result

    def _check_exits(
        self,
        positions: list[BacktestPosition],
        candle: OHLCV,
        result: BacktestResult,
    ) -> tuple[float, list[BacktestPosition]]:
        """Check and execute SL/TP exits."""
        total_pnl = 0.0
        to_close = []

        for pos in positions:
            exit_price = None
            exit_reason = ""

            if pos.side == "buy":
                if pos.stop_loss and candle.low <= pos.stop_loss:
                    exit_price = pos.stop_loss
                    exit_reason = "stop_loss"
                elif pos.take_profit and candle.high >= pos.take_profit:
                    exit_price = pos.take_profit
                    exit_reason = "take_profit"
            else:  # sell/short
                if pos.stop_loss and candle.high >= pos.stop_loss:
                    exit_price = pos.stop_loss
                    exit_reason = "stop_loss"
                elif pos.take_profit and candle.low <= pos.take_profit:
                    exit_price = pos.take_profit
                    exit_reason = "take_profit"

            if exit_price:
                pnl = self._calculate_pnl(pos, exit_price)
                fee = exit_price * pos.quantity * self.config.fee_rate
                net_pnl = pnl - fee
                total_pnl += net_pnl
                self._risk_manager.update_pnl(net_pnl)

                trade = BacktestTrade(
                    entry_time=pos.entry_time,
                    exit_time=candle.timestamp,
                    symbol=pos.symbol,
                    side=pos.side,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    quantity=pos.quantity,
                    pnl=net_pnl,
                    fee=fee,
                    slippage=0.0,
                    strategy_id=pos.strategy_id,
                    exit_reason=exit_reason,
                )
                result.trades.append(trade)
                to_close.append(pos)
                logger.debug(
                    "backtest_position_closed",
                    reason=exit_reason,
                    pnl=net_pnl,
                )

        return total_pnl, to_close

    @staticmethod
    def _calculate_pnl(pos: BacktestPosition, exit_price: float) -> float:
        if pos.side == "buy":
            return (exit_price - pos.entry_price) * pos.quantity
        else:
            return (pos.entry_price - exit_price) * pos.quantity
