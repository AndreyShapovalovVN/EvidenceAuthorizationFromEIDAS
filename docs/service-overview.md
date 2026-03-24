# Огляд сервісу авторизації

## Призначення

Сервіс надає веб-сторінку авторизації, перевіряє службові дані в Redis і зберігає профіль користувача у форматі `Person` для подальшої обробки іншими компонентами системи.

## Основний сценарій

1. Клієнт відкриває `GET /auth/{message_id}` або сумісний alias `GET /{message_id}`.
2. Сервіс читає Redis-ключ `oots:message:response:evidence:{message_id}`.
3. Якщо знайдено `exception.code == EDM:ERR:0002`, це вважається успішним сценарієм.
4. Якщо знайдено будь-який інший `exception.code`, сервіс повертає `422`.
5. Якщо exception немає, сервіс очікує прапор `oots:message:request:preview:{message_id}`.
6. Після успішної перевірки рендериться сторінка `login.html`.
7. Користувач натискає `Continue Securely`, а браузер надсилає `POST /auth/continue`.
8. Сервіс збирає `Person`, зберігає його в Redis і додає `message_id` в Redis-чергу, задану полем `process_queue` в EDM payload.

## Залежності

- FastAPI — HTTP API і шаблони;
- Jinja2 — рендеринг HTML;
- Redis — зберігання службових даних і стану сценарію;
- `pyRegRep4` — парсинг EDM payload;
- `lxml` — XML-модель для `Person`.

## Важливі Redis-ключі

- `oots:message:response:evidence:{message_id}`
- `oots:message:request:preview:{message_id}`
- `oots:message:request:edm:{message_id}`
- `oots:message:request:person:{message_id}`

## Внутрішні модулі

- `lib/UseRedis.py` — асинхронний Redis-клієнт і префіксація ключів;
- `lib/MessageChecker.py` — передрендерні перевірки;
- `lib/RedirectService.py` — обчислення цільового URL після авторизації;
- `lib/PersonRequestService.py` — побудова payload для Redis і постановка в чергу.

## Нефункціональні особливості

- сервіс повертає security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`);
- перевірка `/health` вважається успішною лише за доступного Redis;
- Redis-підключення ініціалізується на старті застосунку і закривається на shutdown.

