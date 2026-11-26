"""
Cost guard (tiêu chí 8): cộng dồn chi phí LLM vào Redis theo ngày và theo tháng.
Tổng chi phí chạm ngân sách → HTTP 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:day:{now:%Y-%m-%d}", f"cost:month:{now:%Y-%m}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → 402."""
    day_key, month_key = _keys()
    try:
        day, month = r.mget(day_key, month_key)
    except RedisError:
        raise HTTPException(status_code=503, detail="Cost guard unavailable")
    if float(day or 0) >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")
    if float(month or 0) >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402, detail="Monthly budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    day_key, month_key = _keys()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(day_key, cost)
        pipe.expire(day_key, 3 * 86400)
        pipe.incrbyfloat(month_key, cost)
        pipe.expire(month_key, 35 * 86400)
        pipe.execute()
    except RedisError:
        pass  # request đã phục vụ xong; không làm hỏng response vì lỗi ghi chi phí
    return cost
