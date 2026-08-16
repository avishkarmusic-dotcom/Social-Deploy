"""Two limiters that look similar and solve opposite problems.

`RateLimiter` protects us from users — a per-workspace token bucket on the API.
`ProviderBudget` protects providers from us. Every channel rations differently
(X counts reads per 15 minutes, YouTube spends quota units per day, Meta uses a
rolling per-app score), so the budget is per (provider, account) and honours a
server-set backoff above everything else. A 429 is a message, not a failure.
"""
from __future__ import annotations

import random
import time

import redis.asyncio as aioredis

_TAKE = """
local tokens = tonumber(redis.call('hget', KEYS[1], 'tokens') or ARGV[1])
local stamp  = tonumber(redis.call('hget', KEYS[1], 'ts') or ARGV[4])
local filled = math.min(tonumber(ARGV[1]), tokens + (ARGV[4] - stamp) * ARGV[2])
if filled < tonumber(ARGV[3]) then
  redis.call('hset', KEYS[1], 'tokens', filled, 'ts', ARGV[4])
  redis.call('expire', KEYS[1], 3600)
  return 0
end
redis.call('hset', KEYS[1], 'tokens', filled - ARGV[3], 'ts', ARGV[4])
redis.call('expire', KEYS[1], 3600)
return 1
"""


class RateLimiter:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_TAKE)

    @classmethod
    async def create(cls, url: str) -> "RateLimiter":
        return cls(aioredis.from_url(url, decode_responses=True))

    async def allow(self, key: str, *, burst: int, per_second: float, cost: int = 1) -> bool:
        got = await self._script(
            keys=[f"rl:{key}"], args=[burst, per_second, cost, time.time()]
        )
        return bool(got)

    async def close(self) -> None:
        await self._redis.aclose()


class ProviderBudget:
    """Per-account pacing with server-directed backoff."""

    DEFAULTS = {           # (burst, refill per second)
        "gmail": (250, 4.0),
        "outlook": (200, 3.0),
        "linkedin": (30, 0.2),
        "x": (15, 0.017),          # 15 per 15 minutes on the low tiers
        "youtube": (100, 0.1),
        "instagram": (200, 1.0),
        "messenger": (200, 1.0),
        "whatsapp": (80, 0.8),
        "slack": (50, 1.0),
        "telegram": (30, 0.5),
        "google_business": (60, 0.3),
    }

    def __init__(self, limiter: RateLimiter, redis: aioredis.Redis) -> None:
        self._limiter = limiter
        self._redis = redis

    async def acquire(self, provider: str, account_id: str, cost: int = 1) -> float:
        """Returns 0 when the call may proceed, else seconds to wait."""
        if (until := await self._redis.get(f"backoff:{provider}:{account_id}")):
            remaining = float(until) - time.time()
            if remaining > 0:
                return remaining
        burst, rate = self.DEFAULTS.get(provider, (60, 1.0))
        if await self._limiter.allow(f"{provider}:{account_id}", burst=burst,
                                     per_second=rate, cost=cost):
            return 0.0
        return cost / rate

    async def penalise(self, provider: str, account_id: str, retry_after_s: int) -> None:
        """The provider told us to stop. Jitter prevents every worker returning
        at the same instant and earning a second 429."""
        wait = retry_after_s + random.uniform(0, retry_after_s * 0.15)
        await self._redis.set(
            f"backoff:{provider}:{account_id}", time.time() + wait, ex=int(wait) + 5
        )
