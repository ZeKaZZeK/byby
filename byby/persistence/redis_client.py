"""Redis client for ephemeral state."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from byby.config import get_settings

logger = structlog.get_logger(__name__)

REGIME_KEY = "byby:current_regime"
RISK_STATE_KEY = "byby:risk_state"
LEADER_KEY = "byby:leader"
ACTIVE_ORDERS_KEY = "byby:active_orders"


class RedisClient:
    """Async Redis client wrapper."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            self.settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await self._client.ping()
        logger.info("redis_connected", url=self.settings.redis_url.split("@")[-1])

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        if not self._client:
            return
        data = json.dumps(value)
        if ttl:
            await self._client.setex(key, ttl, data)
        else:
            await self._client.set(key, data)

    async def get_json(self, key: str) -> Any | None:
        if not self._client:
            return None
        data = await self._client.get(key)
        return json.loads(data) if data else None

    async def store_regime(self, regime: str, confidence: float) -> None:
        await self.set_json(REGIME_KEY, {"regime": regime, "confidence": confidence}, ttl=300)

    async def get_regime(self) -> dict | None:
        return await self.get_json(REGIME_KEY)

    async def store_risk_state(self, state: dict) -> None:
        await self.set_json(RISK_STATE_KEY, state, ttl=86400)

    async def get_risk_state(self) -> dict | None:
        return await self.get_json(RISK_STATE_KEY)

    async def acquire_leader_lock(self, instance_id: str, ttl: int = 30) -> bool:
        """Try to acquire leader lock (NX = only set if not exists)."""
        if not self._client:
            return True  # single instance
        result = await self._client.set(LEADER_KEY, instance_id, nx=True, ex=ttl)
        return result is not None

    async def renew_leader_lock(self, instance_id: str, ttl: int = 30) -> bool:
        """Renew leader lock if we own it."""
        if not self._client:
            return True
        current = await self._client.get(LEADER_KEY)
        if current == instance_id:
            await self._client.expire(LEADER_KEY, ttl)
            return True
        return False
