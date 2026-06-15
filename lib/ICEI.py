"""ICEI (ІСЕІ) OAuth2 client for id.gov.ua identification.

Spec reference: IDInfoProcessingD_QA.pdf (V15_14012026)
"""

import logging
import importlib
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import httpx

_logger = logging.getLogger(__name__)

IDGOV_BASE_URL = os.getenv("IDGOV_BASE_URL", "https://test.id.gov.ua")
IDGOV_CLIENT_ID = os.getenv("ICEI_CLIENT_ID")
IDGOV_CLIENT_SECRET = os.getenv("ICEI_CLIENT_SECRET")
IDGOV_AUTH_TYPE = os.getenv("ICEI_AUTH_TYPE", "dig_sign")
IIT_DECRYPTOR_FUNC = os.getenv("IIT_DECRYPTOR_FUNC")

# Поля сертифіката, що запитуються (Таблиця 2.2.6 специфікації)
DEFAULT_FIELDS = (
    "issuer,issuercn,serial,subject,subjectcn,locality,state,o,ou,title,"
    "lastname,givenname,middlename,email,address,phone,dns,"
    "edrpoucode,drfocode,unzr,isqscd"
)


class ICEIError(Exception):
    """Raised when any step of ICEI identification fails."""


def _load_iit_decryptor() -> Callable[[str], dict] | None:
    """Load custom IIT decryptor from env IIT_DECRYPTOR_FUNC=module:function."""
    if not IIT_DECRYPTOR_FUNC:
        return None

    if ":" not in IIT_DECRYPTOR_FUNC:
        raise ICEIError("IIT_DECRYPTOR_FUNC must be in format module:function")

    module_name, function_name = IIT_DECRYPTOR_FUNC.split(":", 1)
    try:
        module = importlib.import_module(module_name)
        decryptor = getattr(module, function_name)
    except Exception as exc:
        raise ICEIError(f"Failed to load IIT decryptor '{IIT_DECRYPTOR_FUNC}': {exc}") from exc

    if not callable(decryptor):
        raise ICEIError(f"Configured IIT decryptor '{IIT_DECRYPTOR_FUNC}' is not callable")

    return decryptor


@dataclass
class UserProfile:
    """Ідентифікаційні дані, отримані від id.gov.ua (Таблиця 2.2.6).

    Атрибути відповідають полям JSON-відповіді get-user-info.
    """

    givenname: str                   # Ім'я
    lastname: str                    # Прізвище
    middlename: Optional[str]        # По батькові
    edrpoucode: Optional[str]        # РНОКПП (ІПН)
    drfocode: Optional[str]          # Код ДРФО (альтернатива РНОКПП)
    unzr: Optional[str]              # Унікальний номер запису в ЄДР
    auth_type: Optional[str]         # Тип аутентифікації (dig_sign / bank_id)
    subjectcn: Optional[str]         # Загальне ім'я (CN) власника сертифіката
    date_of_birth: Optional[str] = None  # Дата народження (якщо доступна у провайдера)
    gender: Optional[str] = None         # Стать (якщо доступна у провайдера)
    raw: dict = field(default_factory=dict)  # Повна відповідь сервера

    @property
    def identifier(self) -> str:
        """Основний ідентифікатор: РНОКПП → ДРФО → УНЗР (перший доступний)."""
        return self.edrpoucode or self.drfocode or self.unzr or ""

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        """Побудувати `UserProfile` з JSON-словника відповіді get-user-info."""
        return cls(
            givenname=data.get("givenname") or "",
            lastname=data.get("lastname") or "",
            middlename=data.get("middlename") or None,
            edrpoucode=data.get("edrpoucode") or None,
            drfocode=data.get("drfocode") or None,
            unzr=data.get("unzr") or None,
            auth_type=data.get("auth_type") or None,
            subjectcn=data.get("subjectcn") or None,
            date_of_birth=(
                data.get("date_of_birth")
                or data.get("dateOfBirth")
                or data.get("birthdate")
                or None
            ),
            gender=(data.get("gender") or data.get("sex") or None),
            raw=data,
        )


