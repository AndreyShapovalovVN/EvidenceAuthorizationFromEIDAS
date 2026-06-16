# Authorization Service

Сервіс відображає захищену сторінку авторизації, перевіряє службові дані в Redis і зберігає профіль користувача у форматі `Person`. Після авторизації перенаправляє на сторінку перегляду evidence (`/preview`).

## Основні можливості

- темна сторінка авторизації з шаблону `templates/login.html`;
- кнопка `Log in via eIDAS`, яка заповнює демо-дані у форму;
- перевірка Redis перед рендерингом сторінки авторизації;
- збереження `Person` у Redis за ключем `oots:message:request:person:{message_id}`;
- постановка `message_id` у Redis-чергу `process_queue` з EDM payload;
- сторінка очікування (`/preview`) з двоетапним таскбаром;
- API поллінгу прогресу завантаження evidence;
- фіксація таймауту в Redis при спливанні часу;
- рендер PDF та XML evidence після завантаження.

## Структура сервісу

- `main.py` — FastAPI-застосунок, HTTP-маршрути, lifecycle і security headers;
- `redis_keys.py` — клас `Keys` з усіма шаблонами Redis-ключів (спільний для всіх компонентів);
- `lib/MessageChecker.py` — перевірка evidence-помилки та очікування preview-прапора;
- `lib/RedirectService.py` — визначення URL, куди йти після авторизації (EDM `PossibilityForPreview`);
- `lib/PersonRequestService.py` — валідація payload і збереження `Person` у Redis;
- `lib/UseRedis.py` — асинхронний Redis-клієнт, утиліти доступу та префіксація ключів;
- `templates/login.html` — UI сторінки авторизації;
- `templates/redirect_to_preview.html` — авто-перехід на preview, якщо авторизація вже виконана;
- `templates/invalid_link.html` — повідомлення про невалідне посилання з поверненням на `returnurl`;
- `templates/view_waiting.html` — сторінка очікування завантаження evidence;
- `templates/pdf.html` — перегляд PDF evidence;
- `templates/xml.html` — перегляд XML evidence;
- `static/base.css` — спільні стилі для всіх сторінок;
- `docs/kubernetes-install.md` — інструкція для DevOps з деплою в Kubernetes;
- `docs/service-overview.md` — короткий технічний огляд сервісу;
- `docs/flask-migration-notes.md` — нотатки про міграцію з Flask.

## HTTP API

### `GET /health`

Перевіряє доступність сервісу та Redis.

Успішна відповідь:

```json
{
  "status": "ok",
  "redis": "up"
}
```

Якщо Redis недоступний — `503`.

---

### `GET /auth/{message_id}`

Основний маршрут для відкриття сторінки авторизації.

Перед рендерингом:

1. читається ключ `oots:message:request:edm:{message_id}`;
2. якщо EDM відсутній:
   - при наявному `returnurl` рендериться `invalid_link.html` з повідомленням і автоповерненням;
   - без `returnurl` повертається `400` (`Invalid link: EDM not found and no returnurl provided`);
3. якщо EDM є, читається `oots:message:request:person:{message_id}`;
4. якщо `Person` уже збережений, рендериться `redirect_to_preview.html` і користувач одразу переходить на `/preview/{message_id}`;
5. якщо `Person` відсутній:
   - зберігається `returnurl` (після фільтра `RETURNURL_REGEX`),
   - виконується перевірка `check_message(...)`,
   - можливі `422` (EDM business error) або `408` (таймаут preview),
   - інакше рендериться `login.html`.

Після успішного заповнення форми браузер переходить на URL із `continue_url` (зазвичай `/preview/{message_id}`).

---

### `POST /auth/continue`

Приймає дані форми авторизації, збирає об'єкт `Person`, зберігає його в Redis і ставить `message_id` у чергу обробки (з EDM payload `process_queue`).

Потребує заголовок `X-Action-Token` (action=`auth-continue`).

Приклад запиту:

