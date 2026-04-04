import asyncio
import logging

from lib.UseRedis import get_redis_client
from lib.exception import EDMException

_logger = logging.getLogger(__name__)


class WaitEvent:
    """Асинхронний клас для очікування на подію в Redis."""

    def __init__(self, message_id: str, time: int = 10, sleep: int = 60):
        """Ініціалізація WaitEvent.

        Args:
            time: Максимальний час очікування в секундах
            sleep: Час очікування між перевірками в секундах
        """
        self.message_id = message_id
        self.time = time
        self.sleep = sleep

    @staticmethod
    def _get_redis_client():
        """Отримує глобальний Redis клієнт.

        Returns:
            Екземпляр UseRedisAsync (Singleton)
        """
        return get_redis_client()

    async def _check_event(self, key: str) -> bool:
        """Перевіряє наявність ключа в Redis.

        Args:
            key: Ключ для перевірки

        Returns:
            True якщо ключ існує, False інакше
        """
        _logger.debug(f"Читання ключа: {key}")
        redis_client = self._get_redis_client()
        flag = await redis_client.get_raw_from_redis(key)
        return flag is not None

    async def wait(self, key: str) -> bool:
        """Очікує на подію до встановленого часу.

        Args:
            key: Ключ для очікування

        Returns:
            True якщо подія відбулася

        Raises:
            TimeoutException: Якщо час очікування перевищено
        """
        _logger.info(f"Початок очікування на ключ: {key}")
        for i in range(self.time):
            flag = await self._check_event(key)
            if flag:
                _logger.info(f"Ключ {key} знайдено")
                return flag
            _logger.debug(f"Ключ {key} не знайдено, очікування {self.sleep} секунд")
            await asyncio.sleep(self.sleep)
        raise EDMException(
            redis=get_redis_client(),
            message_id=self.message_id,
            code="EDM:ERR:0005",
            message=f"Час очікування на ключ {key} перевищено",
            detail=f"Час очікування на ключ {key} перевищено"
        )