"""
Rate limiting (tiêu chí 7): sliding window 60 giây, state lưu trong Redis
nên mọi worker/instance dùng chung và còn nguyên sau khi restart agent.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    redis_key = "rl:" + hashlib.sha256(key.encode()).hexdigest()[:24]
    now = time.time()
    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, now - WINDOW_SECONDS)
        pipe.zcard(redis_key)
        pipe.zrange(redis_key, 0, 0, withscores=True)
        _, count, oldest = pipe.execute()
        if count >= settings.rate_limit_per_minute:
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        pipe = r.pipeline()
        pipe.zadd(redis_key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
