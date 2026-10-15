import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import RateLimitedError

logger = structlog.get_logger(__name__)


async def enforce_fixed_window(redis: Redis, key: str, *, limit: int, window_seconds: int) -> None:
    """Allow at most `limit` hits per `window_seconds` for `key`; raise RateLimitedError beyond.

    INCR + EXPIRE NX run in one MULTI/EXEC transaction, so the counter is atomic across
    API replicas and the window starts at the first hit. If Redis is unavailable we fail
    open (log and allow) so an outage of the limiter does not take login down with it.
    """
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()
    except RedisError:
        logger.warning("rate_limiter_unavailable", key_prefix=key.split(":", 2)[:2])
        return

    if count > limit:
        raise RateLimitedError(retry_after=max(int(ttl), 1))
