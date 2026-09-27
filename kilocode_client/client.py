"""Async HTTP+SSE client for the Kilo Code headless server (``kilo serve``).

The server exposes a REST API plus two SSE streams. This client mirrors the surface
the TUI uses (via ``createKiloClient`` in ``@kilocode/sdk``), so every TUI action maps
to a method here. All requests go through a shared :class:`httpx.AsyncClient`
configured with configurable timeouts and retries.

Typical usage::

    import asyncio
    from kilocode_client import Kilo

    async def main() -> None:
        client = Kilo(base_url="http://127.0.0.1:4096")   # picks up auth from env
        session = await client.session.create(title="hi")
        resp = await client.send_prompt(session.id, "Hello")
        async for event in await client.stream_session_events(session.id):
            print(event.type, event.properties)

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx

from .auth import Credentials
from .events import EventStream, KiloEvent
from .exceptions import raise_for_response
from .models import (
    AgentAttachment,
    FileAttachment,
    MessagePartInput,
    MessageWithParts,
    ModelRef,
    SendMessageInput,
    SessionCreateInput,
    SessionInfo,
    SessionMessage,
    SessionModelRef,
    SessionUpdateInput,
    Todo,
    validate_session_message,
)


class Kilo:
    """Async client for a running Kilo server.

    :param base_url: Root of the server, e.g. ``http://127.0.0.1:4096``.
    :param username: Basic-auth username (defaults to ``KILO_SERVER_USERNAME``).
    :param password: Basic-auth password (defaults to ``KILO_SERVER_PASSWORD``).
    :param directory: Project directory the session belongs to. Passed as the
        ``directory`` query param on every request; most useful when the server
        manages multiple projects. Injects the ``x-kilo-directory`` header like the
        official SDK.
    :param timeout: Request timeout in seconds, or an ``httpx.Timeout``.
    :param retries: Number of retries for transient failures (connect/5xx).
    :param headers: Extra headers merged into every request.
    :param follow_redirects: Passed to ``httpx.AsyncClient``.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4096",
        username: str | None = None,
        password: str | None = None,
        directory: str | None = None,
        timeout: float | httpx.Timeout = 60.0,
        retries: int = 0,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.directory = directory

        if username is None and password is None:
            from .auth import credentials_from_env

            creds = credentials_from_env()
        else:
            creds = Credentials(username=username, password=password)

        merged_headers: dict[str, str] = dict(headers or {})
        if creds.header_value:
            merged_headers.setdefault("Authorization", creds.header_value)
        if directory:
            merged_headers.setdefault(
                "x-kilo-directory", base64.b64encode(directory.encode()).decode()
            )

        transport = httpx.AsyncHTTPTransport(retries=retries)
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers=merged_headers,
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=transport,
        )

        # Namespaced accessors
        self.session = _SessionApi(self)
        self.permission = _PermissionApi(self)

    # -- lifecycle -------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> Kilo:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # -- low-level request helpers ---------------------------------------------

    def _params(self, **extra: Any) -> dict[str, Any]:
        params: dict[str, Any] = dict(extra)
        if self.directory:
            params.setdefault("directory", self.directory)
        return params

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        content: bytes | None = None,
        model: Any = None,
        parse: bool = True,
    ) -> Any:
        """Perform a request and return parsed data (or a pydantic model)."""
        response = await self._http.request(
            method,
            path,
            params=self._params(**(params or {})),
            json=json_body if json_body is not None else None,
            content=content,
        )
        if response.status_code >= 400:
            raise_for_response(response)
        if not parse:
            return response
        if response.status_code == 204 or not response.content:
            return None
        data = response.json()
        if model is not None:
            return model.model_validate(data)
        return data

    # -- global server info ----------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """GET /global/health."""
        raw = await self._request("GET", "/global/health")
        return cast(dict[str, Any], raw)

    async def list_providers(self, directory: str | None = None) -> list[dict[str, Any]]:
        """GET /provider -- configured providers (use ``directory`` to scope)."""
        params = {"directory": directory} if directory else {}
        raw = await self._request("GET", "/provider", params=params)
        return cast(list[dict[str, Any]], raw)

    async def list_models(self, directory: str | None = None) -> list[dict[str, Any]]:
        """GET /api/model -- available models."""
        params = {"directory": directory} if directory else {}
        raw = await self._request("GET", "/api/model", params=params)
        return cast(list[dict[str, Any]], raw)

    async def list_agents(self) -> list[dict[str, Any]]:
        """GET /agent -- available agents."""
        raw = await self._request("GET", "/agent")
        return cast(list[dict[str, Any]], raw)

    async def list_skills(self) -> list[dict[str, Any]]:
        """GET /skill -- available skills."""
        raw = await self._request("GET", "/skill")
        return cast(list[dict[str, Any]], raw)

    # -- session management ----------------------------------------------------

    async def send_message(
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
        """Send a message to a session (POST /session/{id}/message).

        Preferred over :meth:`send_prompt` when you want to attach arbitrary parts or
        control tools directly. For ordinary text prompts prefer :meth:`send_prompt`.
        ``message`` is shorthand for a single text part.
        """
        if message is not None or text:
            if message and parts:
                raise ValueError("provide either `message` text or `parts`, not both")
            body_parts = [MessagePartInput(type="text", text=message or text)]
        else:
            body_parts = parts or []
        model_ref = None
        if isinstance(model, dict):
            model_ref = ModelRef.model_validate(model)
        elif model is not None:
            model_ref = model
        body = SendMessageInput(
            parts=body_parts,
            model=model_ref,
            agent=agent,
            tools=tools,
            noReply=no_reply,
        )
        data = await self._request(
            "POST",
            f"/session/{session_id}/message",
            json_body=body.model_dump(exclude_none=True),
        )
        return MessageWithParts.model_validate(data)

    async def send_prompt(
        self,
        session_id: str,
        text: str,
        *,
        files: list[FileAttachment] | None = None,
        agents: list[AgentAttachment] | None = None,
        model: dict[str, str] | ModelRef | None = None,
        agent: str | None = None,
    ) -> MessageWithParts:
        """Send a prompt to a session and return the assistant's message.

        Uses the v1 ``POST /session/{id}/message`` endpoint (the same route the
        official SDK's ``prompt()`` calls), which is the reliable send path across
        ``kilo serve`` versions. Builds ``parts`` from the text plus optional file
        and agent mentions.
        """
        text_part = MessagePartInput(type="text", text=text)
        parts: list[MessagePartInput] = [text_part]
        for f in files or []:
            parts.append(
                MessagePartInput(type="file", uri=f.uri, mime=f.mime, name=f.name or f.uri)
            )
        for a in agents or []:
            parts.append(MessagePartInput(type="agent", name=a.name))
        return await self.send_message(
            session_id,
            parts=parts,
            model=model,
            agent=agent,
        )

    async def send_prompt_async(
        self,
        session_id: str,
        text: str,
        *,
        files: list[FileAttachment] | None = None,
        agents: list[AgentAttachment] | None = None,
        model: dict[str, str] | ModelRef | None = None,
        agent: str | None = None,
    ) -> None:
        """Send a prompt and return immediately (streaming-friendly).

        Posts to ``POST /session/{id}/prompt_async`` (HTTP 204 "prompt accepted").
        The agent loop starts asynchronously; subscribe with
        :meth:`stream_session_events` / :meth:`wait_for_turn_end` to observe progress.
        """
        text_part = MessagePartInput(type="text", text=text)
        parts: list[MessagePartInput] = [text_part]
        for f in files or []:
            parts.append(
                MessagePartInput(type="file", uri=f.uri, mime=f.mime, name=f.name or f.uri)
            )
        for a in agents or []:
            parts.append(MessagePartInput(type="agent", name=a.name))
        model_ref = None
        if isinstance(model, dict):
            model_ref = ModelRef.model_validate(model)
        elif model is not None:
            model_ref = model
        body = SendMessageInput(parts=parts, model=model_ref, agent=agent)
        await self._request(
            "POST",
            f"/session/{session_id}/prompt_async",
            json_body=body.model_dump(exclude_none=True),
        )

    async def interrupt(self, session_id: str) -> bool:
        """Interrupt an in-progress agent run (POST /session/{id}/abort)."""
        raw = await self._request("POST", f"/session/{session_id}/abort")
        return cast(bool, raw)

    # aliases matching TUI action names
    abort = interrupt

    async def run_command(
        self,
        session_id: str,
        command: str,
        arguments: str = "",
        *,
        model: dict[str, str] | None = None,
        agent: str | None = None,
    ) -> MessageWithParts:
        """Run a slash command (POST /session/{id}/command)."""
        body: dict[str, Any] = {"command": command, "arguments": arguments}
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent
        data = await self._request("POST", f"/session/{session_id}/command", json_body=body)
        return MessageWithParts.model_validate(data)

    async def run_shell(
        self,
        session_id: str,
        command: str,
        arguments: str = "",
        *,
        model: dict[str, str] | None = None,
        agent: str | None = None,
    ) -> MessageWithParts:
        """Run a shell command through the session (POST /session/{id}/shell)."""
        body: dict[str, Any] = {"command": command, "arguments": arguments}
        if model:
            body["model"] = model
        if agent:
            body["agent"] = agent
        data = await self._request("POST", f"/session/{session_id}/shell", json_body=body)
        return MessageWithParts.model_validate(data)

    # -- model / agent management ----------------------------------------------

    async def change_model(
        self, session_id: str, provider_id: str, model_id: str, agent: str | None = None
    ) -> bool:
        """Change the active model/agent for a session (via /session/{id}/init)."""
        body: dict[str, Any] = {
            "providerID": provider_id,
            "modelID": model_id,
            "messageID": "",
        }
        if agent:
            body["agent"] = agent
        raw = await self._request("POST", f"/session/{session_id}/init", json_body=body)
        return cast(bool, raw)

    async def compact(
        self, session_id: str, provider_id: str, model_id: str, auto: bool = False
    ) -> bool:
        """Summarize/compact a session (POST /session/{id}/summarize)."""
        raw = await self._request(
            "POST",
            f"/session/{session_id}/summarize",
            json_body={"providerID": provider_id, "modelID": model_id, "auto": auto},
        )
        return cast(bool, raw)

    async def compact_v2(self, session_id: str) -> None:
        """Compact a v2 session (POST /api/session/{id}/compact)."""
        await self._request("POST", f"/api/session/{session_id}/compact")

    # -- context / history -----------------------------------------------------

    async def get_context(self, session_id: str) -> list[SessionMessage]:
        """GET /api/session/{id}/context -- active context messages after last compaction."""
        data = await self._request("GET", f"/api/session/{session_id}/context")
        return [validate_session_message(item) for item in data]

    async def list_sessions(self, **query: Any) -> list[SessionInfo]:
        """GET /session -- list sessions (accepts scope/path/roots/start/search/limit)."""
        data = await self._request("GET", "/session", params=query)
        return [SessionInfo.model_validate(item) for item in data]

    async def get_session(self, session_id: str) -> SessionInfo:
        """GET /session/{id}."""
        data = await self._request("GET", f"/session/{session_id}")
        return SessionInfo.model_validate(data)

    async def create_session(
        self,
        *,
        title: str | None = None,
        agent: str | None = None,
        model: dict[str, Any] | None = None,
    ) -> SessionInfo:
        """POST /session -- create a new session."""
        model_ref = None
        if model is not None:
            model_ref = SessionModelRef.model_validate(model)
        body = SessionCreateInput(title=title, agent=agent, model=model_ref)
        data = await self._request("POST", "/session", json_body=body.model_dump(exclude_none=True))
        return SessionInfo.model_validate(data)

    async def delete_session(self, session_id: str) -> bool:
        """DELETE /session/{id}."""
        raw = await self._request("DELETE", f"/session/{session_id}")
        return cast(bool, raw)

    async def fork_session(self, session_id: str, *, message_id: str | None = None) -> SessionInfo:
        """POST /session/{id}/fork -- fork at a specific message (or whole session)."""
        body: dict[str, Any] = {}
        if message_id:
            body["messageID"] = message_id
        data = await self._request("POST", f"/session/{session_id}/fork", json_body=body or None)
        return SessionInfo.model_validate(data)

    async def rename_session(self, session_id: str, title: str) -> SessionInfo:
        """Rename a session (PATCH /session/{id})."""
        body = SessionUpdateInput(title=title)
        data = await self._request(
            "PATCH", f"/session/{session_id}", json_body=body.model_dump(exclude_none=True)
        )
        return SessionInfo.model_validate(data)

    async def archive_session(self, session_id: str) -> SessionInfo:
        """Archive a session (PATCH /session/{id} with archived time)."""
        import time

        body = SessionUpdateInput(time={"archived": int(time.time() * 1000)})
        data = await self._request(
            "PATCH", f"/session/{session_id}", json_body=body.model_dump(exclude_none=True)
        )
        return SessionInfo.model_validate(data)

    async def session_status(self) -> dict[str, dict[str, Any]]:
        """GET /session/status -- status of all sessions."""
        raw = await self._request("GET", "/session/status")
        return cast(dict[str, dict[str, Any]], raw)

    # -- messages ---------------------------------------------------------------

    async def list_messages(
        self, session_id: str, limit: int | None = None
    ) -> list[MessageWithParts]:
        """GET /session/{id}/message -- session history."""
        params: dict[str, Any] = {}
        if limit:
            params["limit"] = limit
        data = await self._request("GET", f"/session/{session_id}/message", params=params)
        return [MessageWithParts.model_validate(item) for item in data]

    async def get_message(self, session_id: str, message_id: str) -> MessageWithParts:
        """GET /session/{id}/message/{messageID}."""
        data = await self._request("GET", f"/session/{session_id}/message/{message_id}")
        return MessageWithParts.model_validate(data)

    async def delete_message(self, session_id: str, message_id: str) -> bool:
        """DELETE /session/{id}/message/{messageID}."""
        raw = await self._request("DELETE", f"/session/{session_id}/message/{message_id}")
        return cast(bool, raw)

    async def get_todos(self, session_id: str) -> list[Todo]:
        """GET /session/{id}/todo."""
        data = await self._request("GET", f"/session/{session_id}/todo")
        return [Todo.model_validate(item) for item in data]

    # -- reverts ----------------------------------------------------------------

    async def revert(
        self, session_id: str, message_id: str, part_id: str | None = None
    ) -> SessionInfo:
        """Undo the effects of a message (POST /session/{id}/revert)."""
        body: dict[str, Any] = {"messageID": message_id}
        if part_id:
            body["partID"] = part_id
        data = await self._request("POST", f"/session/{session_id}/revert", json_body=body)
        return SessionInfo.model_validate(data)

    async def unrevert(self, session_id: str) -> SessionInfo:
        """Restore reverted messages (POST /session/{id}/unrevert)."""
        data = await self._request("POST", f"/session/{session_id}/unrevert")
        return SessionInfo.model_validate(data)

    # -- skills -------------------------------------------------------------------

    async def remove_skill(self, location: str) -> bool:
        """Remove a skill by its file location (POST /kilocode/skill/remove)."""
        raw = await self._request(
            "POST", "/kilocode/skill/remove", json_body={"location": location}
        )
        return cast(bool, raw)

    async def remove_agent(self, name: str) -> bool:
        """Remove a custom agent by name (POST /kilocode/agent/remove)."""
        raw = await self._request("POST", "/kilocode/agent/remove", json_body={"name": name})
        return cast(bool, raw)

    # -- export / import -----------------------------------------------------------

    async def export_session(self, session_id: str) -> dict[str, Any]:
        """Export a session to a JSON document compatible with ``kilo export``.

        The server has no single-file bundle endpoint, so we reconstruct the document
        the way ``kilo export`` does: session metadata + all messages.
        """
        session = await self.get_session(session_id)
        messages = await self.list_messages(session_id)
        return {
            "session": session.model_dump(exclude_none=True),
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }

    async def export_session_to_file(self, session_id: str, path: str) -> None:
        """Export a session to a JSON file."""
        doc = await self.export_session(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)

    async def import_session(self, session: dict[str, Any]) -> dict[str, Any]:
        """Import a session record (POST /kilocode/session-import/session)."""
        raw = await self._request("POST", "/kilocode/session-import/session", json_body=session)
        return cast(dict[str, Any], raw)

    async def import_project(self, project: dict[str, Any]) -> dict[str, Any]:
        """Import a project record (POST /kilocode/session-import/project)."""
        raw = await self._request("POST", "/kilocode/session-import/project", json_body=project)
        return cast(dict[str, Any], raw)

    async def import_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Import a message record (POST /kilocode/session-import/message)."""
        raw = await self._request("POST", "/kilocode/session-import/message", json_body=message)
        return cast(dict[str, Any], raw)

    # -- SSE streaming -------------------------------------------------------------

    async def stream_session_events(
        self,
        session_id: str,
        *,
        instance: bool = False,
    ) -> AsyncIterator[KiloEvent]:
        """Subscribe to a session's live events, yielding only its events.

        Opens the instance-wide ``/event`` stream. Because the server does not filter
        this stream per session, events are filtered *client-side* by ``sessionID``
        (the events carry it in their ``properties``); events from other sessions are
        skipped. Pass ``instance=True`` to bypass filtering and yield every event on
        the instance stream regardless of session. Returns an async iterator you can
        consume with ``async for``.
        """
        base = await self._stream("/event")
        if instance:
            return base
        return _FilteredEventStream(base, session_id=session_id)

    async def stream_global_events(self) -> AsyncIterator[KiloEvent]:
        """Subscribe to the global cross-project event stream (GET /global/event)."""
        return await self._stream("/global/event")

    async def stream_session_log(
        self,
        session_id: str,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[KiloEvent]:
        """Subscribe to a session's event log, yielding only its events.

        The server exposes the full session event log via ``/event``; we use that
        stream and filter client-side to ``session_id``.
        """
        base = await self._stream("/event", params=params)
        return _FilteredEventStream(base, session_id=session_id)

    async def _stream(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[KiloEvent]:
        """Open an SSE stream using a streaming (non-buffering) httpx request."""
        request = self._http.build_request("GET", path, params=self._params(**(params or {})))
        response = await self._http.send(request, stream=True)
        if response.status_code >= 400:
            await response.aread()
            raise_for_response(response)
        source = EventStream(response.aiter_bytes())

        async def gen() -> AsyncIterator[KiloEvent]:
            try:
                async for event in source:
                    yield event
            finally:
                await response.aclose()

        return gen()

    # -- permission handling ----------------------------------------------------------

    async def wait_for_turn_end(
        self,
        session_id: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Block until a session's agent loop reports ``session.turn.close``.

        Useful after :meth:`send_prompt` when you want to wait for the full response
        instead of consuming the stream manually.
        """
        stream = await self.stream_session_events(session_id)
        try:
            if timeout is not None:
                await asyncio.wait_for(
                    self._consume_until_turn_close(stream, session_id), timeout=timeout
                )
            else:
                await self._consume_until_turn_close(stream, session_id)
        finally:
            if hasattr(stream, "aclose") and asyncio.iscoroutinefunction(stream.aclose):
                await stream.aclose()

    async def _consume_until_turn_close(
        self, stream: AsyncIterator[KiloEvent], session_id: str
    ) -> None:
        async for event in stream:
            if event.is_turn_close and event.session_id == session_id:
                return


class _FilteredEventStream:
    """Wraps an :class:`EventStream`, yielding only events for a given session.

    Kept as a separate async iterator (rather than re-wrapping in ``EventStream``)
    because filtering operates on *parsed* events, not raw SSE bytes.
    """

    def __init__(self, source: AsyncIterator[KiloEvent], session_id: str) -> None:
        self._source = source
        self._session_id = session_id

    def __aiter__(self) -> _FilteredEventStream:
        return self

    async def __anext__(self) -> KiloEvent:
        async for event in self._source:
            if event.session_id == self._session_id:
                return event
        raise StopAsyncIteration


class _SessionApi:
    """Namespaced session operations mirroring ``client.session.*`` in the SDK."""

    def __init__(self, client: Kilo) -> None:
        self._client = client

    async def list_sessions(self, **query: Any) -> list[SessionInfo]:
        return await self._client.list_sessions(**query)

    async def create(self, **kwargs: Any) -> SessionInfo:
        return await self._client.create_session(**kwargs)

    async def get(self, session_id: str) -> SessionInfo:
        return await self._client.get_session(session_id)

    async def delete(self, session_id: str) -> bool:
        return await self._client.delete_session(session_id)

    async def fork(self, session_id: str, **kwargs: Any) -> SessionInfo:
        return await self._client.fork_session(session_id, **kwargs)

    async def rename(self, session_id: str, title: str) -> SessionInfo:
        return await self._client.rename_session(session_id, title)

    async def archive(self, session_id: str) -> SessionInfo:
        return await self._client.archive_session(session_id)

    async def status(self) -> dict[str, dict[str, Any]]:
        return await self._client.session_status()

    async def messages(self, session_id: str, limit: int | None = None) -> list[MessageWithParts]:
        return await self._client.list_messages(session_id, limit)

    async def message(self, session_id: str, message_id: str) -> MessageWithParts:
        return await self._client.get_message(session_id, message_id)

    async def context(self, session_id: str) -> list[SessionMessage]:
        return await self._client.get_context(session_id)

    async def compact(
        self, session_id: str, provider_id: str, model_id: str, auto: bool = False
    ) -> bool:
        return await self._client.compact(session_id, provider_id, model_id, auto)

    async def revert(self, session_id: str, message_id: str, **kwargs: Any) -> SessionInfo:
        return await self._client.revert(session_id, message_id, **kwargs)

    async def unrevert(self, session_id: str) -> SessionInfo:
        return await self._client.unrevert(session_id)

    async def todo(self, session_id: str) -> list[Todo]:
        return await self._client.get_todos(session_id)


class _PermissionApi:
    """Permission request handling."""

    def __init__(self, client: Kilo) -> None:
        self._client = client

    async def reply(
        self,
        request_id: str,
        response: str,
        *,
        message: str | None = None,
    ) -> bool:
        """Reply to a permission request (POST /permission/{id}/reply).

        ``response`` is one of ``"once"`` (allow this time), ``"always"`` or
        ``"reject"``.
        """
        body: dict[str, Any] = {"reply": response}
        if message:
            body["message"] = message
        raw = await self._client._request("POST", f"/permission/{request_id}/reply", json_body=body)
        return cast(bool, raw)

    async def allow_everything(
        self, enable: bool, *, request_id: str | None = None, session_id: str | None = None
    ) -> bool:
        """Globally allow or deny all pending permission requests."""
        body: dict[str, Any] = {"enable": enable}
        if request_id:
            body["requestID"] = request_id
        if session_id:
            body["sessionID"] = session_id
        raw = await self._client._request("POST", "/permission/allow-everything", json_body=body)
        return cast(bool, raw)

    async def list_pending(self) -> list[dict[str, Any]]:
        """GET /permission -- the current pending permission requests."""
        raw = await self._client._request("GET", "/permission")
        return cast(list[dict[str, Any]], raw)


def credentials_from_env() -> Credentials:
    """Build credentials from ``KILO_SERVER_USERNAME`` / ``KILO_SERVER_PASSWORD``."""
    from .auth import credentials_from_env as _from_env

    return _from_env()


__all__ = ["Kilo", "Credentials", "EventStream", "KiloEvent"]
