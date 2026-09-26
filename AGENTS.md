# AGENTS.md

Guidance for code agents working in this repository.

## What this project is

`kilocode-client` is an installable Python package that wraps the **Kilo Code headless
server** (`kilo serve`) HTTP + SSE API, mirroring what the Kilo TUI does. It exposes a
typed async client plus a synchronous wrapper.

Public entry points (see `kilocode_client/__init__.py`):

- `Kilo` — async client.
- `SyncKilo` — synchronous wrapper over `Kilo` using one background event-loop thread.

## Layout

```
kilocode_client/
  __init__.py     re-exports the public API (__all__ is authoritative)
  auth.py         Credentials, credentials_from_env, make_headers
  client.py       Kilo (async client) — all HTTP/SSE calls live here
  sync.py         SyncKilo + internal _Loop (daemon thread running an asyncio loop)
  events.py       KiloEvent, EventStream, and parse/text_delta_of/tool_call_of/permission_of helpers
  exceptions.py   KiloError hierarchy + raise_for_response / HTTP error mapping
  models.py       pydantic models + SessionMessage TypeAdapter + validate_session_message()
  py.typed        marker (package is PEP 561 typed)
examples/         runnable usage scripts
tests/
  test_models.py  unit tests (no server required)
  test_client_against_live_server.py  integration tests (skipped unless a server is reachable)
README.md
pyproject.toml
```

## Environment / tooling

- **Python**: >= 3.10. Use the dedicated venv at `/workspace/kilocode_client/.venv`.
- Install with `uv pip install`, not plain `pip`:
  `uv pip install -e ".[dev]"` (or `-p .venv`).
- The **reference server repo** is `/workspace/kilocode` — treat it as **read-only**.
  Use `/workspace/kilocode/packages/sdk/openapi.json` (schema/endpoints) and
  `/workspace/kilocode/packages/sdk/js/src/gen/{sdk.gen.ts,types.gen.ts}` (authoritative
  HTTP paths) as the source of truth. **Never modify files inside `/workspace/kilocode`.**
- Live server binary: `/usr/local/bin/kilo`. Start with
  `kilo serve --port 4096` for integration testing (no auth by default; set
  `KILO_SERVER_PASSWORD` to enable).

## Required checks

Always run both before finishing any code change:

```
.venv/bin/python -m mypy kilocode_client/
.venv/bin/python -m pytest -q
```

- Mypy runs with `strict = true` and `warn_unused_ignores = true` (see `pyproject.toml`).
- Tests skip integration cases automatically when no server is reachable on
  `http://127.0.0.1:4096` (see `tests/test_client_against_live_server.py`).

## Conventions

- **No code comments unless asked.** Keep docstrings on public functions/methods.
- Full type annotations everywhere; mypy strict must stay clean.
- Async (`Kilo`) is the primary implementation. `SyncKilo` methods are thin
  `self._run(self._async.<method>(...))` wrappers — do not duplicate logic there.
- Models are pydantic v2. Wire schemas come from `openapi.json`. If the schema has a
  `Union` (no `model_validate`), use a `TypeAdapter` + a `validate_*` helper.
- `client._request()` returns parsed JSON or a pydantic model; it returns `None` for
  `204`/empty responses and raises typed HTTP errors (via `raise_for_response`) on
  `>= 400`.
- Keep event consumption *generic*: `KiloEvent` carries raw `properties` + convenience
  accessors. Do not require knowledge of every event kind — the server adds new ones.

## Server behavior facts (hard-won, do not "fix")

These are verified against `kilo` 7.3.46 and must be preserved:

- **Send path**: use v1 `POST /session/{id}/message` (how the official SDK's `prompt()`
  works). The v2 `POST /session/{id}/prompt` route is **broken** on this server
  (`Expected Session.Message, got {}`). So `send_prompt`/`send_message` both use v1.
- **`send_prompt` (v1 `/message`) is synchronous** — it waits for the full response and
  returns the completed message; nothing is left to stream afterward.
- **Streaming-friendly send**: `send_prompt_async` posts to
  `POST /session/{id}/prompt_async` (HTTP 204) and returns immediately. To observe live
  text, **subscribe to `stream_session_events` *before*** calling it.<br>
  Correct streaming pattern:
  ```python
  async def send():
      await asyncio.sleep(0.2)  # let the subscription attach
      await client.send_prompt_async(session.id, "...")
  sender = asyncio.create_task(send())
  async for event in await client.stream_session_events(session.id):
      ...
  ```
- **Text deltas** arrive as `message.part.delta` events (`properties.field == "text"`,
  `properties.delta` = fragment), handled by `text_delta_of`/`is_text_delta`. The legacy
  `session.next.text.delta` type is also supported. Do not "simplify" this back to only
  the legacy type.
- **SSE reading**: must use `httpx.AsyncClient.send(req, stream=True)` +
  `response.aiter_bytes()`; a plain `client.get()` buffers the infinite stream. The
  underlying streaming generator closes the response in its `finally`.
- **Message id lives at `msg.info.id`**, not `msg.id` (`MessageWithParts`).
- `Session` model is named `SessionInfo`; `SessionMessage` is an
  `Annotated[Union[...]]` (no `model_validate`) — use `validate_session_message()`.
- 204 / empty-body responses are handled inside `_request` (return `None`); do not call
  `response.json()` on them.

## Adding a new method

1. Implement the HTTP call in `client.py` (async). Use `openapi.json` for the exact
   path, method, and body/query shape.
2. If it returns a response body, define/validate a pydantic model in `models.py`.
3. Add a thin sync wrapper in `sync.py`.
4. Export public names in `__init__.py.__all__` if they are meant to be public.
5. Add a unit test (no server) and, ideally, an integration test behind the
   server-reachable guard in `tests/test_client_against_live_server.py`.
6. Run mypy + pytest.