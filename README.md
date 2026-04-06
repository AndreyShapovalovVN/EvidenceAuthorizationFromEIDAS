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

1. читається ключ `oots:message:response:evidence:{message_id}`;
2. якщо знайдено `exception.code == EDM:ERR:0002` — це **успішний** сценарій, рендер продовжується;
3. якщо знайдено будь-який **інший** `exception.code` — повертається `422`;
4. якщо exception відсутній — очікується поява прапора `oots:message:request:preview:{message_id}`;
5. якщо прапор не з'явився за таймаут — повертається `408`;
6. якщо перевірки пройдено — повертається HTML-сторінка `login.html`.

Після успішного заповнення форми браузер переходить на `/preview/{message_id}?returnurl=...`.

---

### `POST /auth/continue`

Приймає дані форми авторизації, збирає об'єкт `Person`, зберігає його в Redis і ставить `message_id` у чергу обробки (з EDM payload `process_queue`).

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

### `GET /preview/{message_id}?returnurl=<URL>`

Сторінка очікування та перегляду evidence.

- Параметр `returnurl` є обов'язковим; без нього повертається `400`.
- Якщо evidence вже готовий у Redis — одразу рендерить PDF або XML сторінку.
- Інакше — показує сторінку очікування `view_waiting.html` з двоетапним таскбаром.
- Клієнт поллінгує `/preview/progress/{message_id}` і при готовності оновлює сторінку.

---

### `GET /preview/progress/{message_id}`

JSON API для поллінгу прогресу.

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
| `WAIT_EVENT_TIME` | `120` | Максимальний час очікування evidence на сторінці (секунди) |
| `WAIT_EVENT_SLEEP` | `5` | Інтервал поллінгу прогресу (секунди) |
| `QUEUE_OUTGOING` | `oots:queue:outgoing` | Назва Redis-черги для таймаут-записів |
| `PREVIEW_URL` | _(не задано)_ | Базовий URL preview-сервісу (для `RedirectService`) |

Приклад `.env`:

```dotenv
REDIS_URL=redis://localhost:6379/0
REDIS_TTL=86400
REDIS_PREFIX=
WAIT_EVENT_TIME=120
WAIT_EVENT_SLEEP=5
QUEUE_OUTGOING=oots:queue:outgoing
PREVIEW_URL=http://localhost:8081/preview
```

## Локальний запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a
source .env
set +a
uvicorn main:app --reload
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
PYTHONPATH=. pytest -q
```

Точковий запуск:

```bash
PYTHONPATH=. pytest tests/test_main_view_endpoints.py -q
PYTHONPATH=. pytest tests/test_message_checker.py -q
PYTHONPATH=. pytest tests/test_redirect_service.py -q
PYTHONPATH=. pytest tests/test_person_request_service.py -q
```

Перевірка типів:

```bash
python3 -m mypy --config-file mypy.ini
```

## Документація для DevOps

Інструкція з деплою в Kubernetes описана в `docs/kubernetes-install.md`.

Короткий технічний огляд сервісу доступний у `docs/service-overview.md`.
