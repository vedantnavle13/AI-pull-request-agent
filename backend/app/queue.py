from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import REDIS_HOST, REDIS_PORT, REDIS_DB


redis_pool: ArqRedis | None = None


async def get_redis() -> ArqRedis:
    global redis_pool

    if redis_pool is None:
        redis_pool = await create_pool(
            RedisSettings(
                host=REDIS_HOST,
                port=REDIS_PORT,
                database=REDIS_DB,
            )
        )

    return redis_pool