```json
{
  "first_name": "Andrii",
  "last_name": "Kovalenko",
  "date_of_birth": "1992-04-18",
  "identifier": "UA/UA/3124509876",
  "message_id": "msg-001",
  "level_of_assurance": "High"
}
```

Приклад успішної відповіді:

```json
{
  "status": "ok",
  "message": "Дані збережено",
  "redis_key": "oots:message:request:person:msg-001",
  "person": {}
}
```

---

### `GET /preview/{message_id}`

Сторінка очікування та перегляду evidence.

- `returnurl` береться в такому пріоритеті: Redis (`RETURN_URL`) -> query param `returnurl` -> `resolve_url(...)` з EDM.
- Якщо знайдений `returnurl` проходить `RETURNURL_REGEX`, він зберігається в Redis.
- Якщо evidence вже готовий у Redis — одразу рендерить PDF або XML сторінку.
- Інакше — показує сторінку очікування `view_waiting.html` з двоетапним таскбаром.
- Клієнт поллінгує `/preview/progress/{message_id}`; при готовності переходить на preview-сторінку.

---

### `GET /preview/progress/{message_id}`

JSON API для поллінгу прогресу.

Потребує заголовок `X-Action-Token` (action=`preview-progress`).

Відповідь:

```json
{
  "message_id": "msg-001",
  "stage": 1,
  "preview_ready": true,
  "evidence_ready": false
}
```

- `stage=0` — нічого не готово;
- `stage=1` — прапор preview з'явився;
- `stage=2` — evidence завантажено, можна рендерити.

---

### `POST /preview/continue`

Зберігає підтвердження (approvals) для evidence-документів.

Потребує заголовок `X-Action-Token` (action=`preview-continue`).

Приклад запиту:

```json
{
  "message_uuid": "msg-001",
  "approvals": {"doc-1": true, "doc-2": false}
}
```

---

### `POST /preview/timeout/{message_id}`

Фіксує таймаут очікування в Redis (викликається браузером при спливанні часу) і ставить `message_id` в чергу `QUEUE_OUTGOING`.

Потребує заголовок `X-Action-Token` (action=`preview-timeout`).

Записує в `oots:message:response:exp:{message_id}`:

```json
{
  "exception": {
    "code": "EDM:ERR:0005",
    "message": "View timeout for message_id=...",
    "detail": "View timeout for message_id=..."
  }
}
```

---

## Redis-ключі

Усі ключі визначені в `redis_keys.py` (клас `Keys`):

| Ключ | Призначення |
|------|-------------|
| `oots:message:response:evidence:{id}` | Відповідь з evidence та можлива помилка |
| `oots:message:request:preview:{id}` | Прапор готовності preview |
| `oots:message:request:edm:{id}` | EDM payload з `content`/`content2`, `process_queue` |
| `oots:message:request:person:{id}` | Збережений `Person.dict` |
| `oots:message:request:permit:{id}` | Прапор дозволу після підтвердження evidence |
| `oots:message:request:as4:{id}` | AS4 payload |
| `oots:message:response:edm:{id}` | EDM response |
| `oots:message:response:exp:{id}` | Запис таймауту/помилки перегляду |
| `oots:evidencetype:{evidence_type_id}` | Тип evidence |

Усі ключі підтримують опціональний префікс через змінну `REDIS_PREFIX`.

## Змінні середовища

