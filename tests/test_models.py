"""Unit tests for the pydantic models (no server required)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from kilocode_client.models import (
    AgentAttachment,
    FileAttachment,
    MessagePartInput,
    MessageWithParts,
    Part,
    Prompt,
    ReferenceAttachment,
    SendMessageInput,
    SessionCreateInput,
    SessionInfo,
    SessionMessage,
    ToolPart,
    TokenUsage,
    validate_session_message,
)

from kilocode_client import (
    BadRequestError,
    Credentials,
    EventStream,
    KiloEvent,
    NotFoundError,
    client as client_mod,
)
from kilocode_client.events import parse_events, is_text_delta
from kilocode_client.exceptions import KiloHTTPError


class TestSessionModels:
    def test_sessioninfo_required_fields(self) -> None:
        session = SessionInfo(id="s1", projectID="p1", title="t", cost=0.0, tokens=None)
        assert session.id == "s1"
        assert session.cost == 0.0

    def test_sessioninfo_ignores_unknown_fields(self) -> None:
        session = SessionInfo.model_validate(
            {"id": "s1", "projectID": "p1", "title": "t", "future field": True}
        )
        assert session.title == "t"

    def test_create_input_payload(self) -> None:
        inp = SessionCreateInput(title="hi", agent="build", model={"id": "m", "providerID": "p"})
        dumped = inp.model_dump(exclude_none=True)
        assert dumped["model"] == {"id": "m", "providerID": "p"}


class TestParts:
    def test_text_part_input(self) -> None:
        part = MessagePartInput(type="text", text="hello")
        assert part.model_dump(exclude_none=True) == {"type": "text", "text": "hello"}

    def test_send_message_input(self) -> None:
        inp = SendMessageInput(
            parts=[MessagePartInput(type="text", text="x")],
            noReply=True,
        )
        assert inp.noReply is True

    def test_part_discriminator_text(self) -> None:
        adapter = TypeAdapter(Part)
        part = adapter.validate_python(
            {"id": "p", "sessionID": "s", "messageID": "m", "type": "text", "text": "hi"}
        )
        assert part.type == "text"
        assert part.text == "hi"

    def test_part_discriminator_tool(self) -> None:
        adapter = TypeAdapter(Part)
        part = adapter.validate_python(
            {
                "id": "p",
                "sessionID": "s",
                "messageID": "m",
                "type": "tool",
                "callID": "c",
                "tool": "bash",
                "state": {"status": "completed", "input": {}, "output": "ok"},
            }
        )
        assert isinstance(part, ToolPart)
        assert part.tool == "bash"
        assert part.state.status == "completed"

    def test_part_rejects_unknown_type(self) -> None:
        adapter = TypeAdapter(Part)
        with pytest.raises(ValidationError):
            adapter.validate_python(
                {"id": "p", "sessionID": "s", "messageID": "m", "type": "nope"}
            )


class TestSessionMessage:
    def test_user_message_roundtrip(self) -> None:
        msg = validate_session_message(
            {"type": "user", "id": "m", "text": "hi", "files": [], "agents": [], "references": []}
        )
        assert msg.type == "user"
        assert getattr(msg, "text", None) == "hi"

    def test_assistant_message_roundtrip(self) -> None:
        msg = validate_session_message(
            {"type": "assistant", "id": "m", "content": [{"type": "text", "text": "hi"}]}
        )
        assert msg.type == "assistant"


class TestAttachments:
    def test_prompt_builds(self) -> None:
        prompt = Prompt(
            text="do the thing",
            files=[FileAttachment(uri="file:///a.txt", mime="text/plain")],
            agents=[AgentAttachment(name="build")],
            references=[ReferenceAttachment(name="r", kind="local")],
        )
        assert prompt.text == "do the thing"
        assert prompt.files[0].uri == "file:///a.txt"


class TestTokenUsage:
    def test_cache_shape(self) -> None:
        tokens = TokenUsage.model_validate(
            {"input": 1, "output": 2, "cache": {"read": 3, "write": 4}}
        )
        assert tokens.cache == {"read": 3, "write": 4}


class TestEvents:
    def test_parse_globally_wrapped_event(self) -> None:
        text = 'data: {"directory": "/x", "payload": {"id": "1", "type": "session.turn.close", "properties": {"sessionID": "s1"}}}\n\n'
        events = parse_events(text)
        assert len(events) == 1
        e = events[0]
        assert e.type == "session.turn.close"
        assert e.directory == "/x"
        assert e.session_id == "s1"
        assert e.is_turn_close

    def test_parse_instance_event(self) -> None:
        text = 'data: {"type": "session.next.text.delta", "properties": {"delta": "hi"}}\n\n'
        events = parse_events(text)
        assert events[0].type == "session.next.text.delta"

    def test_text_delta_of_message_part_delta(self) -> None:
        from kilocode_client.events import text_delta_of

        ev = KiloEvent(
            type="message.part.delta",
            properties={"sessionID": "s1", "partID": "p1", "field": "text", "delta": "hel"},
        )
        assert is_text_delta(ev)
        # import here to satisfy the module import at top
        assert text_delta_of(ev) == "hel"

    def test_text_delta_of_part_delta_non_text_field(self) -> None:
        from kilocode_client.events import text_delta_of

        ev = KiloEvent(
            type="message.part.delta",
            properties={"field": "thinking", "delta": "zzz"},
        )
        assert not is_text_delta(ev)
        assert text_delta_of(ev) is None

    def test_text_delta_of_legacy_sync_delta(self) -> None:
        from kilocode_client.events import text_delta_of

        ev = KiloEvent(type="session.next.text.delta", properties={"delta": "yo"})
        assert text_delta_of(ev) == "yo"

    def test_keepalive_comment_ignored(self) -> None:
        text = ": keep-alive\n\n"
        assert parse_events(text) == []

    def test_kiloevent_generic(self) -> None:
        e = KiloEvent(type="custom.thing", properties={"a": 1}, id="x")
        assert e.as_dict()["type"] == "custom.thing"

    def test_eventstream_requires_bytes_async(self) -> None:
        # EventStream is an async iterator over bytes frames.
        import asyncio

        async def src() -> None:
            pass

        stream = EventStream(_async_bytes([b'data: {"type": "x"}\n\n']))
        ev = asyncio.run(stream.collect())
        assert ev[0].type == "x"


class _async_bytes:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "_async_bytes":
        return self

    async def __anext__(self) -> bytes:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class TestCredentials:
    def test_header_omitted_without_password(self, monkeypatch) -> None:
        monkeypatch.delenv("KILO_SERVER_PASSWORD", raising=False)
        monkeypatch.setenv("KILO_SERVER_USERNAME", "kilo")
        creds = client_mod.Credentials(username="kilo", password=None)
        assert creds.header_value is None

    def test_basic_auth_header(self) -> None:
        from kilocode_client import make_headers

        headers = make_headers(username="kilo", password="kilo")
        assert headers["Authorization"].startswith("Basic ")


class TestExceptions:
    def test_bad_request_mapping(self) -> None:
        from kilocode_client.exceptions import _STATUS_EXCEPTIONS

        assert _STATUS_EXCEPTIONS[400] is BadRequestError
        assert _STATUS_EXCEPTIONS[404] is NotFoundError

    def test_http_error_subclass(self) -> None:
        assert issubclass(NotFoundError, KiloHTTPError)
        assert issubclass(KiloHTTPError, Exception)