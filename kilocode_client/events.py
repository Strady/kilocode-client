"""Typed parsing of the Kilo server's SSE event stream.

The server emits two flavors of events:

* Instance stream (``GET /event``): each event is ``{ "id", "type", "properties" }``.
* Global stream (``GET /global/event``): each event is wrapped as
  ``{ "directory", "project"?, "workspace"?, "payload": { "id", "type", "properties" } }``.

On the wire every event is a JSON object delivered as a single SSE ``data:`` line
(``data: <json>\\n\\n``). This module parses low-level SSE frames into
:class:`KiloEvent` objects and provides :class:`EventStream`, an ``asyncio`` async
iterator that yields typed events from an ``httpx`` streaming response.

Events are deliberately kept *generic* (raw ``properties`` plus convenience
accessors) rather than a closed enum of schema types. This keeps the client resilient
to new event kinds added server-side, matching how the TUI consumes the stream.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KiloEvent:
    """A single parsed SSE event.

    :ivar type: The event's discriminant (e.g. ``session.next.text.delta``).
    :ivar id: Server-assigned event id (string), if present.
    :ivar properties: The raw ``properties`` payload dict.
    :ivar directory: Routing metadata, set only for global-stream events.
    :ivar project: Routing metadata, set only for global-stream events.
    :ivar workspace: Routing metadata, set only for global-stream events.
    """

    type: str
    properties: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    directory: str | None = None
    project: str | None = None
    workspace: str | None = None

    # -- convenience accessors -------------------------------------------------

    @property
    def session_id(self) -> str | None:
        value = self.properties.get("sessionID")
        return value if isinstance(value, str) else None

    @property
    def is_turn_close(self) -> bool:
        return self.type == "session.turn.close"

    @property
    def turn_close_reason(self) -> str | None:
        if self.type != "session.turn.close":
            return None
        reason = self.properties.get("reason")
        return reason if isinstance(reason, str) else None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "properties": self.properties}
        if self.id is not None:
            payload["id"] = self.id
        return payload


class SessionTextDelta:
    """Structured view of a text-delta event.

    On the installed server build (7.3.x) text is streamed via
    ``message.part.delta`` events whose ``properties.field`` is ``"text"`` and whose
    ``properties.delta`` holds the fragment. Older builds used
    ``session.next.text.delta``.
    """

    __slots__ = ("session_id", "delta")

    def __init__(self, session_id: str | None, delta: str) -> None:
        self.session_id = session_id
        self.delta = delta


class ToolCallEvent:
    """Structured view of a `session.next.tool.called` / `.success` / `.failed` event."""

    __slots__ = ("session_id", "call_id", "tool", "input", "status")

    def __init__(
        self,
        session_id: str | None,
        call_id: str | None,
        tool: str | None,
        input: dict[str, Any],
        status: str,
    ) -> None:
        self.session_id = session_id
        self.call_id = call_id
        self.tool = tool
        self.input = input
        self.status = status


@dataclass(frozen=True)
class PermissionRequestInfo:
    """Lightweight view of a `permission.asked` payload."""

    request_id: str | None
    session_id: str | None
    permission: str | None
    patterns: list[str]
    data: dict[str, Any] = field(default_factory=dict)


def is_text_delta(event: KiloEvent) -> bool:
    return event.type == "session.next.text.delta" or (
        event.type == "message.part.delta" and event.properties.get("field") == "text"
    )


def text_delta_of(event: KiloEvent) -> str | None:
    """Return the text fragment for a text-delta event, else ``None``."""
    if event.type == "session.next.text.delta":
        delta = event.properties.get("delta")
        return delta if isinstance(delta, str) else None
    if event.type == "message.part.delta" and event.properties.get("field") == "text":
        delta = event.properties.get("delta")
        return delta if isinstance(delta, str) else None
    return None


def tool_call_of(event: KiloEvent) -> ToolCallEvent | None:
    """Return a :class:`ToolCallEvent` for tool start/end events, else ``None``."""
    status_by_type = {
        "session.next.tool.called": "running",
        "session.next.tool.success": "completed",
        "session.next.tool.failed": "error",
        "session.next.tool.input": "input",
    }
    if event.type not in status_by_type:
        return None
    input_value = event.properties.get("input")
    return ToolCallEvent(
        session_id=event.session_id,
        call_id=event.properties.get("callID"),
        tool=event.properties.get("tool"),
        input=input_value if isinstance(input_value, dict) else {},
        status=status_by_type[event.type],
    )


def permission_of(event: KiloEvent) -> PermissionRequestInfo | None:
    """Return a :class:`PermissionRequestInfo` for a `permission.asked`, else ``None``."""
    if event.type != "permission.asked":
        return None
    props = event.properties or {}
    patterns = list(props.get("patterns") or [])
    return PermissionRequestInfo(
        request_id=props.get("id"),
        session_id=props.get("sessionID"),
        permission=props.get("permission"),
        patterns=patterns,
        data=props,
    )


# --------------------------------------------------------------------------- #
# SSE frame parsing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _RawFrame:
    data: str | None
    event: str | None
    id: str | None


def _split_frame(frame: str) -> _RawFrame:
    """Parse a single SSE frame into its ``data``/``event``/``id`` components."""
    data_lines: list[str] = []
    event: str | None = None
    msg_id: str | None = None
    for line in frame.split("\n"):
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("id:"):
            msg_id = line[3:].strip()
    if not data_lines:
        return _RawFrame(None, event, msg_id)
    return _RawFrame("\n".join(data_lines), event, msg_id)


def parse_event_frame(frame: str) -> KiloEvent | None:
    """Parse one SSE frame into a :class:`KiloEvent`, or ``None`` for keep-alives."""
    raw = _split_frame(frame)
    if raw.data is None:
        return None
    try:
        payload = json.loads(raw.data)
    except json.JSONDecodeError:
        return None
    # Global-stream wrapping: { directory?, project?, workspace?, payload: {..} }
    if isinstance(payload, dict) and isinstance(payload.get("payload"), dict):
        inner = payload["payload"]
        if isinstance(inner, dict) and isinstance(inner.get("type"), str):
            return KiloEvent(
                id=inner.get("id"),
                type=inner["type"],
                properties=inner.get("properties") or {},
                directory=payload.get("directory"),
                project=payload.get("project"),
                workspace=payload.get("workspace"),
            )
    if isinstance(payload, dict) and isinstance(payload.get("type"), str):
        return KiloEvent(
            id=payload.get("id"),
            type=payload["type"],
            properties=payload.get("properties") or {},
        )
    return None


def parse_events(text: str) -> list[KiloEvent]:
    """Parse a chunk of SSE text (many frames) into a list of events."""
    events: list[KiloEvent] = []
    for frame in text.split("\n\n"):
        event = parse_event_frame(frame)
        if event is not None:
            events.append(event)
    return events


# --------------------------------------------------------------------------- #
# Async streaming iterator over an SSE response body
# --------------------------------------------------------------------------- #


class EventStream:
    """Async iterator over :class:`KiloEvent` objects from an SSE response body.

    Reassembles chunks across network boundaries and discards SSE comments and empty
    keep-alive frames. Usable with ``async for event in stream: ...`` and closed the
    same way an ``httpx`` streaming response is closed.
    """

    def __init__(self, aiter: AsyncIterator[bytes], decoder: str = "utf-8") -> None:
        self._aiter = aiter
        self._decoder = decoder
        self._buffer = ""

    def __aiter__(self) -> EventStream:
        return self

    async def __anext__(self) -> KiloEvent:
        while True:
            frame = await self._next_frame()
            if frame is None:
                raise StopAsyncIteration
            event = parse_event_frame(frame)
            if event is not None:
                return event

    async def _next_frame(self) -> str | None:
        while "\n\n" not in self._buffer:
            try:
                chunk = await self._aiter.__anext__()
            except StopAsyncIteration:
                rest = self._buffer.strip()
                self._buffer = ""
                return rest or None
            if chunk:
                self._buffer += chunk.decode(self._decoder, errors="replace")
        frame, _, self._buffer = self._buffer.partition("\n\n")
        return frame

    async def collect(self) -> list[KiloEvent]:
        """Consume the whole stream and collect all events."""
        return [event async for event in self]


__all__ = [
    "KiloEvent",
    "SessionTextDelta",
    "ToolCallEvent",
    "PermissionRequestInfo",
    "EventStream",
    "is_text_delta",
    "text_delta_of",
    "tool_call_of",
    "permission_of",
    "parse_event_frame",
    "parse_events",
]
