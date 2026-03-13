"""Telegram alert integration."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog

from byby.config import get_settings

logger = structlog.get_logger(__name__)


class TelegramAlerter:
    """Sends alerts via Telegram Bot API."""

    def __init__(self, bot_token: str = "", chat_id: str = "", settings=None) -> None:
        _settings = settings or get_settings()
        self.bot_token = bot_token or _settings.telegram_bot_token
        self.chat_id = chat_id or _settings.telegram_chat_id
        self._client: httpx.AsyncClient | None = None
        self._enabled = bool(self.bot_token and self.chat_id)

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        """Send a message via Telegram."""
        if not self._enabled:
            logger.debug("telegram_disabled", message=message[:100])
            return False

        if not self._client:
            self._client = httpx.AsyncClient(timeout=10.0)

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            response = await self._client.post(
                url,
                json={"chat_id": self.chat_id, "text": message, "parse_mode": parse_mode},
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error("telegram_send_failed", error=str(e))
            return False

    async def alert_daily_loss_hit(self, daily_pnl: float, limit_pct: float) -> None:
        msg = (
            f"🚨 *DAILY LOSS LIMIT HIT*\n"
            f"Daily PnL: `${daily_pnl:.2f}`\n"
            f"Limit: `{limit_pct * 100:.1f}%`\n"
            f"Time: `{datetime.now(tz=timezone.utc).isoformat()}`\n"
            f"⛔ Trading suspended for today."
        )
        await self.send(msg)

    async def alert_ws_disconnect(self, symbol: str) -> None:
        msg = f"⚠️ *WebSocket Disconnected*\nSymbol: `{symbol}`\nReconnecting..."
        await self.send(msg)

    async def alert_exception(self, component: str, error: str) -> None:
        msg = f"🔴 *Exception in {component}*\n```\n{error[:500]}\n```"
        await self.send(msg)

    async def alert_regime_change(
        self, from_regime: str, to_regime: str, confidence: float
    ) -> None:
        emoji = {
            "TREND_UP": "📈",
            "TREND_DOWN": "📉",
            "RANGE": "↔️",
            "HIGH_VOL": "⚡",
            "ILLIQUID": "🏜️",
        }.get(to_regime, "❓")
        msg = (
            f"{emoji} *Regime Change*\n"
            f"`{from_regime}` → `{to_regime}`\n"
            f"Confidence: `{confidence:.1%}`"
        )
        await self.send(msg)

    async def alert_order_filled(
        self, symbol: str, side: str, qty: float, price: float, pnl: float | None = None
    ) -> None:
        emoji = "🟢" if side == "buy" else "🔴"
        msg = (
            f"{emoji} *Order Filled*\n"
            f"Symbol: `{symbol}`\n"
            f"Side: `{side.upper()}`\n"
            f"Qty: `{qty}`  Price: `${price:.2f}`"
        )
        if pnl is not None:
            pnl_emoji = "✅" if pnl >= 0 else "❌"
            msg += f"\nPnL: {pnl_emoji} `${pnl:.2f}`"
        await self.send(msg)

    async def alert_deploy(self, version: str, environment: str) -> None:
        msg = (
            f"🚀 *Deployment*\n"
            f"Version: `{version}`\n"
            f"Environment: `{environment}`\n"
            f"Time: `{datetime.now(tz=timezone.utc).isoformat()}`"
        )
        await self.send(msg)
