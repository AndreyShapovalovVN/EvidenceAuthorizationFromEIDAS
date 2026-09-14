# Authorization Service

Версія **1.10.0**. Python **3.12+**; CI використовує Python **3.12**.

Сервіс відображає захищену сторінку авторизації, перевіряє службові дані в Redis і зберігає профіль користувача у форматі `Person`. Після авторизації перенаправляє на сторінку перегляду evidence (`/preview`).

## Основні можливості

- темна сторінка авторизації з шаблону `templates/login.html`;
- кнопка `Log in via eIDAS`, яка запускає реальний eIDAS Simple Protocol flow через Specific Connector;
- перевірка Redis перед рендерингом сторінки авторизації;
- збереження `Person` у Redis за ключем `oots:message:request:person:{message_id}`;
- постановка `message_id` у Redis-чергу `process_queue` з EDM payload;
- сторінка очікування (`/preview`) з двоетапним таскбаром;
- API поллінгу прогресу завантаження evidence;
- фіксація таймауту в Redis при спливанні часу;
- рендер PDF та XML evidence після завантаження.

## Структура сервісу

- `main.py` — FastAPI-застосунок, HTTP-маршрути, lifecycle і security headers;
- `oots_lib.redis_keys` — спільний клас `Keys`; `lib/preview_keys.py` розширює його ключами preview, eIDAS та ICEI;
- `lib/MessageChecker.py` — перевірка evidence-помилки та очікування preview-прапора;
- `lib/RedirectService.py` — визначення URL, куди йти після авторизації (EDM `PossibilityForPreview`);
- `lib/PersonRequestService.py` — валідація payload і збереження `Person` у Redis;
- `oots_lib.lib.UseRedis` — асинхронний Redis-клієнт, утиліти доступу та префіксація ключів;
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

## Ідентифікація eIDAS та ICEI

- `GET /auth/eidas/start/{message_id}` запускає eIDAS Simple Protocol flow.
- `POST /auth/eidas/callback` обробляє відповідь Specific Connector.
- `GET /auth/icei/start/{message_id}` перенаправляє до id.gov.ua; `message_id` має бути UUID.
- `GET /auth/icei/callback` обмінює код авторизації на профіль користувача.

Для ICEI задайте `ICEI_CLIENT_ID`, `ICEI_CLIENT_SECRET` і `ICEI_REDIRECT_URI`
(типово `http://localhost:8000/auth/icei/callback`). `IDGOV_BASE_URL` визначає
сервер провайдера. Для зашифрованих відповідей потрібен зовнішній дешифратор,
налаштований через `IIT_DECRYPTOR_FUNC=module:function`.

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

Приймає дані форми авторизації, збирає об'єкт `Person` і зберігає його в Redis.

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

Перший виклик також читає EDM payload, бере `process_queue` і ставить `message_id` у чергу лише один раз.

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

Фіксує таймаут очікування в Redis (викликається браузером при спливанні часу) і ставить `message_id` в чергу `QUEUE_OUTCOMING`.

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

Спільні ключі визначені в `oots_lib.redis_keys.Keys`, додаткові — у `lib/preview_keys.py` (`PreviewKeys`):

| Ключ | Призначення |
|------|-------------|
| `oots:message:response:evidence:{id}` | Відповідь з evidence та можлива помилка |
| `oots:message:request:preview:{id}` | Прапор готовності preview |
| `oots:message:request:edm:{id}` | EDM payload з `content`/`content2`, `process_queue` |
| `oots:message:request:person:{id}` | Збережений `Person.dict` |
| `oots:preview:process_queue_dispatched:{id}` | Маркер одноразової постановки в process_queue |
| `oots:message:request:permit:{id}` | Прапор дозволу після підтвердження evidence |
| `oots:message:request:as4:{id}` | AS4 payload |
| `oots:message:response:edm:{id}` | EDM response |
| `oots:message:response:exp:{id}` | Запис таймауту/помилки перегляду |
| `oots:evidencetype:{evidence_type_id}` | Тип evidence |

Усі ключі підтримують опціональний префікс через змінну `REDIS_PREFIX`.

## Змінні середовища

