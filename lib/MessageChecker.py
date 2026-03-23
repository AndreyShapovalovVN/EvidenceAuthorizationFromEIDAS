"""
Логіка перевірки повідомлення в Redis перед рендерингом сторінки авторизації.

Ключі Redis:
  oots:message:response:evidence:{message_id}  — відповідь сервісу з можливою помилкою
  oots:message:request:preview:{message_id}    — прапор готовності preview
"""

import asyncio
import logging
from dataclasses import dataclass

from lib.UseRedis import UseRedisAsync

_logger = logging.getLogger(__name__)

# ─── константи ───────────────────────────────────────────────────────────────

EDM_ERR_CODE = "EDM:ERR:0002"

EVIDENCE_KEY = "oots:message:response:evidence:{message_id}"
PREVIEW_FLAG_KEY = "oots:message:request:preview:{message_id}"

DEFAULT_TIMEOUT: float = 30.0   # секунд — максимальний час очікування прапора
DEFAULT_INTERVAL: float = 1.5   # секунд між спробами поллінгу


# ─── результат ───────────────────────────────────────────────────────────────

@dataclass
class ExceptionInfo:
    """Розібраний об'єкт exception з ключа evidence."""
    code: str
    message: str
    detail: str | None = None
    preview_link: str | None = None


@dataclass
class MessageStatus:
    """Підсумковий стан перевірки повідомлення."""
    # Технічні деталі exception з evidence (для EDM:ERR:0002 це успішний маркер)
    evidence_error: ExceptionInfo | None = None
    # True — прапор preview з'явився в Redis
    preview_ready: bool = False
    # True — таймаут очікування прапора
    timed_out: bool = False

    @property
    def has_error(self) -> bool:
        if self.evidence_error is None:
            return False
        # EDM:ERR:0002 трактуємо як успішний бізнес-сценарій.
        return self.evidence_error.code != EDM_ERR_CODE


# ─── внутрішні функції ───────────────────────────────────────────────────────

async def _get_evidence_exception(
    client: UseRedisAsync,
    message_id: str,
) -> ExceptionInfo | None:
    """Зчитує ключ evidence з Redis та повертає ExceptionInfo якщо code == EDM:ERR:0002.

    Args:
        client:     активний UseRedisAsync
        message_id: ідентифікатор повідомлення

    Returns:
        ExceptionInfo або None
    """
    key = EVIDENCE_KEY.format(message_id=message_id)
    data = await client.get_from_redis(key)

    if not isinstance(data, dict):
        _logger.debug("Evidence key not found or not a dict: %s", key)
        return None

    exception = data.get("exception")
    if not isinstance(exception, dict):
        _logger.debug("No 'exception' block in evidence: %s", key)
        return None

    code = exception.get("code", "")
    if code != EDM_ERR_CODE:
        _logger.debug("Evidence code %r != %r, skipping", code, EDM_ERR_CODE)
        return None

    _logger.info("EDM:ERR:0002 detected as success marker for message_id=%s", message_id)
    return ExceptionInfo(
        code=code,
        message=exception.get("message", ""),
        detail=exception.get("detail"),
        preview_link=exception.get("preview_link"),
    )


async def _wait_for_preview_flag(
    client: UseRedisAsync,
    message_id: str,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
) -> bool:
    """Очікує появи прапора preview в Redis з поллінгом.

    Args:
        client:     активний UseRedisAsync
        message_id: ідентифікатор повідомлення
        timeout:    максимальний час очікування (секунди)
        interval:   пауза між спробами (секунди)

    Returns:
        True — прапор знайдено, False — таймаут
    """
    flag_key = PREVIEW_FLAG_KEY.format(message_id=message_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while loop.time() < deadline:
        value = await client.get_raw_from_redis(flag_key)
        if value is not None:
            _logger.info("Preview flag appeared for message_id=%s", message_id)
            return True
        await asyncio.sleep(interval)

    _logger.warning(
        "Timeout (%.1fs) waiting for preview flag, message_id=%s",
        timeout,
        message_id,
    )
    return False


# ─── публічний API ────────────────────────────────────────────────────────────

async def check_message(
    client: UseRedisAsync,
    message_id: str,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
) -> MessageStatus:
    """Повна перевірка повідомлення перед рендерингом сторінки.

    Порядок:
      1. Перевіряємо наявність коду EDM:ERR:0002 у evidence.
         Якщо знайдено — це успішний сценарій, одразу повертаємо success без очікування.
      2. Якщо коду немає — очікуємо появи прапора preview з поллінгом.

    Args:
        client:     активний UseRedisAsync
        message_id: ідентифікатор повідомлення
        timeout:    максимальний час очікування прапора (секунди)
        interval:   пауза між спробами поллінгу (секунди)

    Returns:
        MessageStatus з результатами обох перевірок
    """
    evidence_error = await _get_evidence_exception(client, message_id)
    if evidence_error is not None:
        return MessageStatus(
            evidence_error=evidence_error,
            preview_ready=True,
            timed_out=False,
        )

    preview_ready = await _wait_for_preview_flag(client, message_id, timeout, interval)
    return MessageStatus(
        preview_ready=preview_ready,
        timed_out=not preview_ready,
    )


