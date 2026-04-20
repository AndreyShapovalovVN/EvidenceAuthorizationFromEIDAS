# mypy: ignore-errors
import json
import logging
import os
from typing import Any, Optional

import redis
import redis.asyncio as Redis

_logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TTL = int(os.getenv("REDIS_TTL", "86400"))
REDIS_PREFIX = os.getenv("REDIS_PREFIX")
REDIS_TIMEOUT = int(os.getenv("REDIS_TIMEOUT", "6"))

# Глобальний екземпляр для централізованого управління з'єднанням
_redis_instance: Optional["UseRedisAsync"] = None


def get_redis_client() -> "UseRedisAsync":
    """Отримує глобальний екземпляр клієнта Redis (Singleton-патерн).

    Returns:
        Екземпляр UseRedisAsync

    Raises:
        redis.exceptions.ConnectionError: Якщо з'єднання з Redis не ініціалізовано
    """
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = UseRedisAsync()
    return _redis_instance


async def initialize_redis(redis_url: Optional[str] = None) -> "UseRedisAsync":
    """Ініціалізує глобальне з'єднання Redis на старті додатку.

    Args:
        redis_url: URL для підключення. Якщо None - використовує REDIS_URL з оточення

    Returns:
        Ініціалізований екземпляр UseRedisAsync

    Raises:
        redis.exceptions.ConnectionError: Якщо підключення не вдалось
    """
    global _redis_instance
    _redis_instance = UseRedisAsync(redis_url)
    await _redis_instance.health_check()
    _logger.info("Redis клієнт ініціалізований та перевірений")
    return _redis_instance


async def close_redis() -> None:
    """Закриває глобальне з'єднання Redis на завершення додатка."""
    global _redis_instance
    if _redis_instance is not None:
        await _redis_instance.disconnect()
        _redis_instance = None
        _logger.info("Redis з'єднання закрито")


