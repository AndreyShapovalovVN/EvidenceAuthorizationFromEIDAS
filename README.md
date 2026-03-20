# Authorization Service (dark eIDAS demo)

Сервис отображает защищенную страницу авторизации и сохраняет профиль пользователя в Redis.

- Кнопка `Log in via eIDAS` подставляет тестовые данные в форму.
- Кнопка `Continue Securely` отправляет данные в `POST /auth/continue`.
- Backend собирает объект `Person` и сохраняет `person.dict` в Redis по ключу `oots:request:person:{message_id}`.

## Что делает сервис

- Проверяет состояние Redis через `GET /health`.
- При открытии `GET /{message_id}`:
  - читает `oots:message:response:evidence:{message_id}`;
  - если `exception.code == EDM:ERR:0002` возвращает `422`;
  - ожидает флаг `oots:message:request:preview:{message_id}`;
  - если флаг не появился за таймаут, возвращает `408`.
- При `POST /auth/continue` валидирует payload и сохраняет Person в Redis.

## Быстрый запуск локально

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Откройте страницу:

- `http://127.0.0.1:8000/<message_id>`
- пример: `http://127.0.0.1:8000/msg-001`

## Запуск в Docker

```bash
docker build -t authorization-app:local .
docker run --rm -p 8000:8000 \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  authorization-app:local
```

## API

### `GET /health`

Ответ при успехе:

```json
{
  "status": "ok",
  "redis": "up"
}
```

Если Redis недоступен: `503`.

### `GET /{message_id}`

Возвращает HTML страницу авторизации (`templates/login.html`) при успешных проверках Redis.

### `POST /auth/continue`

Пример запроса:

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

Пример успешного ответа:

```json
{
  "status": "ok",
  "message": "Дані збережено",
  "redis_key": "oots:request:person:msg-001",
  "person": {}
}
```

## Redis-ключи

- `oots:message:response:evidence:{message_id}` — входные данные для проверки исключения.
- `oots:message:request:preview:{message_id}` — флаг готовности preview.
- `oots:request:person:{message_id}` — сохраненный `person.dict`.

## Переменные окружения

Используются env-переменные из `lib/UseRedis.py`:

- `REDIS_URL` (по умолчанию `redis://localhost:6379/0`)
- `REDIS_TTL` (по умолчанию `86400`)
- `REDIS_PREFIX` (опционально)

## Kubernetes для DevOps

Пошаговая установка в Kubernetes описана в `docs/kubernetes-install.md`.

## Тести

```bash
pytest -q
```

Точковий запуск:

```bash
pytest tests/test_main_endpoints.py -q
```

