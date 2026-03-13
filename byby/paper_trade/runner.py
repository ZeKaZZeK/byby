"""Paper trading runner."""
from __future__ import annotations

import asyncio
import signal
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from byby.config import get_settings
from byby.logging_config import configure_logging
from byby.market_data.data_manager import MarketDataManager
from byby.monitoring.alerts import TelegramAlerter
from byby.monitoring.metrics import (
    record_order_submitted,
    start_metrics_server,
    update_pnl_metrics,
    update_position_metrics,
    update_regime_metrics,
)
from byby.regime_detector.detector import RegimeDetector
from byby.risk_manager.manager import RiskManager
from byby.strategies.base import DesiredOrder
from byby.strategy_manager.manager import StrategyManager

logger = structlog.get_logger(__name__)


class PaperTradingRunner:
    """Full paper trading pipeline."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self._data_manager: Optional[MarketDataManager] = None
        self._regime_detector = RegimeDetector(settings=self.settings)
        self._strategy_manager = StrategyManager(settings=self.settings)
        self._risk_manager = RiskManager(
            initial_equity=self.settings.paper_initial_balance,
            settings=self.settings,
        )
        self._alerter = TelegramAlerter(settings=self.settings)
        self._running = False
        self._instance_id = str(uuid.uuid4())[:8]
        self._paper_orders: list[dict] = []
        self._paper_positions: list[dict] = []

    async def start(self) -> None:
        """Start the paper trading runner."""
        configure_logging()
        logger.info("paper_trade_starting", instance=self._instance_id)

        # Start metrics server
        try:
            start_metrics_server(self.settings.prometheus_port)
            logger.info("metrics_server_started", port=self.settings.prometheus_port)
        except Exception as e:
            logger.warning("metrics_server_failed", error=str(e))

        # Send deploy alert
        async with self._alerter as alerter:
            await alerter.alert_deploy("0.1.0", "paper-trading")

        self._data_manager = MarketDataManager(
            symbol=self.settings.trading_symbol,
            timeframe=self.settings.trading_timeframe,
            testnet=self.settings.bybit_testnet,
            settings=self.settings,
        )

        self._running = True

        try:
            await self._data_manager.start()
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("paper_trade_cancelled")
        except Exception as e:
            logger.error("paper_trade_error", error=str(e))
            async with self._alerter as alerter:
                await alerter.alert_exception("PaperTradingRunner", str(e))
        finally:
            await self._data_manager.stop()
            logger.info("paper_trade_stopped")

    async def _main_loop(self) -> None:
        """Main trading loop - runs every bar."""
        loop_interval = 60  # seconds

        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error("tick_error", error=str(e))
                async with self._alerter as alerter:
                    await alerter.alert_exception("main_loop", str(e))
            await asyncio.sleep(loop_interval)

    async def _tick(self) -> None:
        """Process one tick of the main loop."""
        market_state = await self._data_manager.get_market_state()

        if not market_state.ohlcv_history:
            logger.debug("no_data_yet")
            return

        # Detect regime
        regime_result = self._regime_detector.detect(market_state)
        update_regime_metrics(regime_result.regime.value, regime_result.confidence)
        logger.info(
            "regime_detected",
            regime=regime_result.regime.value,
            confidence=regime_result.confidence,
        )

        # Update position metrics
        update_position_metrics(
            len(self._paper_positions),
            self._get_total_exposure(market_state.last_price or 0),
        )

        # Check if trading allowed
        can_trade, reason = self._risk_manager.can_trade()
        if not can_trade:
            logger.info("trading_blocked", reason=reason)
            if reason == "daily_loss_limit_hit":
                async with self._alerter as alerter:
                    await alerter.alert_daily_loss_hit(
                        self._risk_manager.state.daily_pnl,
                        self.settings.max_daily_loss,
                    )
            return

        # Generate signals
        signals = self._strategy_manager.generate_signals(market_state, regime_result)

        # Execute signals (paper mode)
        for signal in signals:
            if not self._can_add_position():
                break
            await self._execute_paper_order(signal, market_state.last_price or 0)

        # Check SL/TP for open paper positions
        await self._check_paper_exits(market_state)

        # Update PnL metrics
        update_pnl_metrics(
            self._risk_manager.state.daily_pnl,
            self._risk_manager.state.equity,
        )

    async def _execute_paper_order(self, signal: DesiredOrder, current_price: float) -> None:
        """Simulate order execution in paper mode."""
        sized_signal = self._risk_manager.size_order(signal, current_price)
        fill_price = current_price  # assume market fill at current price

        position = {
            "id": str(uuid.uuid4())[:8],
            "symbol": sized_signal.symbol,
            "side": sized_signal.side.value,
            "quantity": sized_signal.quantity,
            "entry_price": fill_price,
            "stop_loss": sized_signal.stop_loss,
            "take_profit": sized_signal.take_profit,
            "strategy_id": sized_signal.strategy_id,
            "entry_time": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._paper_positions.append(position)
        self._paper_orders.append({
            **position,
            "status": "filled",
            "fill_price": fill_price,
        })

        record_order_submitted(sized_signal.symbol, sized_signal.side.value, sized_signal.strategy_id)

        logger.info(
            "paper_order_filled",
            **{k: v for k, v in position.items() if k != "entry_time"},
            price=fill_price,
        )

        async with self._alerter as alerter:
            await alerter.alert_order_filled(
                sized_signal.symbol,
                sized_signal.side.value,
                sized_signal.quantity,
                fill_price,
            )

    async def _check_paper_exits(self, market_state) -> None:
        """Check stop loss / take profit for paper positions."""
        if not market_state.last_price:
            return
        current_price = market_state.last_price
        to_close = []

        for pos in self._paper_positions:
            exit_price = None
            exit_reason = ""

            if pos["side"] == "buy":
                if pos.get("stop_loss") and current_price <= pos["stop_loss"]:
                    exit_price = pos["stop_loss"]
                    exit_reason = "stop_loss"
                elif pos.get("take_profit") and current_price >= pos["take_profit"]:
                    exit_price = pos["take_profit"]
                    exit_reason = "take_profit"
            else:
                if pos.get("stop_loss") and current_price >= pos["stop_loss"]:
                    exit_price = pos["stop_loss"]
                    exit_reason = "stop_loss"
                elif pos.get("take_profit") and current_price <= pos["take_profit"]:
                    exit_price = pos["take_profit"]
                    exit_reason = "take_profit"

            if exit_price:
                if pos["side"] == "buy":
                    pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
                else:
                    pnl = (pos["entry_price"] - exit_price) * pos["quantity"]

                self._risk_manager.update_pnl(pnl)
                to_close.append(pos)
                logger.info(
                    "paper_position_closed",
                    pos_id=pos["id"],
                    exit_reason=exit_reason,
                    pnl=pnl,
                )
                async with self._alerter as alerter:
                    await alerter.alert_order_filled(
                        pos["symbol"], pos["side"], pos["quantity"], exit_price, pnl
                    )

        for pos in to_close:
            self._paper_positions.remove(pos)

    def _can_add_position(self) -> bool:
        return len(self._paper_positions) < self.settings.max_concurrent_trades

    def _get_total_exposure(self, current_price: float) -> float:
        if not self._paper_positions or not current_price:
            return 0.0
        total_notional = sum(p["quantity"] * current_price for p in self._paper_positions)
        equity = self._risk_manager.state.equity
        return total_notional / equity if equity > 0 else 0.0

    def stop(self) -> None:
        self._running = False


async def run_paper_trading():
    """Entry point for paper trading."""
    runner = PaperTradingRunner()

    loop = asyncio.get_event_loop()

    def handle_signal(sig):
        logger.info("shutdown_signal_received", signal=sig.name)
        runner.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    await runner.start()


def main():
    asyncio.run(run_paper_trading())


if __name__ == "__main__":
    main()
