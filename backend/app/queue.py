from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


redis_pool: ArqRedis | None = None


async def get_redis() -> ArqRedis:

    global redis_pool

    if redis_pool is None:

        redis_pool = await create_pool(
            RedisSettings(
                host="127.0.0.1",
                port=6379,
            )
        )

    return redis_pool
    return redis_pool