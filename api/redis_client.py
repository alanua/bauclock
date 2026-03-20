import redis.asyncio as redis
from api.config import settings

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
redis = redis_client
