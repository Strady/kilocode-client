"""Synchronous wrapper around the async :class:`kilocode_client.client.Kilo`.

Every :class:`Kilo` async method is re-exposed as a blocking method on
:class:`SyncKilo`. Behind the scenes a single event loop is created lazily per
instance and each method's coroutine is driven on it.

SSE streaming is the one non-trivial case: the async iterator runs in a
dedicated worker thread that feeds a thread-safe queue, and the sync iterator
pulls from that queue. This keeps blocking calls out of the (main) thread that
a caller might otherwise want to use for other work.

Usage::

    client = SyncKilo(base_url="http://127.0.0.1:4096")
    session = client.session.create(title="demo")
    client.send_prompt(session.id, "Hello")
    client.close()
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Coroutine, Iterator
from typing import Any, TypeVar

from .client import Kilo
from .events import KiloEvent
from .models import (
    AgentAttachment,
    FileAttachment,
    MessagePartInput,
    MessageWithParts,
    ModelRef,
    SessionInfo,
    SessionMessage,
    Todo,
)

R = TypeVar("R")


class _Loop:
    """Background thread that owns a single asyncio event loop.

    Every coroutine the sync wrapper submits is run on this same loop, so the
    underlying ``httpx`` connection pool stays bound to one loop. ``run()``
    blocks the calling thread until the coroutine completes; background streams
    are submitted with :meth:`submit` and deliver events through a queue.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_forever, name="kilocode-sync-loop", daemon=True
        )
        self._ready = threading.Event()
        self._thread.start()
        self._ready.wait()

    def _run_forever(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        # drain pending tasks then close cleanly
        try:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        finally:
            self._loop.close()

    def run(self, coro: Coroutine[Any, Any, R], timeout: float | None = None) -> R:
        """Run a coroutine to completion and return its result (blocking)."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            if timeout is not None:
                return future.result(timeout=timeout)
            return future.result()
        except (TimeoutError, asyncio.TimeoutError):
            future.cancel()
            raise

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Schedule a coroutine in the loop thread without waiting for it."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def close(self) -> None:
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)


class SyncKilo:
    """Synchronous facade over :class:`Kilo`.

    All methods block until the server responds. Raise the same exception types
    as the async client (:class:`KiloHTTPError` and friends).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._async = Kilo(*args, **kwargs)
        self._loop = _Loop()
        self._stream_cancel: threading.Event | None = None

        # Namespaced wrappers
        self.session = _SyncSessionApi(self)
        self.permission = _SyncPermissionApi(self)

    # -- lifecycle -----------------------------------------------------------

    def _run(self, coro: Coroutine[Any, Any, R], timeout: float | None = None) -> R:
        return self._loop.run(coro, timeout=timeout)

    def close(self) -> None:
        """Cancel any streaming and close the underlying client and loop."""
        self._stop_stream()
        try:
            self._loop.run(self._async.close())
        except Exception:  # noqa: BLE001 - loop may already be shutting down
            pass
        finally:
            self._loop.close()

    def __enter__(self) -> SyncKilo:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- global server info ----------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._run(self._async.health())

    def list_providers(self, directory: str | None = None) -> list[dict[str, Any]]:
        return self._run(self._async.list_providers(directory))

    def list_models(self, directory: str | None = None) -> list[dict[str, Any]]:
        return self._run(self._async.list_models(directory))

    def list_agents(self) -> list[dict[str, Any]]:
        return self._run(self._async.list_agents())

    def list_skills(self) -> list[dict[str, Any]]:
        return self._run(self._async.list_skills())

    # -- session management ------------------------------------------------------

    def send_message(
        self,
        session_id: str,
        *,
        parts: list[MessagePartInput] | None = None,
        message: str | None = None,
        text: str = "",
        model: dict[str, str] | ModelRef | None = None,
        agent: str | None = None,
        tools: dict[str, bool] | None = None,
        no_reply: bool = False,
    ) -> MessageWithParts:
        return self._run(
            self._async.send_message(
                session_id,
                parts=parts,
                message=message,
                text=text,
                model=model,
                agent=agent,
                tools=tools,
                no_reply=no_reply,
            )
        )

    def send_prompt(
        self,
        session_id: str,
        text: str,
        *,
        files: list[FileAttachment] | None = None,
        agents: list[AgentAttachment] | None = None,
        model: dict[str, str] | ModelRef | None = None,
        agent: str | None = None,
    ) -> MessageWithParts:
        return self._run(
            self._async.send_prompt(
                session_id,
                text,
                files=files,
                agents=agents,
                model=model,
                agent=agent,
            )
        )

    def send_prompt_async(
        self,
        session_id: str,
        text: str,
        *,
        files: list[FileAttachment] | None = None,
        agents: list[AgentAttachment] | None = None,
        model: dict[str, str] | ModelRef | None = None,
        agent: str | None = None,
    ) -> None:
        self._run(
            self._async.send_prompt_async(
                session_id,
                text,
                files=files,
                agents=agents,
                model=model,
                agent=agent,
            )
        )

    def interrupt(self, session_id: str) -> bool:
        return self._run(self._async.interrupt(session_id))

    abort = interrupt

    def run_command(
        self,
        session_id: str,
        command: str,
        arguments: str = "",
        *,
        model: dict[str, str] | None = None,
        agent: str | None = None,
    ) -> MessageWithParts:
        return self._run(
            self._async.run_command(
                session_id,
                command,
                arguments,
                model=model,
                agent=agent,
            )
        )

    def run_shell(
        self,
        session_id: str,
        command: str,
        arguments: str = "",
        *,
        model: dict[str, str] | None = None,
        agent: str | None = None,
    ) -> MessageWithParts:
        return self._run(
            self._async.run_shell(
                session_id,
                command,
                arguments,
                model=model,
                agent=agent,
            )
        )

    def change_model(
        self, session_id: str, provider_id: str, model_id: str, agent: str | None = None
    ) -> bool:
        return self._run(self._async.change_model(session_id, provider_id, model_id, agent))

    def compact(self, session_id: str, provider_id: str, model_id: str, auto: bool = False) -> bool:
        return self._run(self._async.compact(session_id, provider_id, model_id, auto))

    def compact_v2(self, session_id: str) -> None:
        self._run(self._async.compact_v2(session_id))

    def get_context(self, session_id: str) -> list[SessionMessage]:
        return self._run(self._async.get_context(session_id))

    def list_sessions(self, **query: Any) -> list[SessionInfo]:
        return self._run(self._async.list_sessions(**query))

    def get_session(self, session_id: str) -> SessionInfo:
        return self._run(self._async.get_session(session_id))

    def create_session(
        self,
        *,
        title: str | None = None,
        agent: str | None = None,
        model: dict[str, Any] | None = None,
    ) -> SessionInfo:
        return self._run(self._async.create_session(title=title, agent=agent, model=model))

    def delete_session(self, session_id: str) -> bool:
        return self._run(self._async.delete_session(session_id))

    def fork_session(self, session_id: str, *, message_id: str | None = None) -> SessionInfo:
        return self._run(self._async.fork_session(session_id, message_id=message_id))

    def rename_session(self, session_id: str, title: str) -> SessionInfo:
        return self._run(self._async.rename_session(session_id, title))

    def archive_session(self, session_id: str) -> SessionInfo:
        return self._run(self._async.archive_session(session_id))

    def session_status(self) -> dict[str, dict[str, Any]]:
        return self._run(self._async.session_status())

    def list_messages(self, session_id: str, limit: int | None = None) -> list[MessageWithParts]:
        return self._run(self._async.list_messages(session_id, limit))

    def get_message(self, session_id: str, message_id: str) -> MessageWithParts:
        return self._run(self._async.get_message(session_id, message_id))

    def delete_message(self, session_id: str, message_id: str) -> bool:
        return self._run(self._async.delete_message(session_id, message_id))

    def get_todos(self, session_id: str) -> list[Todo]:
        return self._run(self._async.get_todos(session_id))

    def revert(self, session_id: str, message_id: str, part_id: str | None = None) -> SessionInfo:
        return self._run(self._async.revert(session_id, message_id, part_id))

    def unrevert(self, session_id: str) -> SessionInfo:
        return self._run(self._async.unrevert(session_id))

    def remove_skill(self, location: str) -> bool:
        return self._run(self._async.remove_skill(location))

    def remove_agent(self, name: str) -> bool:
        return self._run(self._async.remove_agent(name))

    def export_session(self, session_id: str) -> dict[str, Any]:
        return self._run(self._async.export_session(session_id))

    def export_session_to_file(self, session_id: str, path: str) -> None:
        self._run(self._async.export_session_to_file(session_id, path))

    def import_session(self, session: dict[str, Any]) -> dict[str, Any]:
        return self._run(self._async.import_session(session))

    def import_project(self, project: dict[str, Any]) -> dict[str, Any]:
        return self._run(self._async.import_project(project))

    def import_message(self, message: dict[str, Any]) -> dict[str, Any]:
        return self._run(self._async.import_message(message))

    def wait_for_turn_end(self, session_id: str, *, timeout: float | None = None) -> None:
        self._run(self._async.wait_for_turn_end(session_id, timeout=timeout), timeout=timeout)

    # -- SSE streaming (synchronous iterator) -------------------------------------

    def stream_session_events(
        self, session_id: str, *, instance: bool = False
    ) -> Iterator[KiloEvent]:
        """Blocking iterator over a session's SSE events.

        Opens the stream on the client's event loop in the background; iterate
        the returned object with a plain ``for`` loop. Each iteration blocks
        until the next event arrives or the stream closes.
        """
        return self._stream(self._async.stream_session_events(session_id, instance=instance))

    def stream_global_events(self) -> Iterator[KiloEvent]:
        return self._stream(self._async.stream_global_events())

    def stream_session_log(
        self, session_id: str, params: dict[str, Any] | None = None
    ) -> Iterator[KiloEvent]:
        return self._stream(self._async.stream_session_log(session_id, params))

    def _stream(self, consume: Any) -> Iterator[KiloEvent]:
        self._stop_stream()  # only one active stream per client
        q: queue.Queue[KiloEvent | _KiloExceptionSentinel | None] = queue.Queue()
        cancel = threading.Event()

        async def pump() -> None:
            try:
                stream = await consume
                async for event in stream:
                    if cancel.is_set():
                        break
                    q.put(event)
            except Exception as exc:  # noqa: BLE001 - surface in the iterator
                q.put(_EXC_SENTINEL(exc))
            finally:
                q.put(None)

        self._loop.submit(pump())
        self._stream_cancel = cancel
        return _SyncEventIterator(q, cancel)

    def _stop_stream(self) -> None:
        if self._stream_cancel is not None:
            self._stream_cancel.set()
        self._stream_cancel = None


class _SyncEventIterator:
    """Iterates :class:`KiloEvent` pulled from a background coroutine's queue."""

    def __init__(
        self,
        q: queue.Queue[KiloEvent | _KiloExceptionSentinel | None],
        cancel: threading.Event,
    ) -> None:
        self._q = q
        self._cancel = cancel

    def __iter__(self) -> _SyncEventIterator:
        return self

    def __next__(self) -> KiloEvent:
        item = self._q.get()
        if item is None:
            raise StopIteration
        if isinstance(item, _KiloExceptionSentinel):
            raise item.error
        return item

    def close(self) -> None:
        """Stop consuming and let the background pump exit."""
        self._cancel.set()


class _KiloExceptionSentinel:
    __slots__ = ("error",)

    def __init__(self, error: Exception) -> None:
        self.error = error


def _EXC_SENTINEL(exc: Exception) -> _KiloExceptionSentinel:
    return _KiloExceptionSentinel(exc)


class _SyncSessionApi:
    """Namespaced synchronous session helpers (``client.session.*``)."""

    def __init__(self, wrap: SyncKilo) -> None:
        self._w = wrap

    def create(self, **kwargs: Any) -> SessionInfo:
        return self._w.create_session(**kwargs)

    def get(self, session_id: str) -> SessionInfo:
        return self._w.get_session(session_id)

    def list_sessions(self, **query: Any) -> list[SessionInfo]:
        return self._w.list_sessions(**query)

    def delete(self, session_id: str) -> bool:
        return self._w.delete_session(session_id)

    def rename(self, session_id: str, title: str) -> SessionInfo:
        return self._w.rename_session(session_id, title)

    def archive(self, session_id: str) -> SessionInfo:
        return self._w.archive_session(session_id)

    def fork(self, session_id: str, **kwargs: Any) -> SessionInfo:
        return self._w.fork_session(session_id, **kwargs)

    def status(self) -> dict[str, dict[str, Any]]:
        return self._w.session_status()

    def messages(self, session_id: str, limit: int | None = None) -> list[MessageWithParts]:
        return self._w.list_messages(session_id, limit)

    def message(self, session_id: str, message_id: str) -> MessageWithParts:
        return self._w.get_message(session_id, message_id)

    def context(self, session_id: str) -> list[SessionMessage]:
        return self._w.get_context(session_id)

    def compact(self, session_id: str, provider_id: str, model_id: str, auto: bool = False) -> bool:
        return self._w.compact(session_id, provider_id, model_id, auto)

    def revert(self, session_id: str, message_id: str, **kwargs: Any) -> SessionInfo:
        return self._w.revert(session_id, message_id, **kwargs)

    def unrevert(self, session_id: str) -> SessionInfo:
        return self._w.unrevert(session_id)

    def todo(self, session_id: str) -> list[Todo]:
        return self._w.get_todos(session_id)


class _SyncPermissionApi:
    """Namespaced synchronous permission helpers (``client.permission.*``)."""

    def __init__(self, wrap: SyncKilo) -> None:
        self._w = wrap

    def reply(
        self,
        request_id: str,
        response: str,
        *,
        message: str | None = None,
    ) -> bool:
        return self._w._run(self._w._async.permission.reply(request_id, response, message=message))

    def allow_everything(
        self,
        enable: bool,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        return self._w._run(
            self._w._async.permission.allow_everything(
                enable, request_id=request_id, session_id=session_id
            )
        )

    def list_pending(self) -> list[dict[str, Any]]:
        return self._w._run(self._w._async.permission.list_pending())


__all__ = [
    "SyncKilo",
]
