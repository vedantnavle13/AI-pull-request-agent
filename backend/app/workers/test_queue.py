import asyncio

from arq import create_pool
from arq.connections import RedisSettings


async def main():

    redis = await create_pool(
        RedisSettings(
            host="127.0.0.1",
            port=6379,
        )
    )

    await redis.enqueue_job(
        "test_job",
        "Hello from AI PR Review Agent",
    )

    await redis.close()


if __name__ == "__main__":
    asyncio.run(main())