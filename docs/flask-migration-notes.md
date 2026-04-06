# Flask to FastAPI migration notes

## Мета

Відтворити функціонал застарілого `OOTS-evidence-viewer` (Flask) в цьому FastAPI-сервісі та повністю відмовитись від Flask.

## Ітерація 1 (✅ виконано)

- Додано спільний рендерер для сторінки авторизації в `main.py`.
- Додано перевірку EDM:ERR:0002 як успішного маркера в `lib/MessageChecker.py`.
- Маршрут `/auth/{message_id}` замінює Flask `/auth`.

## Ітерація 2 (✅ виконано)

- Реалізовано `GET /preview/{message_id}` — паритет з Flask `/view/{message_id}`.
- Реалізовано `POST /preview/continue` — збереження підтверджень evidence.
- Реалізовано `GET /preview/progress/{message_id}` — API поллінгу прогресу.
- Реалізовано `POST /preview/timeout/{message_id}` — фіксація таймауту в Redis.
- Шаблони `view_waiting.html`, `pdf.html`, `xml.html` переведені на базові стилі з `static/base.css`.
- Додано контрактні тести для всіх `/preview/*` сценаріїв.

## Контракт (виконано)

- ✅ Маршрути та методи (`/auth`, `/preview`, `/preview/continue`, `/preview/progress`, `/preview/timeout`).
- ✅ Коди статусів: `200`, `400`, `408`, `422`, `503`.
- ✅ Поведінка при таймауті: запис `EDM:ERR:0005` у Redis + редирект по `returnurl`.
- ✅ Redis-ключі централізовані в `redis_keys.py` (спільний файл для всіх компонентів).
- ✅ Шаблони розділяють загальні стилі через `static/base.css`.

## Стан міграції

Flask повністю замінено FastAPI. Підтримка Flask-кодової бази більше не ведеться.
