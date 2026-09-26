"""Pydantic models mirroring the Kilo server's OpenAPI schema.

The server's OpenAPI spec lives at ``./kilocode/packages/sdk/openapi.json`` and is the
source of truth for these types. They were hand-checked/derived from that spec so the
client does not drift from the server when the SDK is regenerated. Models use
``extra="ignore"`` so server-side fields added in newer versions do not break parsing.

Message `Part`/`ToolState`/`SessionMessage` are discriminated unions keyed off an
enum `type`/`status` field, expressed with pydantic v2 ``Annotated`` tags.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union, cast

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
    variant: Optional[str] = None


class ModelRef(_Base):
    """Reference to a model used in a message/command request body."""

    providerID: str
    modelID: str
    variant: Optional[str] = None


# --------------------------------------------------------------------------- #
# Tokens & cost
# --------------------------------------------------------------------------- #


class TokenUsage(_Base):
    input: Optional[int] = None
    output: Optional[int] = None
    reasoning: Optional[int] = None
    cache: Optional[Dict[str, int]] = None


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #


class TimeInfo(_Base):
    created: int = 0
    updated: int = 0
    compacting: Optional[int] = None
    archived: Optional[float] = None


class ShareInfo(_Base):
    url: str = ""


class SummaryInfo(_Base):
    additions: int = 0
    deletions: int = 0
    files: int = 0
    diffs: List[Dict[str, Any]] = Field(default_factory=list)


class SessionInfo(_Base):
    """A Kilo session (as returned by /session)."""

    id: str
    slug: Optional[str] = None
    projectID: str
    workspaceID: Optional[str] = None
    directory: Optional[str] = None
    path: Optional[str] = None
    parentID: Optional[str] = None
    title: str
    agent: Optional[str] = None
    model: Optional[SessionModelRef] = None
    version: Optional[str] = None
    time: TimeInfo = Field(default_factory=TimeInfo)
    cost: float = 0.0
    tokens: Optional[TokenUsage] = None
    summary: Optional[SummaryInfo] = None
    share: Optional[ShareInfo] = None
    permission: Any = None
    revert: Any = None


class SessionCreateInput(_Base):
    """Request body for POST /session."""

    parentID: Optional[str] = None
    title: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[SessionModelRef] = None
    permission: Any = None
    platform: Optional[str] = None
    workspaceID: Optional[str] = None


class SessionUpdateInput(_Base):
    """Request body for PATCH /session/{id} (rename / archive)."""

    title: Optional[str] = None
    permission: Any = None
    time: Optional[Dict[str, Optional[int]]] = None


# --------------------------------------------------------------------------- #
# Parts (message building blocks) -- discriminated by `type`
# --------------------------------------------------------------------------- #


class TimeRange(_Base):
    start: int = 0
    end: Optional[int] = None


class TextPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["text"] = "text"
    text: str
    synthetic: Optional[bool] = None
    ignored: Optional[bool] = None
    time: Optional[TimeRange] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReasoningPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["reasoning"] = "reasoning"
    text: str
    time: Optional[TimeRange] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolTime(_Base):
    start: int = 0
    end: Optional[int] = None
    compacted: Optional[int] = None


class ToolStatePending(_Base):
    status: Literal["pending"] = "pending"
    input: Dict[str, Any] = Field(default_factory=dict)
    title: Optional[str] = None


class ToolStateRunning(_Base):
    status: Literal["running"] = "running"
    input: Dict[str, Any] = Field(default_factory=dict)
    title: Optional[str] = None
    time: ToolTime = Field(default_factory=ToolTime)


class ToolStateCompleted(_Base):
    status: Literal["completed"] = "completed"
    input: Dict[str, Any] = Field(default_factory=dict)
    output: str = ""
    title: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    time: ToolTime = Field(default_factory=ToolTime)
    attachments: List[Any] = Field(default_factory=list)


class ToolStateError(_Base):
    status: Literal["error"] = "error"
    input: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    time: ToolTime = Field(default_factory=ToolTime)


ToolState = Annotated[
    Union[ToolStatePending, ToolStateRunning, ToolStateCompleted, ToolStateError],
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
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FilePart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["file"] = "file"
    mime: str = ""
    filename: Optional[str] = None
    url: str = ""
    source: Optional[Dict[str, Any]] = None


class StepStartPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["step-start"] = "step-start"
    step: Optional[str] = None


class StepFinishPart(_Base):
    id: str
    sessionID: str
    messageID: str
    type: Literal["step-finish"] = "step-finish"
    step: Optional[str] = None


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
    error: Optional[str] = None


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
    snapshot: Optional[str] = None


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
    Union[
        TextPart,
        ReasoningPart,
        ToolPart,
        FilePart,
        StepStartPart,
        StepFinishPart,
        AgentPart,
        RetryPart,
        CompactionPart,
        SnapshotPart,
        PatchPart,
        SubtaskPart,
    ],
    Field(discriminator="type"),
]


class Message(_Base):
    """A message info record with parts attached (GET /session/{id}/message)."""

    id: str
    sessionID: str
    role: str
    time: Dict[str, int] = Field(default_factory=dict)
    error: Any = None
    parts: List[Part] = Field(default_factory=list)


class MessageWithParts(_Base):
    """Message info + parts (the element shape of GET /session/{id}/message)."""

    info: Message
    parts: List[Part] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Prompt (for sending a message, incl. file/agent/reference attachments)
# --------------------------------------------------------------------------- #


class PromptSource(_Base):
    start: float = 0
    end: float = 0
    text: Optional[str] = None


class FileAttachment(_Base):
    uri: str
    mime: str = ""
    name: Optional[str] = None
    description: Optional[str] = None
    source: Optional[PromptSource] = None


class AgentAttachment(_Base):
    name: str
    source: Optional[PromptSource] = None


class ReferenceAttachment(_Base):
    name: str
    kind: Literal["local", "git", "invalid"] = "local"
    uri: Optional[str] = None
    repository: Optional[str] = None
    branch: Optional[str] = None
    target: Optional[str] = None
    targetUri: Optional[str] = None
    problem: Optional[str] = None


class Prompt(_Base):
    """The structured prompt payload for sending a message."""

    text: str
    files: List[FileAttachment] = Field(default_factory=list)
    agents: List[AgentAttachment] = Field(default_factory=list)
    references: List[ReferenceAttachment] = Field(default_factory=list)


class MessagePartInput(_Base):
    """A single part in a message send request (inline object, no id/session)."""

    type: str
    text: Optional[str] = None
    uri: Optional[str] = None
    mime: Optional[str] = None
    name: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None


class SendMessageInput(_Base):
    """Request body for POST /session/{id}/message, /command and /shell."""

    parts: List[MessagePartInput] = Field(default_factory=list)
    messageID: Optional[str] = None
    model: Optional[ModelRef] = None
    agent: Optional[str] = None
    noReply: Optional[bool] = None
    tools: Optional[Dict[str, bool]] = None
    format: Any = None
    system: Optional[str] = None
    variant: Optional[str] = None
    editorContext: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------- #
# SessionMessage (V2) -- discriminated by `type`
# --------------------------------------------------------------------------- #


class SessionMessageUser(_Base):
    type: Literal["user"] = "user"
    id: str
    time: Dict[str, int] = Field(default_factory=dict)
    text: str
    files: List[FileAttachment] = Field(default_factory=list)
    agents: List[AgentAttachment] = Field(default_factory=list)
    references: List[ReferenceAttachment] = Field(default_factory=list)


class SessionMessageAssistant(_Base):
    type: Literal["assistant"] = "assistant"
    id: str
    time: Dict[str, int] = Field(default_factory=dict)
    agent: Optional[str] = None
    model: Optional[SessionModelRef] = None
    content: List[Any] = Field(default_factory=list)
    snapshot: Optional[Dict[str, str]] = None
    finish: Optional[str] = None
    cost: Optional[float] = None
    tokens: Optional[TokenUsage] = None


class SessionMessageSynthetic(_Base):
    type: Literal["synthetic"] = "synthetic"
    id: str
    sessionID: str
    time: Dict[str, int] = Field(default_factory=dict)
    text: str = ""


class SessionMessageShell(_Base):
    type: Literal["shell"] = "shell"
    id: str
    time: Dict[str, int] = Field(default_factory=dict)
    parts: List[Any] = Field(default_factory=list)


class SessionMessageCompaction(_Base):
    type: Literal["compaction"] = "compaction"
    id: str
    reason: Literal["auto", "manual"] = "auto"
    summary: str = ""
    include: Optional[str] = None
    time: Dict[str, int] = Field(default_factory=dict)


class SessionMessageAgentSwitched(_Base):
    type: Literal["agent.switched"] = "agent.switched"
    id: str
    agent: str


class SessionMessageModelSwitched(_Base):
    type: Literal["model.switched"] = "model.switched"
    id: str
    model: SessionModelRef


SessionMessage = Annotated[
    Union[
        SessionMessageUser,
        SessionMessageAssistant,
        SessionMessageSynthetic,
        SessionMessageShell,
        SessionMessageCompaction,
        SessionMessageAgentSwitched,
        SessionMessageModelSwitched,
    ],
    Field(discriminator="type"),
]


class V2SessionListResponse(_Base):
    items: List[SessionInfo] = Field(default_factory=list)
    cursor: Optional[Dict[str, Optional[str]]] = None


# --------------------------------------------------------------------------- #
# Context / todos / status
# --------------------------------------------------------------------------- #


class Todo(_Base):
    id: str
    sessionID: str
    content: str
    status: str
    time: Dict[str, int] = Field(default_factory=dict)


class SessionError(_Base):
    name: str
    data: Dict[str, Any] = Field(default_factory=dict)

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