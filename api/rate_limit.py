"""Redis-backed fixed-window quotas with a development-safe local fallback."""

from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException, status

from .config import settings


class RateLimiter:
    def __init__(self):
        self._redis = None
        self._local: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        try:
            from redis.asyncio import from_url

            client = from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
            await client.ping()
            self._redis = client
        except Exception:
            self._redis = None
            if settings.redis_required:
                raise RuntimeError("Redis is required but unavailable")

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def consume(self, user_id: str, bucket: str, limit: int, window: int) -> None:
        key = f"jarvis:rate:{bucket}:{user_id}:{int(time.time()) // window}"
        if self._redis is not None:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, window + 1)
        else:
            async with self._lock:
                count, expires = self._local.get(key, (0, time.monotonic() + window))
                if expires <= time.monotonic():
                    count, expires = 0, time.monotonic() + window
                count += 1
                self._local[key] = (count, expires)
                if len(self._local) > 2000:
                    now = time.monotonic()
                    self._local = {k: v for k, v in self._local.items() if v[1] > now}
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Request limit reached. Please try again shortly.",
                headers={"Retry-After": str(window)},
            )


limiter = RateLimiter()