class IdICEI:
    """OAuth2-клієнт для ідентифікації через id.gov.ua (ІСЕІ).

    Реалізований потік (IDInfoProcessingD_QA.pdf):

    1. Сформувати URL авторизації → ``auth_url``  (крок 3)
    2. Перенаправити браузер користувача на ``auth_url``
    3. Користувач автентифікується на id.gov.ua
    4. Браузер повертається на ``redirect_uri?code=...&state=...``  (крок 10)
    5. ``get_access_token(code)``  → access_token + user_id  (кроки 11.1–11.2)
    6. ``get_user_info(access_token, user_id)``  → дані особи  (кроки 11.3–11.4)
    7. ``fetch_person(code)``  — кроки 5+6 разом, повертає ``UserProfile``

    Змінні середовища:
        IDGOV_BASE_URL   — базовий URL (за замовч. ``https://test.id.gov.ua``)
        ICEI_CLIENT_ID   — ідентифікатор прикладної системи
        ICEI_CLIENT_SECRET — секрет прикладної системи
        ICEI_AUTH_TYPE   — тип аутентифікації (``dig_sign`` або ``bank_id``)
    """

    def __init__(
        self,
        redirect_uri: Optional[str] = None,
        decryptor: Callable[[str], dict] | None = None,
    ):
        self.response_type: str = "code"
        self.client_id: Optional[str] = IDGOV_CLIENT_ID
        self.client_secret: Optional[str] = IDGOV_CLIENT_SECRET
        self.auth_type: str = IDGOV_AUTH_TYPE
        self.state: str = uuid.uuid4().hex
        self.redirect_uri: str = redirect_uri or "http://localhost:8000/auth/icei/callback"
        self.base_url: str = IDGOV_BASE_URL.rstrip("/")
        self.decryptor: Callable[[str], dict] | None = decryptor or _load_iit_decryptor()

    def _decrypt_encrypted_user_info(self, encrypted_payload: str) -> dict:
        """Decrypt encryptedUserInfo with external IIT integration."""
        if self.decryptor is None:
            raise ICEIError(
                "get-user-info returned encryptedUserInfo, but IIT decryptor is not configured. "
                "Set IIT_DECRYPTOR_FUNC=module:function"
            )

        try:
            decrypted_data = self.decryptor(encrypted_payload)
        except Exception as exc:
            raise ICEIError(f"IIT decryptor failed: {exc}") from exc

        if not isinstance(decrypted_data, dict):
            raise ICEIError("IIT decryptor must return dict with user attributes")

        return decrypted_data

    # ------------------------------------------------------------------
    # Крок 3  —  URL для перенаправлення користувача
    # ------------------------------------------------------------------

    @property
    def auth_url(self) -> str:
        """Authorization URL для перенаправлення браузера користувача (крок 3).

        Формат:
            GET https://test.id.gov.ua/?response_type=code
                &client_id=...&auth_type=...&state=...&redirect_uri=...
        """
        params = urlencode({
            "response_type": self.response_type,
            "client_id": self.client_id or "",
            "auth_type": self.auth_type,
            "state": self.state,
            "redirect_uri": self.redirect_uri,
        })
        return f"{self.base_url}/?{params}"

    # ------------------------------------------------------------------
    # Кроки 11.1–11.2  —  обмін code на access_token
    # ------------------------------------------------------------------

    async def get_access_token(self, code: str) -> dict:
        """Обмін authorization code на маркер доступу (кроки 11.1–11.2).

        POST https://test.id.gov.ua/get-access-token
            ?grant_type=authorization_code
            &client_id=...&client_secret=...&code=...

        Returns:
            dict з: access_token, token_type, expires_in, refresh_token, user_id

        Raises:
            ICEIError: при HTTP-помилці або error у відповіді
        """
        params = {
            "grant_type": "authorization_code",
            "client_id": self.client_id or "",
            "client_secret": self.client_secret or "",
            "code": code,
        }
        url = f"{self.base_url}/get-access-token"
        _logger.debug("get-access-token → %s", url)

        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                response = await http.post(url, params=params)
        except httpx.RequestError as exc:
            raise ICEIError(f"HTTP request to get-access-token failed: {exc}") from exc

        _logger.debug("get-access-token ← HTTP %s", response.status_code)
        if response.status_code != 200:
            raise ICEIError(
                f"get-access-token returned HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise ICEIError(f"Invalid JSON from get-access-token: {exc}") from exc

        if "error" in data:
            raise ICEIError(
                f"get-access-token error={data['error']}: "
                f"{data.get('error_description', '')}"
            )

        return data

    # ------------------------------------------------------------------
    # Кроки 11.3–11.4  —  отримання даних особи
    # ------------------------------------------------------------------

    async def get_user_info(
        self,
        access_token: str,
        user_id: str,
        fields: Optional[str] = None,
    ) -> dict:
        """Отримання інформації про ідентифікованого користувача (кроки 11.3–11.4).

        POST https://test.id.gov.ua/get-user-info
            ?access_token=...&user_id=...&fields=...&cert=

        Примітка: якщо ``cert`` порожній — сервер повертає незашифрований JSON.
        Якщо потрібне шифрування — передати сертифікат у ``cert`` (BASE64).

        Args:
            access_token: маркер доступу з ``get_access_token``
            user_id: ідентифікатор користувача з ``get_access_token``
            fields: перелік полів через кому (за замовч. ``DEFAULT_FIELDS``)

        Returns:
            dict з полями сертифіката (Таблиця 2.2.6)

        Raises:
            ICEIError: при HTTP-помилці, error у відповіді або encrypted-відповіді
        """
        params = {
            "access_token": access_token,
            "user_id": user_id,
            "fields": fields or DEFAULT_FIELDS,
            "cert": "",  # порожній → незашифрована відповідь
        }
        url = f"{self.base_url}/get-user-info"
        _logger.debug("get-user-info → %s (user_id=%s)", url, user_id)

        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                response = await http.post(url, params=params)
        except httpx.RequestError as exc:
            raise ICEIError(f"HTTP request to get-user-info failed: {exc}") from exc

        _logger.debug("get-user-info ← HTTP %s", response.status_code)
        if response.status_code != 200:
            raise ICEIError(
                f"get-user-info returned HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise ICEIError(f"Invalid JSON from get-user-info: {exc}") from exc

        if "error" in data:
            raise ICEIError(
                f"get-user-info error={data['error']}: "
                f"{data.get('error_description', '')}"
            )

        # Підтримка ДСТУ-шифрування через зовнішній IIT-дешифратор
        if "encryptedUserInfo" in data:
            encrypted_payload: Any = data.get("encryptedUserInfo")
            if not isinstance(encrypted_payload, str) or not encrypted_payload.strip():
                raise ICEIError("get-user-info returned invalid encryptedUserInfo payload")
            return self._decrypt_encrypted_user_info(encrypted_payload)

        return data

    # ------------------------------------------------------------------
    # Крок 3.2 — видалення сесії на сервері ідентифікації
    # ------------------------------------------------------------------

    async def logout(self, access_token: str, user_id: str) -> bool:
        """Видалити сесію користувача на сервері id.gov.ua (крок 3.2).

        Це необхідно робити після успішного отримання персональних даних.
        Запит видаляє дані сесії на стороні провайдера (access_token буде невалідним).

        Запит:
            GET/POST https://test.id.gov.ua/get-user-logout
                ?access_token=...&user_id=...

        Очікувана відповідь при успіху:
            { "error": "0", "error_description": "Дані користувача із ID = user_id видалено успішно" }

        Args:
            access_token: маркер доступу (буде невалідним після цього виклику)
            user_id: ідентифікатор користувача

        Returns:
            True якщо логаут успішний, False якщо помилка (але це не критично)

        Примітка:
            Помилки логауту не викидаються — лишень логуються. Проходження логауту
            не впливає на успіх обробки ідентифікації, оскільки персональні дані
            вже отримані. Логаут — це чистка ресурсів на стороні провайдера.
        """
        if not access_token or not user_id:
            _logger.debug("logout: access_token or user_id missing, skipping")
            return False

        params = {
            "access_token": access_token,
            "user_id": user_id,
        }
        url = f"{self.base_url}/get-user-logout"
        _logger.debug("get-user-logout → %s (user_id=%s)", url, user_id)

        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                response = await http.post(url, params=params)
        except httpx.RequestError as exc:
            _logger.warning("logout: HTTP request failed (non-critical): %s", exc)
            return False

        if response.status_code != 200:
            _logger.warning(
                "logout: HTTP %s (non-critical): %s",
                response.status_code,
                response.text[:100],
            )
            return False

        try:
            data = response.json()
        except Exception as exc:
            _logger.warning("logout: Invalid JSON in response (non-critical): %s", exc)
            return False

        error_code = data.get("error")
        if error_code and error_code != "0":
            error_desc = data.get("error_description", "")
            _logger.warning(
                "logout: server returned error=%s (non-critical): %s",
                error_code,
                error_desc,
            )
            return False

        _logger.info("logout: успішно видалено сесію для user_id=%s", user_id)
        return True

    # ------------------------------------------------------------------
    # Крок 11  —  повний ланцюжок: code → UserProfile
    # ------------------------------------------------------------------

    async def fetch_person(self, code: str) -> UserProfile:
        """Повний ланцюжок ідентифікації (кроки 11.1–11.6).

        Виконує get_access_token → get_user_info та повертає ``UserProfile``.

        Args:
            code: authorization code з callback id.gov.ua (крок 10)

        Returns:
            ``UserProfile`` з даними особи

        Raises:
            ICEIError: при будь-якій помилці на будь-якому кроці
        """
        token_data = await self.get_access_token(code)

        access_token: str = token_data.get("access_token") or ""
        user_id: str = str(token_data.get("user_id") or "")

        if not access_token:
            raise ICEIError("No access_token in get-access-token response")
        if not user_id:
            raise ICEIError("No user_id in get-access-token response")

        _logger.info("ICEI: received access_token for user_id=%s", user_id)

        user_data = await self.get_user_info(access_token, user_id)
        profile = UserProfile.from_dict(user_data)

        _logger.info(
            "ICEI: identified user lastname=%s givenname=%s identifier=%s",
            profile.lastname,
            profile.givenname,
            profile.identifier,
        )

        # Видалити сесію на крок 3.2 (після успішного отримання даних)
        # Помилки логауту не критичні — вже маємо персональні дані
        await self.logout(access_token, user_id)

        # Очистити токени з локальної пам'яті (вони вже невалідні на сервері)
        access_token = ""
        user_id = ""

        return profile
