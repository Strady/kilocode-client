"""kilocode-client: programmatic access to a Kilo Code headless server (``kilo serve``).

This package mirrors the actions the Kilo TUI performs against the server's
HTTP+SSE API, exposing them as a typed Python client with both async and sync
interfaces.

Quick start (async)::

    import asyncio
    from kilocode_client import Kilo

    async def main() -> None:
        client = Kilo(base_url="http://127.0.0.1:4096")   # auth from env
        session = await client.session.create(title="demo")
        message = await client.send_prompt(session.id, "Hello, world")
        print(message.id)
        await client.close()

    asyncio.run(main())

Quick start (sync)::

    from kilocode_client import SyncKilo

    client = SyncKilo()
    session = client.session.create(title="demo")
    msg = client.send_prompt(session.id, "Hello")
    print(msg.id)
    client.close()

:class:`Kilo` is the async client; :class:`SyncKilo` is a thin synchronous wrapper
built on top of it via an event loop per instance.
"""

from __future__ import annotations

from .auth import Credentials, credentials_from_env, make_headers
from .client import Kilo
from .events import (
    EventStream,
    KiloEvent,
    PermissionRequestInfo,
    SessionTextDelta,
    ToolCallEvent,
    is_text_delta,
    parse_event_frame,
    parse_events,
    permission_of,
    text_delta_of,
    tool_call_of,
)
from .exceptions import (
    BadRequestError,
    ConsentRequiredError,
    DecodeError,
    ForbiddenError,
    KiloError,
    KiloHTTPError,
    NotFoundError,
    ServerError,
    UnauthorizedError,
)
from .models import (
    AgentAttachment,
    CompactionPart,
    FileAttachment,
    FilePart,
    Message,
    MessagePartInput,
    MessageWithParts,
    ModelRef,
    Part,
    PatchPart,
    Prompt,
    ReasoningPart,
    ReferenceAttachment,
    RetryPart,
    SendMessageInput,
    SessionInfo,
    SessionMessage,
    SessionModelRef,
    SnapshotPart,
    StepFinishPart,
    StepStartPart,
    SubtaskPart,
    TextPart,
    TimeInfo,
    TimeRange,
    Todo,
    TokenUsage,
    ToolPart,
    ToolState,
    V2SessionListResponse,
)
from .sync import SyncKilo

__all__ = [
    # client
    "Kilo",
    "SyncKilo",
    # auth
    "Credentials",
    "credentials_from_env",
    "make_headers",
    # events
    "EventStream",
    "KiloEvent",
    "PermissionRequestInfo",
    "SessionTextDelta",
    "ToolCallEvent",
    "is_text_delta",
    "parse_event_frame",
    "parse_events",
    "permission_of",
    "text_delta_of",
    "tool_call_of",
    # exceptions
    "BadRequestError",
    "ConsentRequiredError",
    "DecodeError",
    "ForbiddenError",
    "KiloError",
    "KiloHTTPError",
    "NotFoundError",
    "ServerError",
    "UnauthorizedError",
    # models
    "AgentAttachment",
    "CompactionPart",
    "FileAttachment",
    "FilePart",
    "Message",
    "MessagePartInput",
    "MessageWithParts",
    "ModelRef",
    "Part",
    "PatchPart",
    "Prompt",
    "ReasoningPart",
    "ReferenceAttachment",
    "RetryPart",
    "SendMessageInput",
    "SessionInfo",
    "SessionMessage",
    "SessionModelRef",
    "SnapshotPart",
    "StepFinishPart",
    "StepStartPart",
    "SubtaskPart",
    "TextPart",
    "TimeInfo",
    "TimeRange",
    "Todo",
    "TokenUsage",
    "ToolPart",
    "ToolState",
    "V2SessionListResponse",
]

__version__ = "0.1.0"
