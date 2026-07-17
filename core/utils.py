from datetime import datetime
from zoneinfo import ZoneInfo
import redis
import os

def ahora_lima() -> datetime:
    return datetime.now(ZoneInfo("America/Lima"))

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)