| Змінна | Типове значення | Опис |
|--------|-----------------|------|
| `REDIS_URL` | `redis://localhost:6379/0` | URL підключення до Redis |
| `REDIS_TTL` | `3600` | TTL для JSON-даних у Redis (секунди) |
| `REDIS_PREFIX` | _(порожній)_ | Необов'язковий префікс для всіх Redis-ключів |
| `EVIDENCE_TIMEOUT` | `600` | Максимальний час очікування evidence/preview (секунди) |
| `REDIS_TIMEOUT` | `6` | Половина цього значення задає інтервал поллінгу прогресу (секунди) |
| `QUEUE_OUTCOMING` | _(обов’язково задати)_ | Назва Redis-черги для таймаут-записів |
| `PREVIEW_URL` | _(не задано)_ | Базовий URL preview-сервісу (для `RedirectService`) |
| `RETURNURL_REGEX` | `.*` | Regex-фільтр для `returnurl` перед збереженням/використанням |
| `ACTION_TOKEN_SECRET` | `dev-action-secret` | Master secret для HMAC; використовується для derivation dynamic signing key |
| `ACTION_TOKEN_KEY_SALT` | `action-token-v2` | Salt для derivation ключа підпису, прив'язаного до `message_id` + `action` |
| `ACTION_TOKEN_TTL` | `900` | TTL action-токена у секундах |
| `EIDAS_SPECIFIC_CONNECTOR_URL` | `https://connector.eidas.k8s/SpecificConnector/ServiceProvider` | URL Specific Connector для відправки `SMSSPRequest` |
| `EIDAS_SP_PUBLIC_BASE_URL` | _(не задано)_ | Публічний base URL цього сервісу для формування callback `.../auth/eidas/callback` |
| `EIDAS_SP_CALLBACK_URL` | _(не задано)_ | Явний callback URL; має пріоритет над `EIDAS_SP_PUBLIC_BASE_URL` |
| `EIDAS_SP_PROVIDER_NAME` | `DEMO-SP-CA` | Provider name у `authentication_request` |
| `EIDAS_SP_REQUESTER_ID` | `https://eidas.example.org/RequesterId_CA` | Requester ID у `authentication_request` |
| `EIDAS_SP_CITIZEN_COUNTRY` | `CA` | Країна громадянства для eIDAS запиту |
| `EIDAS_SP_LEVEL_OF_ASSURANCE` / `EIDAS_SP_LOA` | `A` | Requested LoA |
| `EIDAS_SP_TYPE` | `public` | Тип SP (`public` або `private`) |
| `EIDAS_SP_ID_POLICY` | `unspecified` | NameID policy |

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
REDIS_TIMEOUT=6
QUEUE_OUTCOMING=oots:queue:outgoing
PREVIEW_URL=http://localhost:8081/preview
RETURNURL_REGEX=.*
ACTION_TOKEN_SECRET=dev-action-secret
ACTION_TOKEN_TTL=900
STATIC_VERSION=1.10.0
COUNTRY=UA
ICEI_CLIENT_ID=replace-with-client-id
ICEI_CLIENT_SECRET=replace-with-client-secret
```

`STATIC_VERSION` додається до URL статичних ресурсів (`/static/...?...v=...`) і дозволяє швидко скидати кеш браузера після змін у JS/CSS. Після UI-змін достатньо оновити значення в `.env` і перезапустити сервіс.

## Локальний запуск

```bash
uv sync --frozen --no-build --no-install-project --extra dev
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

## Залежності та перевірки CI

`pyproject.toml` містить прямі залежності сервісу: FastAPI, Uvicorn, Jinja2,
Redis, lxml, pyregrep, HTTPX, python-multipart, Pydantic та oots-lib.
`pytest`, `mypy` та `ruff` встановлюються через extra `dev`.
Точні версії прямих і транзитивних залежностей зафіксовані в `uv.lock`.
Після зміни залежностей виконайте `uv lock` і збережіть обидва файли.

Локальне відтворення Python Code Quality з `.github/workflows/ci-security-quality.yml`:

```bash
uv sync --python 3.12 --frozen --no-build --no-install-project --extra dev
uv run --no-sync ruff check . --extend-exclude 'tests/~*.py'
uv run --no-sync mypy . --ignore-missing-imports --pretty --show-error-codes
uv run --no-sync pytest --maxfail=2 --disable-warnings --ignore-glob='tests/~*.py'
```

Тести використовують підмінений Redis; зовнішні Redis/eIDAS/ICEI сервіси для них не потрібні.
CI також запускає Gitleaks для пошуку секретів в історії Git і Trivy для сканування
файлової системи на виправлювані вразливості рівнів HIGH та CRITICAL.
Docker build/push виконується окремим workflow для `main` і опублікованих релізів.

## Документація для DevOps

Інструкція з деплою в Kubernetes описана в `docs/kubernetes-install.md`.

Короткий технічний огляд сервісу доступний у `docs/service-overview.md`.
