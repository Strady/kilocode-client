"""Pydantic models mirroring the Kilo server's OpenAPI schema.

The server's OpenAPI spec lives at ``./kilocode/packages/sdk/openapi.json`` and is the
source of truth for these types. They were hand-checked/derived from that spec so the
client does not drift from the server when the SDK is regenerated. Models use
``extra="ignore"`` so server-side fields added in newer versions do not break parsing.

Message `Part`/`ToolState`/`SessionMessage` are discriminated unions keyed off an
enum `type`/`status` field, expressed with pydantic v2 ``Annotated`` tags.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# Use a type alias so static checkers see plain names.
Discriminated = Any


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# --------------------------------------------------------------------------- #
# Model / provider refs
# --------------------------------------------------------------------------- #


class SessionModelRef(_Base):
    """Reference to a model used by a session or message."""

    id: str
    providerID: str
    variant: str | None = None


class ModelRef(_Base):
    """Reference to a model used in a message/command request body."""

    providerID: str
    modelID: str
    variant: str | None = None


# --------------------------------------------------------------------------- #
# Tokens & cost
# --------------------------------------------------------------------------- #


class TokenUsage(_Base):
    input: int | None = None
    output: int | None = None
    reasoning: int | None = None
    cache: dict[str, int] | None = None


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #


class TimeInfo(_Base):
    created: int = 0
    updated: int = 0
    compacting: int | None = None
    archived: float | None = None


class ShareInfo(_Base):
    url: str = ""


class SummaryInfo(_Base):
    additions: int = 0
    deletions: int = 0
    files: int = 0
    diffs: list[dict[str, Any]] = Field(default_factory=list)


class SessionInfo(_Base):
    """A Kilo session (as returned by /session)."""

    id: str
    slug: str | None = None
    projectID: str
    workspaceID: str | None = None
    directory: str | None = None
    path: str | None = None
    parentID: str | None = None
    title: str
    agent: str | None = None
    model: SessionModelRef | None = None
    version: str | None = None
    time: TimeInfo = Field(default_factory=TimeInfo)
    cost: float = 0.0
    tokens: TokenUsage | None = None
    summary: SummaryInfo | None = None
    share: ShareInfo | None = None
    permission: Any = None
    revert: Any = None


class SessionCreateInput(_Base):
    """Request body for POST /session."""

    parentID: str | None = None
    title: str | None = None
    agent: str | None = None
    model: SessionModelRef | None = None
    permission: Any = None
    platform: str | None = None
    workspaceID: str | None = None


class SessionUpdateInput(_Base):
    """Request body for PATCH /session/{id} (rename / archive)."""

    title: str | None = None
    permission: Any = None
    time: dict[str, int | None] | None = None


# --------------------------------------------------------------------------- #
# Parts (message building blocks) -- discriminated by `type`
# --------------------------------------------------------------------------- #


class TimeRange(_Base):
    start: int = 0
    end: int | None = None


class TextPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["text"] = "text"
    text: str
    synthetic: bool | None = None
    ignored: bool | None = None
    time: TimeRange | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReasoningPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["reasoning"] = "reasoning"
    text: str
    time: TimeRange | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolTime(_Base):
    start: int = 0
    end: int | None = None
    compacted: int | None = None


class ToolStatePending(_Base):
    status: Literal["pending"] = "pending"
    input: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None


class ToolStateRunning(_Base):
    status: Literal["running"] = "running"
    input: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    time: ToolTime = Field(default_factory=ToolTime)


class ToolStateCompleted(_Base):
    status: Literal["completed"] = "completed"
    input: dict[str, Any] = Field(default_factory=dict)
    output: str = ""
    title: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    time: ToolTime = Field(default_factory=ToolTime)
    attachments: list[Any] = Field(default_factory=list)


class ToolStateError(_Base):
    status: Literal["error"] = "error"
    input: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    time: ToolTime = Field(default_factory=ToolTime)


ToolState = Annotated[
    ToolStatePending | ToolStateRunning | ToolStateCompleted | ToolStateError,
    Field(discriminator="status"),
]


class ToolPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["tool"] = "tool"
    callID: str
    tool: str
    state: ToolState
    metadata: dict[str, Any] = Field(default_factory=dict)


class FilePart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["file"] = "file"
    mime: str = ""
    filename: str | None = None
    url: str = ""
    source: dict[str, Any] | None = None


class StepStartPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["step-start"] = "step-start"
    step: str | None = None


class StepFinishPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["step-finish"] = "step-finish"
    step: str | None = None


class AgentPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["agent"] = "agent"
    name: str


class RetryPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["retry"] = "retry"
    error: str | None = None


class CompactionPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["compaction"] = "compaction"
    summary: str = ""


class SnapshotPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["snapshot"] = "snapshot"
    snapshot: str | None = None


class PatchPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["patch"] = "patch"


class SubtaskPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["subtask"] = "subtask"


Part = Annotated[
    TextPart
    | ReasoningPart
    | ToolPart
    | FilePart
    | StepStartPart
    | StepFinishPart
    | AgentPart
    | RetryPart
    | CompactionPart
    | SnapshotPart
    | PatchPart
    | SubtaskPart,
    Field(discriminator="type"),
]


class Message(_Base):
    """A message info record with parts attached (GET /session/{id}/message)."""

    id: str
    sessionID: str
    role: str
    time: dict[str, int] = Field(default_factory=dict)
    error: Any = None
    parts: list[Part] = Field(default_factory=list)


class MessageWithParts(_Base):
    """Message info + parts (the element shape of GET /session/{id}/message)."""

    info: Message
    parts: list[Part] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Prompt (for sending a message, incl. file/agent/reference attachments)
# --------------------------------------------------------------------------- #


class PromptSource(_Base):
    start: float = 0
    end: float = 0
    text: str | None = None


class FileAttachment(_Base):
    uri: str
    mime: str = ""
    name: str | None = None
    description: str | None = None
    source: PromptSource | None = None


class AgentAttachment(_Base):
    name: str
    source: PromptSource | None = None


class ReferenceAttachment(_Base):
    name: str
    kind: Literal["local", "git", "invalid"] = "local"
    uri: str | None = None
    repository: str | None = None
    branch: str | None = None
    target: str | None = None
    targetUri: str | None = None
    problem: str | None = None


class Prompt(_Base):
    """The structured prompt payload for sending a message."""

    text: str
    files: list[FileAttachment] = Field(default_factory=list)
    agents: list[AgentAttachment] = Field(default_factory=list)
    references: list[ReferenceAttachment] = Field(default_factory=list)


class MessagePartInput(_Base):
    """A single part in a message send request (inline object, no id/session)."""

    type: str
    text: str | None = None
    uri: str | None = None
    mime: str | None = None
    name: str | None = None
    start: int | None = None
    end: int | None = None


class SendMessageInput(_Base):
    """Request body for POST /session/{id}/message, /command and /shell."""

    parts: list[MessagePartInput] = Field(default_factory=list)
    messageID: str | None = None
    model: ModelRef | None = None
    agent: str | None = None
    noReply: bool | None = None
    tools: dict[str, bool] | None = None
    format: Any = None
    system: str | None = None
    variant: str | None = None
    editorContext: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# SessionMessage (V2) -- discriminated by `type`
# --------------------------------------------------------------------------- #


class SessionMessageUser(_Base):
    type: Literal["user"] = "user"
    id: str
    time: dict[str, int] = Field(default_factory=dict)
    text: str
    files: list[FileAttachment] = Field(default_factory=list)
    agents: list[AgentAttachment] = Field(default_factory=list)
    references: list[ReferenceAttachment] = Field(default_factory=list)


class SessionMessageAssistant(_Base):
    type: Literal["assistant"] = "assistant"
    id: str
    time: dict[str, int] = Field(default_factory=dict)
    agent: str | None = None
    model: SessionModelRef | None = None
    content: list[Any] = Field(default_factory=list)
    snapshot: dict[str, str] | None = None
    finish: str | None = None
    cost: float | None = None
    tokens: TokenUsage | None = None


class SessionMessageSynthetic(_Base):
    type: Literal["synthetic"] = "synthetic"
    id: str
    sessionID: str
    time: dict[str, int] = Field(default_factory=dict)
    text: str = ""


class SessionMessageShell(_Base):
    type: Literal["shell"] = "shell"
    id: str
    time: dict[str, int] = Field(default_factory=dict)
    parts: list[Any] = Field(default_factory=list)


class SessionMessageCompaction(_Base):
    type: Literal["compaction"] = "compaction"
    id: str
    reason: Literal["auto", "manual"] = "auto"
    summary: str = ""
    include: str | None = None
    time: dict[str, int] = Field(default_factory=dict)


class SessionMessageAgentSwitched(_Base):
    type: Literal["agent.switched"] = "agent.switched"
    id: str
    agent: str


class SessionMessageModelSwitched(_Base):
    type: Literal["model.switched"] = "model.switched"
    id: str
    model: SessionModelRef


SessionMessage = Annotated[
    SessionMessageUser
    | SessionMessageAssistant
    | SessionMessageSynthetic
    | SessionMessageShell
    | SessionMessageCompaction
    | SessionMessageAgentSwitched
    | SessionMessageModelSwitched,
    Field(discriminator="type"),
]


class V2SessionListResponse(_Base):
    items: list[SessionInfo] = Field(default_factory=list)
    cursor: dict[str, str | None] | None = None


# --------------------------------------------------------------------------- #
# Context / todos / status
# --------------------------------------------------------------------------- #


class Todo(_Base):
    id: str
    sessionID: str
    content: str
    status: str
    time: dict[str, int] = Field(default_factory=dict)


class SessionError(_Base):
    name: str
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def message(self) -> str:
        data = self.data
        if isinstance(data, dict):
            msg = data.get("message")
            if isinstance(msg, str):
                return msg
        return self.name


# TypeAdapter for the discriminated union `SessionMessage`. Because it is an
# ``Annotated[Union[...]]`` rather than a concrete BaseModel, ``model_validate`` is
# not available -- use this helper instead (mypy-friendly).
_session_message_adapter: TypeAdapter[Any] = TypeAdapter(SessionMessage)


def validate_session_message(data: Any) -> SessionMessage:
    return cast(SessionMessage, _session_message_adapter.validate_python(data))


__all__ = [
    "SessionModelRef",
    "ModelRef",
    "TokenUsage",
    "TimeInfo",
    "ShareInfo",
    "SummaryInfo",
    "SessionInfo",
    "SessionCreateInput",
    "SessionUpdateInput",
    "TimeRange",
    "TextPart",
    "ReasoningPart",
    "ToolState",
    "ToolPart",
    "FilePart",
    "StepStartPart",
    "StepFinishPart",
    "AgentPart",
    "RetryPart",
    "CompactionPart",
    "SnapshotPart",
    "PatchPart",
    "SubtaskPart",
    "Part",
    "Message",
    "MessageWithParts",
    "PromptSource",
    "FileAttachment",
    "AgentAttachment",
    "ReferenceAttachment",
    "Prompt",
    "MessagePartInput",
    "SendMessageInput",
    "SessionMessage",
    "V2SessionListResponse",
    "Todo",
    "SessionError",
    "validate_session_message",
]
