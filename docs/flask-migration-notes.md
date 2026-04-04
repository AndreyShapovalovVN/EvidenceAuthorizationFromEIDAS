# Flask to FastAPI migration notes

## Goal

Recreate legacy `OOTS-evidence-viewer` behavior in this FastAPI service and retire Flask support.

## Iteration 1 (done)

- Added a shared renderer for auth page flow in `main.py`.
- Added backward-compatible route alias `GET /{message_id}`.
- Kept `/view/*` endpoints explicit with `501` while migration scope is not implemented.
- Added endpoint tests for alias and `501` placeholders.

## Iteration 2 (next)

- Inventory legacy Flask `/view/*` contract (request params, response codes, redirects, Redis keys).
- Implement `GET /view/{message_id}` parity.
- Implement `POST /view/continue` parity.
- Add contract tests for all migrated `/view/*` scenarios.

## Contract checklist to capture from Flask

- Exact routes and methods.
- Success and error HTTP status codes.
- Error body schema and field names.
- Redirect behavior and query params.
- Redis keys and payload structure.
- Template fields expected by frontend JS.

