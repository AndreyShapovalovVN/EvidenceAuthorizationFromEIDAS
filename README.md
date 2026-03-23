# Authorization Service

Сервіс відображає захищену сторінку авторизації, перевіряє службові дані в Redis і зберігає профіль користувача у форматі `Person`.

## Основні можливості

- темна сторінка авторизації з шаблону `templates/login.html`;
- кнопка `Log in via eIDAS`, яка заповнює демо-дані у форму;
- перевірка Redis перед рендерингом сторінки;
- збереження `Person` у Redis за ключем `oots:request:person:{message_id}`;
- постановка `message_id` у Redis-чергу на подальшу обробку.

## Структура сервісу

- `main.py` — FastAPI-застосунок, HTTP-маршрути, lifecycle і security headers;
- `lib/MessageChecker.py` — перевірка evidence-помилки та очікування preview-прапора;
- `lib/RedirectService.py` — визначення URL, куди йти після авторизації;
- `lib/PersonRequestService.py` — валідація payload і збереження `Person` у Redis;
- `lib/UseRedis.py` — асинхронний Redis-клієнт і утиліти доступу до Redis;
- `templates/login.html` — UI сторінки авторизації;
- `docs/kubernetes-install.md` — інструкція для DevOps з деплою в Kubernetes.

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

Якщо Redis недоступний, endpoint повертає `503`.

### `GET /auth/{message_id}`

Основний маршрут для відкриття сторінки авторизації.

Перед рендерингом:

1. читається ключ `oots:message:response:evidence:{message_id}`;
2. якщо знайдено `exception.code == EDM:ERR:0002`, повертається `422`;
3. очікується поява прапора `oots:message:request:preview:{message_id}`;
4. якщо прапор не з'явився за таймаут, повертається `408`;
5. якщо перевірки пройдено, повертається HTML-сторінка `login.html`.

### `GET /{message_id}`

Сумісний alias для того самого сценарію, що й `GET /auth/{message_id}`.

### `POST /auth/continue`

Приймає дані форми, збирає об'єкт `Person`, зберігає його в Redis і ставить `message_id` у чергу обробки.

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
  "redis_key": "oots:request:person:msg-001",
  "person": {}
}
```

## Redis-ключі

- `oots:message:response:evidence:{message_id}` — дані перевірки evidence-помилки;
- `oots:message:request:preview:{message_id}` — прапор готовності preview;
- `oots:message:request:edm:{message_id}` — EDM-дані з `content`/`content2` та `process_queue`;
- `oots:request:person:{message_id}` — збережений `person.dict`;
- `process_queue` з EDM payload — Redis list для постановки `message_id` в обробку.

## Змінні середовища

- `REDIS_URL` — URL підключення до Redis, за замовчуванням `redis://localhost:6379`;
- `REDIS_TTL` — TTL для JSON-даних у Redis (секунди), за замовчуванням `86400`;
- `REDIS_PREFIX` — необов'язковий префікс для всіх Redis-ключів;
- `PREVIEW_URL` — базовий URL preview-сервісу для формування continue/preview-посилань.

У репозиторій додано файл `.env` з прикладом значень:

```dotenv
REDIS_URL=redis://localhost:6379/0
REDIS_TTL=86400
REDIS_PREFIX=
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

Після запуску можна відкрити, наприклад:

- `http://127.0.0.1:8000/auth/msg-001`
- `http://127.0.0.1:8000/msg-001`

## Запуск у Docker

```bash
docker build -t authorization-app:local .
docker run --rm -p 8000:8000 --env-file .env authorization-app:local
```

> На Linux `host.docker.internal` може бути недоступним без додаткової конфігурації Docker. Якщо Redis працює локально, за потреби вкажіть фактичну IP-адресу хоста або використайте окрему docker network.

## Перевірка якості

Запуск усіх тестів:

```bash
PYTHONPATH=. pytest -q
```

Точковий запуск:

```bash
PYTHONPATH=. pytest tests/test_main_endpoints.py -q
PYTHONPATH=. pytest tests/test_redirect_service.py -q
```

Перевірка типів:

```bash
python3 -m mypy --config-file mypy.ini
```

## Документація для DevOps

Інструкція з деплою в Kubernetes описана в `docs/kubernetes-install.md`.

Короткий технічний огляд сервісу доступний у `docs/service-overview.md`.

