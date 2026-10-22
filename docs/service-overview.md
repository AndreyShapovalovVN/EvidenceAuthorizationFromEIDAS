# Огляд сервісу авторизації

Сервіс підтверджує особу через eIDAS Simple Protocol, зберігає `Person` у Redis і показує документи для погодження.

## Авторизація

1. `GET /auth/{message_id}` перевіряє EDM у Redis та зберігає дозволений `returnurl`.
2. Якщо `Person` вже є, браузер переходить на `/preview/{message_id}`. Інакше після `check_message(...)` показується кнопка входу через eIDAS.
3. `GET /auth/eidas/start/{message_id}` зберігає одноразовий стан запиту та надсилає `SMSSPRequest` до Specific Connector.
4. `POST /auth/eidas/callback` обробляє JSON або поле форми `SMSSPResponse`. Обробка зосереджена в `lib/eidas_sp_service.py`.
5. `EIDAS_SP_ALLOWED_LOA` задає дозволені рівні відповіді через кому. Без значення дозволені всі рівні. Недозволений рівень формує `AuthenticationException` (`EDM:ERR:0001`), зберігається в `response:exp` і надсилається до `QUEUE_OUTCOMING`; `Person` не зберігається.
6. Після успішної ідентифікації зберігається `Person`, а браузер отримує `303` до `/preview/{message_id}`. При відхиленні рівня браузер також переходить на preview, де за наявності помилки виконується повернення до порталу.

Якщо EDM відсутній, сторінка повертає користувача на дозволений `returnurl` або відповідає `400`. Бізнес-помилка в `check_message(...)` повертає `422`, таймаут — `408`.

## Перегляд документів

- `GET /preview/{message_id}` показує `evidences.html`, якщо документи готові, або `view_waiting.html`.
- `GET /preview/progress/{message_id}` повертає прогрес та одноразово ставить `message_id` у `process_queue` з EDM.
- `POST /preview/continue` зберігає погодження документів і ставить `message_id` у `QUEUE_OUTCOMING`.
- `POST /preview/timeout/{message_id}` зберігає `EDM:ERR:0005` і ставить `message_id` у `QUEUE_OUTCOMING`.

Маршрути прогресу, погодження і таймауту потребують action-токенів. PDF та XML відображаються в одному переглядачі; вибір документа виконується натисканням на його назву. Підтримується поточний і попередній формат evidence payload.

## Основні модулі

- `main.py` — маршрути, lifecycle Redis, шаблони та HTTP security headers.
- `lib/eidas_sp_service.py` — запити й відповіді eIDAS, одноразовий стан, перевірка LoA.
- `lib/PersonRequestService.py` — валідація та збереження ідентифікованої особи.
- `lib/MessageChecker.py` — перевірка бізнес-помилок і очікування preview-прапора.
- `lib/RedirectService.py` — читання EDM `ReturnLocation` і фільтрація `returnurl`.
- `lib/preview_service.py` — прогрес, черги, погодження та таймаути.
- `lib/evidence_view_model.py` — спільна модель перегляду evidence.
- `lib/preview_keys.py` — додаткові ключі preview та eIDAS поверх `oots_lib.redis_keys.Keys`.

Сервіс використовує Redis-клієнт із `oots_lib`. Підключення відкривається під час startup і закривається під час shutdown. `/health` повертає `503`, якщо Redis недоступний. Тести підміняють Redis і lifecycle та не потребують зовнішніх сервісів.

Налаштування оточення описані в [README](../README.md), встановлення — у [Kubernetes guide](kubernetes-install.md).
