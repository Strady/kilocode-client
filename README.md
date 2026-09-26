# kilocode-client

A typed Python client for the Kilo Code headless server (`kilo serve`). It exposes
the same HTTP + SSE surface the Kilo TUI uses — sessions, chat streaming, shell /
slash commands, interrupt, staged revert, skills, context, model & agent switching,
export/import, and permission handling — with both **async** and **sync** interfaces.

The client talks to a running `kilo serve` (or a daemon, `kilo daemon start`)
instance. It does **not** bundle or start the server itself.

```bash
pip install kilocode-client
```

## Quick start

### Async

```python
import asyncio
from kilocode_client import Kilo


async def main() -> None:
    client = Kilo(base_url="http://127.0.0.1:4096")  # auth from env
    session = await client.session.create(title="demo")
    msg = await client.send_prompt(session.id, "Explain the codebase in one line")
    print("message:", msg.info.id)
    await client.close()


asyncio.run(main())
```

### Sync

```python
from kilocode_client import SyncKilo

client = SyncKilo(base_url="http://127.0.0.1:4096")
session = client.session.create(title="demo")
msg = client.send_prompt(session.id, "Hello")
print("message:", msg.info.id)
client.close()
```

## Authentication

By default the client reads two environment variables, matching the server:

- `KILO_SERVER_USERNAME` (defaults to `"kilo"`)
- `KILO_SERVER_PASSWORD`

If no password is configured the server accepts unauthenticated requests, so the
client simply sends no `Authorization` header. You can also pass `username=` /
`password=` directly to `Kilo(...)` / `SyncKilo(...)`.

The daemon (`kilo daemon start`) uses username `kilo` / password `kilo` and serves
on `http://127.0.0.1:PORT` (ports 4097–4116); its current port is in the daemon
state file.

## Streaming

Subscribe to a session's event stream and iterate typed events. To observe text
deltas *as they stream*, subscribe **before** sending and use the non-blocking
`send_prompt_async` (`POST /session/{id}/prompt_async`):

```python
import asyncio
from kilocode_client import Kilo
from kilocode_client import text_delta_of, tool_call_of, permission_of


async def main() -> None:
    client = Kilo()
    session = await client.session.create(title="stream")

    async def send() -> None:
        await asyncio.sleep(0.2)  # let the subscription settle first
        await client.send_prompt_async(session.id, "Refactor the parser")

    sender = asyncio.create_task(send())
    async for event in await client.stream_session_events(session.id):
        if delta := text_delta_of(event):
            print(delta, end="")
        if tool := tool_call_of(event):
            print(f"\n[tool {tool.status}] {tool.tool} {tool.input}")
        if perm := permission_of(event):
            await client.permission.reply(perm.request_id, "once")
        if event.is_turn_close:
            break
    sender.cancel()
    await client.close()


asyncio.run(main())
```

> **Note on `send_prompt` vs `send_prompt_async`**: the v1 `POST /session/{id}/message`
> route (`send_prompt`) is *synchronous* — it waits for the full response and returns
> the completed message, so nothing is left to stream afterward. For live streaming
> use `send_prompt_async`, which returns immediately (HTTP 204) while the agent loop
> runs in the background.

For a fully synchronous iterator with the sync client:

```python
for event in client.stream_session_events(session.id):
    print(event.type, event.properties)
```

### Global vs instance streams

- **Instance stream** (`GET /event`): one event per line,
  `{ "id", "type", "properties" }`. Use `client.stream_session_events(id)` /
  `client.stream_session_log(id)`.
- **Global stream** (`GET /global/event`): events wrapped as
  `{ "directory", "project", "workspace", "payload": { "id", "type", "properties" } }`.
  Use `client.stream_global_events()`.

Events are deliberately kept generic (raw `properties` + convenience accessors) so
new event types don't break the client.

## TUI parity

Every action you can do in the Kilo TUI maps to a method here:

| TUI action | `kilocode-client` method |
|---|---|
| New session | `session.create(title=, agent=, model=)` |
| List / open sessions | `session.list_sessions()` / `session.get(id)` |
| Rename / archive session | `session.rename(id, title)` / `session.archive(id)` |
| Delete session | `session.delete(id)` |
| Fork session | `session.fork(id, message_id=)` |
| Type a prompt + Enter | `send_prompt(id, "text")` (synchronous, `/message`) |
| Send message (raw) | `send_message(id, parts=...)` (v1 `/message`) |
| Stream-enabled prompt | `send_prompt_async(id, "text")` (`/prompt_async`) |
| Interrupt current run | `interrupt(id)` (alias `abort`) |
| Run a slash command | `run_command(id, command, arguments=)` |
| Run a shell command | `run_shell(id, command, arguments=)` |
| Switch model / agent | `change_model(id, provider_id, model_id, agent=)` |
| Compact / summarize context | `compact(id, provider_id, model_id, auto=)` / `compact_v2(id)` |
| View context after compaction | `get_context(id)` |
| History / messages list | `session.messages(id)` / `list_messages(id)` |
| Get a single message | `session.message(id, message_id)` |
| Delete a message | `delete_message(id, message_id)` |
| Undo a message's edits | `revert(id, message_id, part_id=)` |
| Redo a revert | `unrevert(id)` |
| Todo list | `session.todo(id)` / `get_todos(id)` |
| Enable a skill | (auto-discovered) `list_skills()`, remove via `remove_skill(loc)` |
| Custom agents | `list_agents()`, remove via `remove_agent(name)` |
| Allow permission once/always/reject | `permission.reply(request_id, "once"/"always"/"reject")` |
| Allow everything | `permission.allow_everything(enabled)` |
| Pending permission requests | `permission.list_pending()` |
| Wait for turn to finish | `wait_for_turn_end(id, timeout=)` |
| Stream live updates | `stream_session_events(id)`, `stream_global_events()` |
| Export session | `export_session(id)` / `export_session_to_file(id, path)` |
| Import session/message/project | `import_session(doc)` / `import_message(doc)` / `import_project(doc)` |
| Server health / providers / models | `health()`, `list_providers()`, `list_models()` |
| Session status map | `session_status()` |

The async API uses `await`; add the same method names on `SyncKilo` for blocking
calls (e.g. `SyncKilo().session.create(...)`).

## Models

Request/response payloads are validated with pydantic v2 models derived from the
server's OpenAPI schema (`packages/sdk/openapi.json`). Message parts and v2 session
messages are discriminated unions keyed off a `type`/`status` field.

## Development

```bash
# set up
uv sync --dev                     # or: uv pip install -e ".[dev]" --python .venv/bin/python
# lint + format
ruff check . && ruff format --check .
# type-check
ty check
# tests (unit + integration against a live `kilo serve`)
python -m pytest
```

Integration tests are skipped when no `KILO_SERVER_URL` / running `kilo serve` is
available — see `tests/`.

## Documentation

Docstrings are written in reStructuredText and rendered with Sphinx (autodoc).
Build the docs with:

```bash
uv pip install -e ".[docs]" -p .venv
cd docs && sphinx-build -b html . _build/html
```

The generated HTML lands in `docs/_build/html/index.html`.

## License

MIT