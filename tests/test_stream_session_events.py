"""Unit tests for SSE streaming helpers (no server required).

These verify that :meth:`kilocode_client.client.Kilo.stream_session_events`
filters events down to a single session (client-side) and that the ``instance``
flag returns the unfiltered instance stream.
"""

import asyncio
from collections.abc import AsyncIterator

from kilocode_client import Kilo
from kilocode_client.events import KiloEvent


class _FakeSource:
    """Async iterator over a fixed list of events, emulating ``_stream``."""

    def __init__(self, events: list[KiloEvent]) -> None:
        self._events = list(events)

    def __aiter__(self) -> AsyncIterator[KiloEvent]:
        return self

    async def __anext__(self) -> KiloEvent:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


def _event(session_id: str | None, type_: str = "session.next.text.delta") -> KiloEvent:
    props: dict = {"sessionID": session_id} if session_id else {}
    return KiloEvent(type=type_, properties=props)


async def _collect(stream: AsyncIterator[KiloEvent]) -> list[KiloEvent]:
    return [event async for event in stream]


async def _fake_stream(events: list[KiloEvent], *args: object, **kwargs: object) -> _FakeSource:
    """Mimic ``Kilo._stream``: an awaitable that yields an async iterator."""
    return _FakeSource(events)


def _client_with_stream(monkeypatch, source_events: list[KiloEvent]) -> Kilo:
    client = Kilo()
    monkeypatch.setattr(
        client,
        "_stream",
        lambda path, **kw: _fake_stream(source_events, path, **kw),
    )
    return client


class TestStreamSessionEvents:
    def test_filters_out_other_sessions(self, monkeypatch) -> None:
        source = [_event("session-a"), _event("target"), _event("session-b"), _event("target")]

        async def run() -> None:
            client = _client_with_stream(monkeypatch, source)
            stream = await client.stream_session_events("target")
            events = await _collect(stream)
            assert [e.session_id for e in events] == ["target", "target"]

        asyncio.run(run())

    def test_returns_all_events_when_instance_true(self, monkeypatch) -> None:
        source = [_event("session-a"), _event("target"), _event("session-b")]

        async def run() -> None:
            client = _client_with_stream(monkeypatch, source)
            stream = await client.stream_session_events("target", instance=True)
            events = await _collect(stream)
            assert [e.session_id for e in events] == ["session-a", "target", "session-b"]

        asyncio.run(run())

    def test_missing_sessionid_is_skipped(self, monkeypatch) -> None:
        source = [_event("target"), _event(None), _event("target")]

        async def run() -> None:
            client = _client_with_stream(monkeypatch, source)
            stream = await client.stream_session_events("target")
            events = await _collect(stream)
            assert [e.session_id for e in events] == ["target", "target"]

        asyncio.run(run())

    def test_empty_when_no_matching_events(self, monkeypatch) -> None:
        source = [_event("session-a")]

        async def run() -> None:
            client = _client_with_stream(monkeypatch, source)
            stream = await client.stream_session_events("target")
            events = await _collect(stream)
            assert events == []

        asyncio.run(run())
