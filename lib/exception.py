import asyncio
import logging
import os

from lib.UseRedis import UseRedisAsync
from redis_keys import Keys

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
        self.key = key or KEYS.get_response_exp(message_id)
        self.message_id = message_id
        self.preview_link = preview_link

        self._on_exception_created()

        super().__init__(f"[{self.code}] {self.message}: {detail}")

    def _on_exception_created(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._process_exception_created())
            return
        loop.create_task(self._process_exception_created())

    async def _process_exception_created(self):
        await self._save_exception_data()
        await self._push_to_queue()

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
            _logger.info("Exception data saved to Redis with key: %s", self.key)
        except Exception:
            _logger.exception(
                "Failed to save exception data to Redis with key: %s", self.key
            )

    async def _push_to_queue(self):
        try:
            await self.redis.push_to_queue(self.queue, self.message_id)
            _logger.info("Message ID %s pushed to queue: %s", self.message_id, self.queue)
        except Exception:
            _logger.exception("Failed to push message_id %s to queue: %s", self.message_id, self.queue)
