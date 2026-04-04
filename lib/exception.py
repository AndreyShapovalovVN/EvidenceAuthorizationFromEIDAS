import asyncio
import logging
import os

from redis_keys import Keys
from lib.UseRedis import UseRedisAsync

_logger = logging.getLogger(__name__)

KEYS = Keys()


class EDMException(Exception):
    QUEUE_OUTCOMING = os.getenv("QUEUE_OUTCOMING")

    def __init__(
        self,
        redis: UseRedisAsync,
        queue: str | None,
        key: str | None,
        message_id: str,
        code: str,
        message: str,
        detail: str,
        preview_link: str | None = None,
    ):
        self.code = code
        self.message = message
        self.detail = detail
        self.redis = redis
        self.queue = queue or self.QUEUE_OUTCOMING
        self.key = key or KEYS.response_exp(message_id)
        self.message_id = message_id
        self.preview_link = preview_link

        asyncio.create_task(self._save_exception_data())
        asyncio.create_task(self._push_to_queue())

        super().__init__(f"[{self.code}] {self.message}: {detail}")

    async def _save_exception_data(self):
        try:
            exception_data = {
                "exception": {
                    "code": self.code,
                    "message": self.message,
                    "detail": self.detail,
                    "preview_link": self.preview_link,
                }
            }
            await self.redis.save_to_redis(self.key, exception_data)
            _logger.info(f"Exception data saved to Redis with key: {self.key}")
        except Exception as e:
            _logger.error(f"Failed to save exception data to Redis: {e}")

    async def _push_to_queue(self):
        try:
            await self.redis.push_to_queue(self.queue, self.message_id)
            _logger.info(f"Message ID {self.message_id} pushed to queue: {self.queue}")
        except Exception as e:
            _logger.error(f"Failed to push message_id to queue: {e}")
