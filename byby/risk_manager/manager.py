"""Risk manager: position sizing and risk controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import structlog

from byby.config import get_settings
from byby.strategies.base import DesiredOrder

logger = structlog.get_logger(__name__)


@dataclass
class RiskState:
    equity: float
    daily_pnl: float = 0.0
    open_positions: int = 0
    total_exposure: float = 0.0
    daily_loss_hit: bool = False
    last_reset_date: date = field(default_factory=date.today)


class RiskManager:
    """Enforces risk limits and sizes positions."""

    def __init__(self, initial_equity: float, settings=None) -> None:
        self.settings = settings or get_settings()
        self.state = RiskState(equity=initial_equity)

    def check_daily_reset(self) -> None:
        """Reset daily counters if new day."""
        today = date.today()
        if self.state.last_reset_date != today:
            logger.info(
                "daily_reset",
                prev_pnl=self.state.daily_pnl,
                date=str(today),
            )
            self.state.daily_pnl = 0.0
            self.state.daily_loss_hit = False
            self.state.last_reset_date = today

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is allowed."""
        self.check_daily_reset()

        if self.state.daily_loss_hit:
            return False, "daily_loss_limit_hit"

        daily_loss_pct = -self.state.daily_pnl / self.state.equity
        if daily_loss_pct >= self.settings.max_daily_loss:
            self.state.daily_loss_hit = True
            logger.warning(
                "daily_loss_limit_hit",
                daily_pnl=self.state.daily_pnl,
                limit=self.settings.max_daily_loss,
            )
            return False, "daily_loss_limit_hit"

        if self.state.open_positions >= self.settings.max_concurrent_trades:
            return False, "max_concurrent_trades_reached"

        if self.state.total_exposure >= self.settings.max_total_exposure:
            return False, "max_exposure_reached"

        return True, "ok"

    def size_order(
        self,
        order: DesiredOrder,
        current_price: float,
        atr: float | None = None,
    ) -> DesiredOrder:
        """Size the order using fixed fractional or volatility-adjusted sizing."""
        risk_amount = self.state.equity * self.settings.max_risk_per_trade

        if not order.stop_loss:
            # Use fixed fractional sizing
            stop_distance = atr * 2.0 if atr and atr > 0 else current_price * 0.02
        else:
            # Volatility-adjusted sizing: size = risk_amount / stop_distance
            stop_distance = abs(current_price - order.stop_loss)
            if stop_distance == 0:
                stop_distance = current_price * 0.01

        quantity = risk_amount / stop_distance

        # Round down to reasonable precision
        quantity = round(quantity, 6)
        # Ensure minimum viable quantity
        min_qty = 0.001
        quantity = max(quantity, min_qty)

        order.quantity = quantity
        logger.info(
            "order_sized",
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            risk_amount=risk_amount,
        )
        return order

    def update_pnl(self, pnl: float) -> None:
        """Update daily PnL."""
        self.state.daily_pnl += pnl
        self.state.equity += pnl
        logger.info(
            "pnl_updated", pnl=pnl, daily_pnl=self.state.daily_pnl, equity=self.state.equity
        )

    def update_positions(self, open_positions: int, total_exposure: float) -> None:
        """Update position tracking."""
        self.state.open_positions = open_positions
        self.state.total_exposure = total_exposure
