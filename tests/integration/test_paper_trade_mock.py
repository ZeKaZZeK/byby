"""Integration test for paper trading with mocked exchange."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from byby.market_data.models import OHLCV, MarketState
from byby.paper_trade.runner import PaperTradingRunner


def make_candles(n: int = 150) -> list[OHLCV]:
    candles = []
    price = 50000.0
    now = datetime.now(tz=timezone.utc)
    import math

    for i in range(n):
        t = i / n * 4 * math.pi
        trend = math.sin(t) * 0.002
        open_ = price
        close = price * (1 + trend)
        high = max(open_, close) * 1.001
        low = min(open_, close) * 0.999
        candles.append(
            OHLCV(
                timestamp=now - timedelta(minutes=n - i),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=5.0,
                symbol="BTC/USDT:USDT",
            )
        )
        price = close
    return candles


class TestPaperTradingIntegration:
    @pytest.mark.asyncio
    async def test_tick_processes_without_error(self):
        """Test that a single tick runs without raising exceptions."""
        runner = PaperTradingRunner()
        candles = make_candles(150)

        # Mock the data manager
        mock_dm = AsyncMock()
        mock_state = MarketState(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            ohlcv_history=candles,
        )
        mock_dm.get_market_state = AsyncMock(return_value=mock_state)
        runner._data_manager = mock_dm

        # Mock alerter to avoid network calls
        mock_alerter = AsyncMock()
        mock_alerter.__aenter__ = AsyncMock(return_value=mock_alerter)
        mock_alerter.__aexit__ = AsyncMock(return_value=None)
        runner._alerter = mock_alerter

        # Should not raise
        await runner._tick()

    @pytest.mark.asyncio
    async def test_daily_loss_blocks_trading(self):
        """Test that daily loss limit blocks new trades."""
        runner = PaperTradingRunner()
        candles = make_candles(150)

        mock_dm = AsyncMock()
        mock_state = MarketState(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            ohlcv_history=candles,
        )
        mock_dm.get_market_state = AsyncMock(return_value=mock_state)
        runner._data_manager = mock_dm

        mock_alerter = AsyncMock()
        mock_alerter.__aenter__ = AsyncMock(return_value=mock_alerter)
        mock_alerter.__aexit__ = AsyncMock(return_value=None)
        mock_alerter.alert_daily_loss_hit = AsyncMock()
        runner._alerter = mock_alerter

        # Simulate daily loss hit
        runner._risk_manager.update_pnl(-500.0)  # 5% loss

        initial_positions = len(runner._paper_positions)
        await runner._tick()
        # No new positions should be added
        assert len(runner._paper_positions) == initial_positions

    @pytest.mark.asyncio
    async def test_paper_order_execution(self):
        """Test paper order execution simulates fill."""
        runner = PaperTradingRunner()

        mock_alerter = AsyncMock()
        mock_alerter.__aenter__ = AsyncMock(return_value=mock_alerter)
        mock_alerter.__aexit__ = AsyncMock(return_value=None)
        mock_alerter.alert_order_filled = AsyncMock()
        runner._alerter = mock_alerter

        from byby.strategies.base import DesiredOrder, OrderSide, OrderType

        order = DesiredOrder(
            symbol="BTC/USDT:USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.05,
            stop_loss=49000.0,
            take_profit=52000.0,
            strategy_id="test",
        )

        await runner._execute_paper_order(order, 50000.0)
        assert len(runner._paper_positions) == 1
        assert runner._paper_positions[0]["side"] == "buy"

    @pytest.mark.asyncio
    async def test_stop_loss_closes_position(self):
        """Test that stop loss triggers position close."""
        runner = PaperTradingRunner()

        mock_alerter = AsyncMock()
        mock_alerter.__aenter__ = AsyncMock(return_value=mock_alerter)
        mock_alerter.__aexit__ = AsyncMock(return_value=None)
        mock_alerter.alert_order_filled = AsyncMock()
        runner._alerter = mock_alerter

        # Add a long position
        runner._paper_positions.append(
            {
                "id": "test1",
                "symbol": "BTC/USDT:USDT",
                "side": "buy",
                "quantity": 0.1,
                "entry_price": 50000.0,
                "stop_loss": 49000.0,
                "take_profit": 52000.0,
                "strategy_id": "test",
                "entry_time": datetime.now(tz=timezone.utc).isoformat(),
            }
        )

        # Price drops to stop loss
        mock_state = MarketState(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            ohlcv_history=[],
        )
        # Manually set last_price via orderbook
        from byby.market_data.models import OrderBook, OrderBookEntry, OrderBookSide

        mock_state.orderbook = OrderBook(
            symbol="BTC/USDT:USDT",
            timestamp=datetime.now(tz=timezone.utc),
            bids=[OrderBookEntry(price=48990.0, size=1.0, side=OrderBookSide.BID)],
            asks=[OrderBookEntry(price=49010.0, size=1.0, side=OrderBookSide.ASK)],
        )

        await runner._check_paper_exits(mock_state)
        # SL at 49000, mid price = (48990 + 49010) / 2 = 49000 ≤ SL → position closes
        assert len(runner._paper_positions) == 0