class UseRedisAsync:
    """Клас для асинхронних операцій з Redis та обробки помилок.

    Attributes:
        _redis_client: Екземпляр асинхронного клієнта Redis
    """

    def __init__(
            self,
            redis_url: str | Redis.Redis | None = None,
            redis_prefix: str | None = None,
    ):
        self._redis_prefix = self._normalize_prefix(
            redis_prefix if redis_prefix is not None else REDIS_PREFIX
        )
        try:
            if isinstance(redis_url, Redis.Redis):
                self._redis_client = redis_url
            else:
                url = redis_url if isinstance(redis_url, str) else REDIS_URL
                _logger.debug(f"URL підключення Redis: {url}")
                self._redis_client = Redis.from_url(url)
        except Exception as e:
            raise redis.exceptions.ConnectionError(
                f"Не вдалось підключитись до Redis: {e}"
            )

    @staticmethod
    def _normalize_prefix(prefix: str) -> str:
        clean_prefix = (prefix or "").strip().strip(":")
        return f"{clean_prefix}:" if clean_prefix else ""

    def _prefixed_key(self, key: str) -> str:
        if not self._redis_prefix or key.startswith(self._redis_prefix):
            return key
        return f"{self._redis_prefix}{key}"

    async def get_from_redis(self, key: str) -> dict | list | None:
        """Отримує та десеріалізує JSON дані з Redis за ключем.

        Args:
            key: Ключ Redis для отримання даних

        Returns:
            Десеріалізований словник або None, якщо ключ не існує або дані невалідні
        """
        if key is None:
            raise ValueError("Ключ не може бути None")

        redis_key = self._prefixed_key(key)
        data = await self._redis_client.get(redis_key)
        if data is None:
            return None
        try:
            data = json.loads(data)
            _logger.debug(f"Отримано дані з Redis для ключа {redis_key}: {data}")
            return data
        except json.JSONDecodeError as e:
            _logger.error(f"Не вдалось розшифрувати JSON для ключа {redis_key}: {e}")
            return None

    async def get_raw_from_redis(self, key: str) -> bytes | None:
        """Отримує сирі bytes дані з Redis.

        Args:
            key: Ключ Redis для отримання сирих даних

        Returns:
            Сирі дані або None, якщо ключ не існує
        """
        if key is None:
            raise ValueError("Ключ не може бути None")

        redis_key = self._prefixed_key(key)
        data = await self._redis_client.get(redis_key)
        _logger.debug(f"Отримано сирі дані з Redis для ключа {redis_key}: {data}")
        return data if isinstance(data, bytes) else None

    async def save_to_redis(self, key: str, data: dict[Any, Any] | list | str) -> None:
        """Зберігає дані як JSON до Redis з TTL.

        Args:
            key: Ключ Redis для зберігання даних
            data: Дані для серіалізації та зберігання
        """
        if key is None:
            raise ValueError("Ключ не може бути None")

        redis_key = self._prefixed_key(key)
        await self._redis_client.set(redis_key, json.dumps(data, default=str), ex=TTL)
        _logger.debug(f"Збережено дані до Redis для ключа {redis_key}: {data}")

    async def save_raw_to_redis(self, key: str, data: bytes) -> None:
        """Зберігає сирі bytes дані до Redis з TTL.

        Args:
            key: Ключ Redis для зберігання сирих даних
            data: Сирі дані для зберігання
        """
        if key is None:
            raise ValueError("Ключ не може бути None")

        redis_key = self._prefixed_key(key)
        await self._redis_client.set(redis_key, data, ex=TTL)
        _logger.debug(f"Збережено сирі дані до Redis для ключа {redis_key}: {data}")

    async def push_to_queue(self, queue_name: str, message: str) -> None:
        """Поміщає повідомлення до Redis-черги list.

        Args:
            queue_name: Назва черги Redis list
            message: Повідомлення для поміщення в чергу
        """
        redis_queue = self._prefixed_key(queue_name)
        await self._redis_client.lpush(redis_queue, message)
        _logger.debug(f"Поміщено повідомлення до черги {redis_queue}: {message}")

    async def set_flag(self, key: str, value: bool) -> None:
        """Зберігає булевий прапор до Redis з TTL.

        Args:
            key: Ключ Redis для зберігання прапора
            value: Булеве значення для зберігання

        Raises:
            ValueError: Якщо ключ є None
        """
        if key is None:
            raise ValueError("Ключ не може бути None")

        redis_key = self._prefixed_key(key)
        # Зберігаємо як JSON boolean: true/false
        flag_value = json.dumps(value)
        await self._redis_client.set(redis_key, flag_value, ex=TTL)
        _logger.debug(f"Встановлено прапор {redis_key} = {value}")

    async def get_flag(self, key: str, default: bool = False) -> bool:
        """Отримує булевий прапор з Redis.

        Args:
            key: Ключ Redis для отримання прапора
            default: Значення за замовчуванням, якщо прапор не знайдено

        Returns:
            Булеве значення прапора або default, якщо ключ не існує

        Raises:
            ValueError: Якщо ключ є None
        """
        if key is None:
            raise ValueError("Ключ не може бути None")

        redis_key = self._prefixed_key(key)
        data = await self._redis_client.get(redis_key)

        if data is None:
            _logger.debug(f"Прапор {redis_key} не знайдено, повертаємо default: {default}")
            return default

        try:
            value = json.loads(data)
            if not isinstance(value, bool):
                _logger.warning(f"Значення прапора {redis_key} не є boolean: {value}, повертаємо default")
                return default
            _logger.debug(f"Отримано прапор {redis_key} = {value}")
            return value
        except json.JSONDecodeError as e:
            _logger.error(f"Не вдалося розшифрувати булевий прапор {redis_key}: {e}")
            return default

    async def pop_from_queue(
            self,
            queue_name: str,
            return_tuple_as_string: bool = False,
    ) -> Optional[str]:
        """Отримує повідомлення з Redis-черги list.

        Args:
            queue_name: Назва черги Redis list
            return_tuple_as_string: Якщо True, повертає рядок-кортеж
                у форматі "(<queue>, <payload>)". За замовчуванням
                повертається лише payload як str.

        Returns:
            Повідомлення з черги або None якщо черга порожня
        """
        if queue_name is None:
            raise ValueError("Назва черги не може бути None")

        redis_queue = self._prefixed_key(queue_name)
        result = await self._redis_client.brpop([redis_queue], timeout=REDIS_TIMEOUT)
        if result:
            if return_tuple_as_string:
                if isinstance(result, tuple) and len(result) == 2:
                    queue_part = result[0].decode("utf-8") if isinstance(result[0], bytes) else str(result[0])
                    payload_part = result[1].decode("utf-8") if isinstance(result[1], bytes) else str(result[1])
                    tuple_str = f"({queue_part}, {payload_part})"
                    _logger.debug(f"Отримано кортеж-повідомлення з черги {redis_queue}: {tuple_str}")
                    return tuple_str

                tuple_str = str(result)
                _logger.debug(f"Отримано кортеж-повідомлення з черги {redis_queue}: {tuple_str}")
                return tuple_str

            payload = result[1] if isinstance(result, tuple) and len(result) == 2 else result
            if payload is None:
                return None

            message = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            _logger.debug(f"Отримано повідомлення з черги {redis_queue}: {message}")
            return message
        return None

    async def health(self) -> bool:
        """Перевіряє здоров'я з'єднання з Redis без виключень.

        Зручно використовувати в health-endpoint'ах або умовних перевірках,
        коли важливо отримати bool без обробки виключень.

        Returns:
            True якщо з'єднання активне, False інакше
        """
        try:
            await self._redis_client.ping()
            _logger.debug("Redis здоров'я: OK")
            return True
        except Exception as e:
            _logger.warning(f"Redis недоступний: {e}")
            return False

    async def health_check(self) -> bool:
        """Перевіряє здоров'я з'єднання з Redis.

        На відміну від :meth:`health`, кидає виключення при невдачі —
        підходить для ініціалізації або критичних перевірок.

        Returns:
            True якщо з'єднання активне

        Raises:
            redis.exceptions.ConnectionError: Якщо з'єднання неможливе
        """
        if not await self.health():
            raise redis.exceptions.ConnectionError("Redis недоступний")
        return True

    async def disconnect(self) -> None:
        """Закриває з'єднання з Redis."""
        try:
            await self._redis_client.aclose()
            _logger.debug("Redis з'єднання закрито")
        except Exception as e:
            _logger.error(f"Помилка при закритті Redis: {e}")

    async def __aenter__(self) -> "UseRedisAsync":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    @property
    def redis(self) -> Redis.Redis:
        """Отримує екземпляр клієнта Redis.

        Returns:
            Екземпляр клієнта Redis
        """
        return self._redis_client
