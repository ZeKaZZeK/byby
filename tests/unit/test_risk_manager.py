"""Unit tests for risk manager."""

from __future__ import annotations

import pytest

from byby.risk_manager.manager import RiskManager
from byby.strategies.base import DesiredOrder, OrderSide, OrderType


def make_order(
    symbol: str = "BTC/USDT:USDT",
    side: OrderSide = OrderSide.BUY,
    stop_loss: float | None = 49000.0,
) -> DesiredOrder:
    return DesiredOrder(
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=0.0,
        stop_loss=stop_loss,
        strategy_id="test",
        client_order_id="test_123",
    )


class TestRiskManager:
    def test_can_trade_initially(self):
        rm = RiskManager(initial_equity=10000.0)
        can_trade, reason = rm.can_trade()
        assert can_trade is True
        assert reason == "ok"

    def test_blocks_on_daily_loss(self):
        rm = RiskManager(initial_equity=10000.0)
        # Simulate large loss
        rm.update_pnl(-500.0)  # 5% loss > 3% limit
        can_trade, reason = rm.can_trade()
        assert can_trade is False
        assert reason == "daily_loss_limit_hit"

    def test_blocks_on_max_positions(self):
        rm = RiskManager(initial_equity=10000.0)
        rm.update_positions(3, 0.1)  # max is 3
        can_trade, reason = rm.can_trade()
        assert can_trade is False
        assert reason == "max_concurrent_trades_reached"

    def test_blocks_on_max_exposure(self):
        rm = RiskManager(initial_equity=10000.0)
        rm.update_positions(0, 0.20)  # 20% > 15% max
        can_trade, reason = rm.can_trade()
        assert can_trade is False
        assert reason == "max_exposure_reached"

    def test_size_order_with_stop_loss(self):
        rm = RiskManager(initial_equity=10000.0)
        order = make_order(stop_loss=49000.0)
        current_price = 50000.0
        sized = rm.size_order(order, current_price)
        # Risk = 0.5% of 10000 = 50
        # Stop distance = 50000 - 49000 = 1000
        # Qty = 50 / 1000 = 0.05
        assert sized.quantity == pytest.approx(0.05, rel=0.01)

    def test_size_order_without_stop_loss(self):
        rm = RiskManager(initial_equity=10000.0)
        order = make_order(stop_loss=None)
        sized = rm.size_order(order, 50000.0, atr=500.0)
        # Risk = 50, stop = 500 * 2 = 1000, qty = 0.05
        assert sized.quantity > 0

    def test_update_pnl_updates_equity(self):
        rm = RiskManager(initial_equity=10000.0)
        rm.update_pnl(100.0)
        assert rm.state.equity == pytest.approx(10100.0)
        assert rm.state.daily_pnl == pytest.approx(100.0)

    def test_update_pnl_negative(self):
        rm = RiskManager(initial_equity=10000.0)
        rm.update_pnl(-200.0)
        assert rm.state.equity == pytest.approx(9800.0)
        assert rm.state.daily_pnl == pytest.approx(-200.0)

    def test_daily_reset(self):
        import datetime

        rm = RiskManager(initial_equity=10000.0)
        rm.state.daily_pnl = -100.0
        rm.state.daily_loss_hit = True
        # Simulate yesterday's date
        rm.state.last_reset_date = datetime.date(2020, 1, 1)
        rm.check_daily_reset()
        assert rm.state.daily_pnl == 0.0
        assert rm.state.daily_loss_hit is False

    def test_minimum_quantity_enforced(self):
        rm = RiskManager(initial_equity=1.0)  # tiny equity
        order = make_order(stop_loss=49999.0)
        sized = rm.size_order(order, 50000.0)
        assert sized.quantity >= 0.001  # minimum
