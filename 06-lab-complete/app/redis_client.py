"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

Client được tạo lazy (from_url không mở kết nối), nên app vẫn khởi động được
khi Redis chưa sẵn sàng. redis_healthy() dùng cho GET /ready.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except Exception:
        return False