| Змінна | Типове значення | Опис |
|--------|-----------------|------|
| `REDIS_URL` | `redis://localhost:6379` | URL підключення до Redis |
| `REDIS_TTL` | `86400` | TTL для JSON-даних у Redis (секунди) |
| `REDIS_PREFIX` | _(порожній)_ | Необов'язковий префікс для всіх Redis-ключів |
| `EVIDENCE_TIMEOUT` | `600` | Максимальний час очікування evidence/preview (секунди) |
| `WAIT_EVENT_SLEEP` | `5` | Інтервал поллінгу прогресу (секунди) |
| `QUEUE_OUTGOING` | `oots:queue:outgoing` | Назва Redis-черги для таймаут-записів |
| `PREVIEW_URL` | _(не задано)_ | Базовий URL preview-сервісу (для `RedirectService`) |
| `RETURNURL_REGEX` | `.*` | Regex-фільтр для `returnurl` перед збереженням/використанням |
| `ACTION_TOKEN_SECRET` | `dev-action-secret` | Master secret для HMAC; використовується для derivation dynamic signing key |
| `ACTION_TOKEN_KEY_SALT` | `action-token-v2` | Salt для derivation ключа підпису, прив'язаного до `message_id` + `action` |
| `ACTION_TOKEN_TTL` | `900` | TTL action-токена у секундах |

### Security-конфігурація (dev/test/prod)

`returnurl` у цьому сервісі фільтрується через `RETURNURL_REGEX`, а state-changing endpoint-и захищені підписаними action-токенами.
Підпис токена формується dynamic key, похідним від `message_id` та `action`; legacy-підписи не підтримуються.

Рекомендовані значення:

| Середовище | `RETURNURL_REGEX` | `ACTION_TOKEN_SECRET` | `ACTION_TOKEN_TTL` |
|---|---|---|---|
| dev | `.*` | `dev-action-secret` | `900` |
| test | `^https://(oots-portal\\.oots-test\\.k8s|portal\\.example\\.test)/.*$` | довгий випадковий secret | `600` |
| prod | `^https://(oots-portal\\.gov\\.example|portal\\.gov\\.example)/.*$` | довгий випадковий secret (з vault/secret manager) | `300-600` |

Мінімальні вимоги для `test/prod`:

- не використовувати `RETURNURL_REGEX=.*`;
- не використовувати дефолтний `ACTION_TOKEN_SECRET`;
- періодично ротувати `ACTION_TOKEN_SECRET`.

Приклад `.env`:

```dotenv
REDIS_URL=redis://localhost:6379/0
REDIS_TTL=86400
REDIS_PREFIX=
EVIDENCE_TIMEOUT=600
WAIT_EVENT_SLEEP=5
QUEUE_OUTGOING=oots:queue:outgoing
PREVIEW_URL=http://localhost:8081/preview
RETURNURL_REGEX=.*
ACTION_TOKEN_SECRET=dev-action-secret
ACTION_TOKEN_TTL=900
STATIC_VERSION=dev-1
```

`STATIC_VERSION` додається до URL статичних ресурсів (`/static/...?...v=...`) і дозволяє швидко скидати кеш браузера після змін у JS/CSS. Після UI-змін достатньо оновити значення в `.env` і перезапустити сервіс.

## Локальний запуск

```bash
uv sync --group dev
set -a
source .env
set +a
uv run uvicorn main:app --reload
```

Після запуску:

- `http://127.0.0.1:8000/auth/msg-001`
- `http://127.0.0.1:8000/preview/msg-001?returnurl=https://example.com`

## Запуск у Docker

```bash
docker build -t authorization-app:local .
docker run --rm -p 8000:8000 --env-file .env authorization-app:local
```

> На Linux `host.docker.internal` може бути недоступним без додаткової конфігурації Docker. Якщо Redis працює локально, вкажіть фактичну IP-адресу хоста або використайте окрему docker network.

## Перевірка якості

Запуск усіх тестів:

```bash
uv run pytest -q
```

Точковий запуск:

```bash
uv run pytest tests/test_main_view_endpoints.py -q
uv run pytest tests/test_message_checker.py -q
uv run pytest tests/test_redirect_service.py -q
uv run pytest tests/test_person_request_service.py -q
```

Перевірка типів:

```bash
uv run mypy --config-file pyproject.toml
```

## Документація для DevOps

Інструкція з деплою в Kubernetes описана в `docs/kubernetes-install.md`.

Короткий технічний огляд сервісу доступний у `docs/service-overview.md`.
