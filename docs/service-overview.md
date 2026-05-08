# Огляд сервісу авторизації

## Призначення

Сервіс надає захищену веб-сторінку авторизації, перевіряє службові дані в Redis і зберігає профіль користувача у форматі `Person` для подальшої обробки іншими компонентами системи. Після авторизації перенаправляє користувача на сторінку перегляду evidence (`/preview`).

## Сценарії авторизації

### Базовий сценарій (`GET /auth/{message_id}`)

1. Клієнт відкриває `GET /auth/{message_id}`.
2. Сервіс перевіряє наявність `oots:message:request:edm:{message_id}`.
3. Якщо EDM відсутній:
   - при наявному `returnurl` рендериться `invalid_link.html` і виконується автоповернення на `returnurl`;
   - без `returnurl` повертається `400` (`Invalid link: EDM not found and no returnurl provided`).
4. Якщо EDM наявний, сервіс перевіряє `oots:message:request:person:{message_id}`.
5. Якщо `Person` вже є, рендериться `redirect_to_preview.html` і користувач автоматично переходить на `/preview/{message_id}`.
6. Якщо `Person` відсутній, рендериться `login.html` (після `check_message(...)`), а форма відправляється на `POST /auth/continue`.

### Одноразова авторизація в межах `message_id`

- Перша авторизація зберігає `Person` у `oots:message:request:person:{message_id}`.
- Повторне відкриття `/auth/{message_id}` для того самого `message_id` не показує форму повторно і одразу переводить на `/preview/{message_id}`.

### Бізнес-помилки/таймаут у `check_message(...)`

- Якщо знайдено business error від evidence — повертається `422`.
- Якщо спрацьовує таймаут очікування preview — повертається `408`.

## Сторінка перегляду evidence (/preview)

1. `GET /preview/{message_id}` — якщо evidence вже готовий у Redis, рендерить його; інакше повертає `view_waiting.html`.
2. `view_waiting.html` поллінгує `GET /preview/progress/{message_id}` кожні `WAIT_EVENT_SLEEP` секунд (із `X-Action-Token`, action=`preview-progress`).
3. При `stage=2` браузер оновлює сторінку — отримуємо рендер evidence (PDF або XML).
4. При таймауті браузер викликає `POST /preview/timeout/{message_id}` з `X-Action-Token` (action=`preview-timeout`), який фіксує `EDM:ERR:0005` у Redis і ставить `message_id` у чергу `QUEUE_OUTGOING`, після чого перенаправляє по `returnurl`.
5. Після перегляду користувач підтверджує документи через `POST /preview/continue` з `X-Action-Token` (action=`preview-continue`).

Поточний flow `view_evidence` / `continue_view` / `view_timeout` лишається без змін у бізнес-частині.

## Маршрути

| Метод | Шлях | Призначення |
|-------|------|-------------|
| `GET` | `/health` | Перевірка Redis та застосунку |
| `GET` | `/auth/{message_id}` | Сторінка авторизації |
| `POST` | `/auth/continue` | Збереження Person, постановка в чергу |
| `GET` | `/preview/{message_id}` | Сторінка перегляду/очікування evidence |
| `GET` | `/preview/progress/{message_id}` | API поллінгу прогресу |
| `POST` | `/preview/continue` | Збереження підтверджень evidence |
| `POST` | `/preview/timeout/{message_id}` | Фіксація таймауту в Redis |

## Залежності

- FastAPI — HTTP API і шаблони;
- Jinja2 — рендеринг HTML;
- Redis — зберігання службових даних і стану сценарію;
- `pyRegRep4` — парсинг EDM payload;
- `lxml` — XML-модель для `Person`.

## Redis-ключі

Усі ключі визначені в `redis_keys.py` (клас `Keys`), спільному для всіх компонентів:

| Ключ | Опис |
|------|------|
| `oots:message:response:evidence:{id}` | Відповідь сервісу з можливою помилкою |
| `oots:message:request:preview:{id}` | Прапор готовності preview |
| `oots:message:request:edm:{id}` | EDM payload (content, process_queue) |
| `oots:message:request:person:{id}` | Збережений Person.dict |
| `oots:message:request:permit:{id}` | Прапор дозволу після підтвердження |
| `oots:message:request:as4:{id}` | AS4 payload |
| `oots:message:response:edm:{id}` | EDM response |
| `oots:message:response:exp:{id}` | Запис таймауту/помилки перегляду (EDM:ERR:0005) |
| `oots:evidencetype:{evidence_type_id}` | Тип evidence |

## Змінні середовища

| Змінна | Типове значення | Опис |
|--------|-----------------|------|
| `REDIS_URL` | `redis://localhost:6379` | URL підключення до Redis |
| `REDIS_TTL` | `86400` | TTL для даних у Redis (секунди) |
| `REDIS_PREFIX` | _(порожній)_ | Префікс для всіх Redis-ключів |
| `EVIDENCE_TIMEOUT` | `600` | Час очікування evidence на сторінці (секунди) |
| `WAIT_EVENT_SLEEP` | `5` | Інтервал поллінгу прогресу (секунди) |
| `QUEUE_OUTGOING` | `oots:queue:outgoing` | Redis-черга для таймаут-записів |
| `PREVIEW_URL` | _(не задано)_ | Базовий URL preview-сервісу (RedirectService) |
| `RETURNURL_REGEX` | `.*` | Regex-фільтр для `returnurl` перед використанням |
| `ACTION_TOKEN_SECRET` | `dev-action-secret` | Master secret для derivation ключа підпису action-токенів |
| `ACTION_TOKEN_KEY_SALT` | `action-token-v2` | Salt для derivation dynamic signing key (`message_id` + `action`) |
| `ACTION_TOKEN_TTL` | `900` | TTL action-токена (секунди) |

Action token-и використовують dynamic signing key, прив'язаний до `message_id` та `action`; legacy signatures не підтримуються.

## Внутрішні модулі

- `redis_keys.py` — централізоване визначення всіх Redis-ключів;
- `lib/UseRedis.py` — асинхронний Redis-клієнт, Singleton, префіксація ключів;
- `lib/MessageChecker.py` — перевірка evidence-помилки та поллінг preview-прапора;
- `lib/RedirectService.py` — обчислення цільового URL на основі EDM `PossibilityForPreview`;
- `lib/PersonRequestService.py` — побудова Person payload і постановка в чергу Redis.

## Нефункціональні особливості

- сервіс повертає security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) на всі відповіді;
- `GET /health` вважається успішним лише за доступного Redis;
- Redis-підключення ініціалізується на старті застосунку і закривається на shutdown (lifespan);
- сторінка очікування (`view_waiting.html`) фіксує таймаут у Redis через REST API перед редиректом;
- всі стилі зібрані в `static/base.css` і підключаються через `<link>` у кожному шаблоні.
