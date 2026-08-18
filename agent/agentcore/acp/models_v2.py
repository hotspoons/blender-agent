# SPDX-FileCopyrightText: 2026 agentcore contributors
#
# SPDX-License-Identifier: MIT OR Apache-2.0
#
# GENERATED FILE -- DO NOT EDIT.
# Regenerate with: python -m agentcore.acp.schema.regen
# Source: ACP v2 draft schema (Apache-2.0), pinned at
#   7b160aeda86d123f37f7a9d201e642cd7ee12ef5
"""
Pydantic models for the ACP v2 draft, generated from the vendored schema.

Field names are snake_case with camelCase wire aliases, so every model must be
serialized with ``by_alias=True`` (see ``agentcore.acp.wire``).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AnyUrl, AwareDatetime, BaseModel, ConfigDict, Field, RootModel


__all__ = (
    "AbsolutePath",
    "AcceptNesNotification",
    "AgentAuthCapabilities",
    "AgentCapabilities",
    "AgentClientProtocol",
    "AgentMessage",
    "AgentNotification",
    "AgentRequest",
    "AgentResponse",
    "AgentResponse1",
    "AgentResponse2",
    "AgentThought",
    "Annotations",
    "AudioContent",
    "AuthCapabilities",
    "AuthMethod",
    "AuthMethod1",
    "AuthMethod2",
    "AuthMethod3",
    "AuthMethodAgent",
    "AuthMethodId",
    "AuthMethodTerminal",
    "AvailableCommand",
    "AvailableCommandInput",
    "AvailableCommandInput1",
    "AvailableCommandInput2",
    "AvailableCommandsUpdate",
    "BlobResourceContents",
    "BooleanPropertySchema",
    "CancelRequestNotification",
    "CancelSessionNotification",
    "ClientCapabilities",
    "ClientNesCapabilities",
    "ClientNotification",
    "ClientRequest",
    "ClientResponse",
    "ClientResponse1",
    "ClientResponse2",
    "CloseNesRequest",
    "CloseNesResponse",
    "CloseSessionRequest",
    "CloseSessionResponse",
    "CommandPermissionSubject",
    "CompleteElicitationNotification",
    "ConfigOptionUpdate",
    "ConnectMcpRequest",
    "ConnectMcpResponse",
    "Content",
    "ContentBlock",
    "ContentBlock1",
    "ContentBlock2",
    "ContentBlock3",
    "ContentBlock4",
    "ContentBlock5",
    "ContentBlock6",
    "ContentChunk",
    "Cost",
    "CreateElicitationRequest",
    "CreateElicitationRequest1",
    "CreateElicitationRequest11",
    "CreateElicitationRequest12",
    "CreateElicitationRequest13",
    "CreateElicitationRequest14",
    "CreateElicitationRequest15",
    "CreateElicitationRequest2",
    "CreateElicitationRequest21",
    "CreateElicitationRequest22",
    "CreateElicitationRequest23",
    "CreateElicitationRequest24",
    "CreateElicitationRequest25",
    "CreateElicitationRequest3",
    "CreateElicitationRequest4",
    "CreateElicitationResponse",
    "CreateElicitationResponse1",
    "CreateElicitationResponse2",
    "CreateElicitationResponse3",
    "CreateElicitationResponse4",
    "DeleteSessionRequest",
    "DeleteSessionResponse",
    "DidChangeDocumentNotification",
    "DidCloseDocumentNotification",
    "DidFocusDocumentNotification",
    "DidOpenDocumentNotification",
    "DidSaveDocumentNotification",
    "Diff",
    "DiffChange",
    "DiffChange1",
    "DiffChange2",
    "DiffChange3",
    "DiffChange4",
    "DiffChange5",
    "DiffChange6",
    "DiffFileType",
    "DiffPatch",
    "DiffPatchFormat",
    "DiffPathChange",
    "DiffPathPairChange",
    "DisableProviderRequest",
    "DisableProviderResponse",
    "DisconnectMcpRequest",
    "DisconnectMcpResponse",
    "ElicitationAcceptAction",
    "ElicitationCapabilities",
    "ElicitationContentValue",
    "ElicitationFormCapabilities",
    "ElicitationFormMode",
    "ElicitationFormMode1",
    "ElicitationFormMode2",
    "ElicitationId",
    "ElicitationPropertySchema",
    "ElicitationPropertySchema1",
    "ElicitationPropertySchema2",
    "ElicitationPropertySchema3",
    "ElicitationPropertySchema4",
    "ElicitationPropertySchema5",
    "ElicitationPropertySchema6",
    "ElicitationRequestScope",
    "ElicitationSchema",
    "ElicitationSchemaType",
    "ElicitationSessionScope",
    "ElicitationUrlCapabilities",
    "ElicitationUrlMode",
    "ElicitationUrlMode1",
    "ElicitationUrlMode2",
    "EmbeddedResource",
    "EmbeddedResourceResource",
    "EnumOption",
    "EnvVariable",
    "Error",
    "ErrorCode",
    "ExtNotification",
    "ExtRequest",
    "ExtResponse",
    "ForkSessionRequest",
    "ForkSessionResponse",
    "HttpHeader",
    "Icon",
    "IconTheme",
    "IdleStateUpdate",
    "ImageContent",
    "Implementation",
    "InitializeRequest",
    "InitializeResponse",
    "IntegerPropertySchema",
    "ListProvidersRequest",
    "ListProvidersResponse",
    "ListSessionsRequest",
    "ListSessionsResponse",
    "LlmProtocol",
    "LoginAuthRequest",
    "LoginAuthResponse",
    "LogoutAuthRequest",
    "LogoutAuthResponse",
    "McpAcpCapabilities",
    "McpCapabilities",
    "McpConnectionId",
    "McpHttpCapabilities",
    "McpServer",
    "McpServer1",
    "McpServer2",
    "McpServer3",
    "McpServer4",
    "McpServerAcp",
    "McpServerAcpId",
    "McpServerHttp",
    "McpServerStdio",
    "McpStdioCapabilities",
    "MediaType",
    "MessageId",
    "MessageMcpNotification",
    "MessageMcpRequest",
    "MessageMcpResponse",
    "MultiSelectItems",
    "MultiSelectItems1",
    "MultiSelectItems2",
    "MultiSelectPropertySchema",
    "NesCapabilities",
    "NesContextCapabilities",
    "NesDiagnostic",
    "NesDiagnosticSeverity",
    "NesDiagnosticsCapabilities",
    "NesDocumentDidChangeCapabilities",
    "NesDocumentDidCloseCapabilities",
    "NesDocumentDidFocusCapabilities",
    "NesDocumentDidOpenCapabilities",
    "NesDocumentDidSaveCapabilities",
    "NesDocumentEventCapabilities",
    "NesEditHistoryCapabilities",
    "NesEditHistoryEntry",
    "NesEditSuggestion",
    "NesEventCapabilities",
    "NesExcerpt",
    "NesJumpCapabilities",
    "NesJumpSuggestion",
    "NesOpenFile",
    "NesOpenFilesCapabilities",
    "NesRecentFile",
    "NesRecentFilesCapabilities",
    "NesRejectReason",
    "NesRelatedSnippet",
    "NesRelatedSnippetsCapabilities",
    "NesRenameCapabilities",
    "NesRenameSuggestion",
    "NesRepository",
    "NesSearchAndReplaceCapabilities",
    "NesSearchAndReplaceSuggestion",
    "NesSuggestContext",
    "NesSuggestion",
    "NesSuggestion1",
    "NesSuggestion2",
    "NesSuggestion3",
    "NesSuggestion4",
    "NesSuggestion5",
    "NesSuggestionId",
    "NesTextEdit",
    "NesTriggerKind",
    "NesUserAction",
    "NesUserActionsCapabilities",
    "NewSessionRequest",
    "NewSessionResponse",
    "NumberPropertySchema",
    "PermissionOption",
    "PermissionOptionId",
    "PermissionOptionKind",
    "PlanEntry",
    "PlanEntryPriority",
    "PlanEntryStatus",
    "PlanFile",
    "PlanId",
    "PlanItems",
    "PlanMarkdown",
    "PlanRemoved",
    "PlanUpdate",
    "PlanUpdateContent",
    "PlanUpdateContent1",
    "PlanUpdateContent2",
    "PlanUpdateContent3",
    "PlanUpdateContent4",
    "Position",
    "PositionEncodingKind",
    "PromptAudioCapabilities",
    "PromptCapabilities",
    "PromptEmbeddedContextCapabilities",
    "PromptImageCapabilities",
    "PromptRequest",
    "PromptResponse",
    "ProtocolLevelNotification",
    "ProtocolVersion",
    "ProviderCurrentConfig",
    "ProviderId",
    "ProviderInfo",
    "ProvidersCapabilities",
    "Range",
    "RejectNesNotification",
    "ReplayFrom",
    "ReplayFrom1",
    "ReplayFrom2",
    "ReplayFromStart",
    "RequestId",
    "RequestPermissionOutcome",
    "RequestPermissionOutcome1",
    "RequestPermissionOutcome2",
    "RequestPermissionOutcome3",
    "RequestPermissionRequest",
    "RequestPermissionResponse",
    "RequestPermissionSubject",
    "RequestPermissionSubject1",
    "RequestPermissionSubject2",
    "RequestPermissionSubject3",
    "RequiresActionStateUpdate",
    "ResourceLink",
    "ResumeSessionRequest",
    "ResumeSessionResponse",
    "Role",
    "RunningStateUpdate",
    "SelectedPermissionOutcome",
    "SessionAdditionalDirectoriesCapabilities",
    "SessionCapabilities",
    "SessionConfigBoolean",
    "SessionConfigGroupId",
    "SessionConfigId",
    "SessionConfigOption",
    "SessionConfigOption1",
    "SessionConfigOption2",
    "SessionConfigOption3",
    "SessionConfigOptionCategory",
    "SessionConfigSelect",
    "SessionConfigSelectGroup",
    "SessionConfigSelectOption",
    "SessionConfigSelectOptions",
    "SessionConfigValueId",
    "SessionDeleteCapabilities",
    "SessionForkCapabilities",
    "SessionId",
    "SessionInfo",
    "SessionInfoUpdate",
    "SessionListCursor",
    "SessionUpdate",
    "SessionUpdate1",
    "SessionUpdate10",
    "SessionUpdate11",
    "SessionUpdate12",
    "SessionUpdate13",
    "SessionUpdate14",
    "SessionUpdate15",
    "SessionUpdate16",
    "SessionUpdate17",
    "SessionUpdate18",
    "SessionUpdate2",
    "SessionUpdate3",
    "SessionUpdate4",
    "SessionUpdate5",
    "SessionUpdate6",
    "SessionUpdate7",
    "SessionUpdate71",
    "SessionUpdate72",
    "SessionUpdate73",
    "SessionUpdate74",
    "SessionUpdate75",
    "SessionUpdate76",
    "SessionUpdate77",
    "SessionUpdate78",
    "SessionUpdate79",
    "SessionUpdate8",
    "SessionUpdate9",
    "SetProviderRequest",
    "SetProviderResponse",
    "SetSessionConfigOptionRequest",
    "SetSessionConfigOptionRequest1",
    "SetSessionConfigOptionRequest2",
    "SetSessionConfigOptionRequest3",
    "SetSessionConfigOptionResponse",
    "StartNesRequest",
    "StartNesResponse",
    "StateUpdate",
    "StateUpdate1",
    "StateUpdate2",
    "StateUpdate3",
    "StateUpdate4",
    "StopReason",
    "StringFormat",
    "StringMultiSelectItems",
    "StringPropertySchema",
    "SuggestNesRequest",
    "SuggestNesResponse",
    "Terminal",
    "TerminalAuthCapabilities",
    "TerminalExitStatus",
    "TerminalId",
    "TerminalOutput",
    "TerminalOutputChunk",
    "TerminalUpdate",
    "TextCommandInput",
    "TextContent",
    "TextDocumentContentChangeEvent",
    "TextDocumentSyncKind",
    "TextResourceContents",
    "TitledMultiSelectItems",
    "ToolCallContent",
    "ToolCallContent1",
    "ToolCallContent2",
    "ToolCallContent3",
    "ToolCallContent4",
    "ToolCallContentChunk",
    "ToolCallId",
    "ToolCallLocation",
    "ToolCallPermissionSubject",
    "ToolCallStatus",
    "ToolCallUpdate",
    "ToolKind",
    "UpdateSessionNotification",
    "Usage",
    "UsageUpdate",
    "UserMessage",
    "WorkspaceFolder",
)


class AgentClientProtocol(RootModel[Any]):
    root: Annotated[Any, Field(title='Agent Client Protocol')]


class RequestId(RootModel[int | str | None]):
    root: Annotated[
        int | str | None,
        Field(
            description='JSON RPC Request Id\n\nAn identifier established by the Client that MUST contain a String, Number, or NULL value if included. If it is not included it is assumed to be a notification. The value SHOULD normally not be Null \\[1\\] and Numbers SHOULD NOT contain fractional parts \\[2\\]\n\nThe Server MUST reply with the same value in the Response object if included. This member is used to correlate the context between the two objects.\n\n\\[1\\] The use of Null as a value for the id member in a Request object is discouraged, because this specification uses a value of Null for Responses with an unknown id. Also, because JSON-RPC 1.0 uses an id value of Null for Notifications this could cause confusion in handling.\n\n\\[2\\] Fractional parts may be problematic, since many decimal fractions cannot be represented exactly as binary fractions.'
        ),
    ]


class SessionId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='A unique identifier for a conversation session between a client and agent.\n\nSessions maintain their own context, conversation history, and state,\nallowing multiple independent interactions with the same agent.\n\nSee protocol docs: [Session ID](https://agentclientprotocol.com/protocol/v2/draft/session-setup#session-id)'
        ),
    ]


class RequestPermissionSubject3(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future permission subject type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class ToolCallId(RootModel[str]):
    root: Annotated[
        str, Field(description='Unique identifier for a tool call within a session.')
    ]


class ToolKind(
    RootModel[
        Literal['read']
        | Literal['edit']
        | Literal['delete']
        | Literal['move']
        | Literal['search']
        | Literal['execute']
        | Literal['think']
        | Literal['fetch']
        | Literal['switch_mode']
        | Literal['other']
        | str
    ]
):
    root: Annotated[
        Literal['read']
        | Literal['edit']
        | Literal['delete']
        | Literal['move']
        | Literal['search']
        | Literal['execute']
        | Literal['think']
        | Literal['fetch']
        | Literal['switch_mode']
        | Literal['other']
        | str,
        Field(
            description='Categories of tools that can be invoked.\n\nTool kinds help clients choose appropriate icons and optimize how they\ndisplay tool execution progress.\n\nSee protocol docs: [Creating](https://agentclientprotocol.com/protocol/v2/draft/tool-calls#creating)'
        ),
    ]


class ToolCallStatus(
    RootModel[
        Literal['pending']
        | Literal['in_progress']
        | Literal['completed']
        | Literal['failed']
        | Literal['cancelled']
        | str
    ]
):
    root: Annotated[
        Literal['pending']
        | Literal['in_progress']
        | Literal['completed']
        | Literal['failed']
        | Literal['cancelled']
        | str,
        Field(
            description='Execution status of a tool call.\n\nTool calls progress through different statuses during their lifecycle.\n\nSee protocol docs: [Status](https://agentclientprotocol.com/protocol/v2/draft/tool-calls#status)'
        ),
    ]


class ToolCallContent4(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future tool call content type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class ContentBlock6(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future content block type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class Role(RootModel[Literal['assistant'] | Literal['user'] | str]):
    root: Annotated[
        Literal['assistant'] | Literal['user'] | str,
        Field(
            description='The sender or recipient of messages and data in a conversation.'
        ),
    ]


class MediaType(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='An Internet media type identifying the format of protocol content.'
        ),
    ]


class IconTheme(RootModel[Literal['light'] | Literal['dark'] | str]):
    root: Annotated[
        Literal['light'] | Literal['dark'] | str,
        Field(description='Theme an icon is designed for.'),
    ]


class TextResourceContents(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    text: Annotated[
        str, Field(description='Text payload carried by this content block.')
    ]
    uri: Annotated[
        AnyUrl, Field(description='URI associated with this resource or media payload.')
    ]
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type describing the encoded media payload.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class BlobResourceContents(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    blob: Annotated[
        str,
        Field(
            description='Base64-encoded bytes for a binary resource payload.',
            json_schema_extra={'contentEncoding': 'base64'},
        ),
    ]
    uri: Annotated[
        AnyUrl, Field(description='URI associated with this resource or media payload.')
    ]
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type describing the encoded media payload.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DiffFileType(
    RootModel[
        Literal['text']
        | Literal['binary']
        | Literal['directory']
        | Literal['symlink']
        | str
    ]
):
    root: Annotated[
        Literal['text']
        | Literal['binary']
        | Literal['directory']
        | Literal['symlink']
        | str,
        Field(description='Kind of file content represented by a diff change.'),
    ]


class AbsolutePath(RootModel[str]):
    root: Annotated[
        str, Field(description='An absolute filesystem path used by the protocol.')
    ]


class DiffPathChange(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    path: Annotated[AbsolutePath, Field(description='Absolute path for the operation.')]


class DiffPathPairChange(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    old_path: Annotated[
        AbsolutePath,
        Field(alias='oldPath', description='Absolute path before the operation.'),
    ]
    path: Annotated[
        AbsolutePath, Field(description='Absolute path after the operation.')
    ]


class DiffPatchFormat(RootModel[Literal['git_patch'] | str]):
    root: Annotated[
        Literal['git_patch'] | str,
        Field(description='Text patch format used by [`DiffPatch`].'),
    ]


class TerminalId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='Unique identifier for an agent-owned terminal within a session.'
        ),
    ]


class Terminal(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    terminal_id: Annotated[
        TerminalId,
        Field(alias='terminalId', description='The ID of the terminal to display.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. This metadata is scoped to the content reference. Omitted\nand `null` are equivalent and mean no item metadata was provided.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ToolCallLocation(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    path: Annotated[
        AbsolutePath,
        Field(description='The absolute file path being accessed or modified.'),
    ]
    line: Annotated[
        int | None, Field(description='Optional line number within the file.', ge=0)
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class CommandPermissionSubject(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    command: Annotated[
        str,
        Field(description='The command that would be run if permission is granted.'),
    ]
    cwd: Annotated[
        AbsolutePath,
        Field(description='The absolute working directory for the command.'),
    ]
    tool_call_id: Annotated[
        ToolCallId | None,
        Field(
            alias='toolCallId',
            description='The associated tool call, when known. Omitted and `null` are equivalent.',
        ),
    ] = None
    terminal_id: Annotated[
        TerminalId | None,
        Field(
            alias='terminalId',
            description='The associated terminal, when already known. Omitted and `null` are equivalent.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. Omitted and `null` are equivalent and mean no subject metadata was provided.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PermissionOptionId(RootModel[str]):
    root: Annotated[
        str, Field(description='Unique identifier for a permission option.')
    ]


class PermissionOptionKind(
    RootModel[
        Literal['allow_once']
        | Literal['allow_always']
        | Literal['reject_once']
        | Literal['reject_always']
        | str
    ]
):
    root: Annotated[
        Literal['allow_once']
        | Literal['allow_always']
        | Literal['reject_once']
        | Literal['reject_always']
        | str,
        Field(
            description='The type of permission option being presented to the user.\n\nHelps clients choose appropriate icons and UI treatment.'
        ),
    ]


class CreateElicitationRequest13(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message: Annotated[
        str,
        Field(description='A human-readable message describing what input is needed.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    mode: Literal['form']


class CreateElicitationRequest23(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message: Annotated[
        str,
        Field(description='A human-readable message describing what input is needed.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    mode: Literal['url']


class ElicitationSessionScope(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId', description='The session this elicitation is tied to.'
        ),
    ]
    tool_call_id: Annotated[
        ToolCallId | None,
        Field(
            alias='toolCallId',
            description='Optional tool call within the session.\n\nOptional. Omitted and `null` are equivalent and mean the elicitation is scoped to the\nsession without a specific tool call.',
        ),
    ] = None


class ElicitationRequestScope(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    request_id: Annotated[
        RequestId | None,
        Field(
            alias='requestId', description='The request this elicitation is tied to.'
        ),
    ]


class ElicitationSchemaType(Enum):
    object = 'object'


class ElicitationPropertySchema6(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future elicitation property schema type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class StringFormat(
    RootModel[
        Literal['email'] | Literal['uri'] | Literal['date'] | Literal['date-time'] | str
    ]
):
    root: Annotated[
        Literal['email']
        | Literal['uri']
        | Literal['date']
        | Literal['date-time']
        | str,
        Field(
            description='String format types for string properties in elicitation schemas.'
        ),
    ]


class EnumOption(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    const: Annotated[str, Field(description='The constant value for this option.')]
    title: Annotated[str, Field(description='Human-readable title for this option.')]
    description: Annotated[
        str | None,
        Field(
            description='Human-readable description.\n\nOptional. Omitted and `null` are equivalent and mean no description is provided.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class StringPropertySchema(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    title: Annotated[
        str | None,
        Field(
            description='Optional title for the property.\n\nOptional. Omitted and `null` are equivalent and mean no title is provided.'
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(
            description='Human-readable description.\n\nOptional. Omitted and `null` are equivalent and mean no description is provided.'
        ),
    ] = None
    min_length: Annotated[
        int | None,
        Field(
            alias='minLength',
            description='Minimum string length.\n\nOptional. Omitted and `null` are equivalent and mean there is no minimum length constraint.',
            ge=0,
        ),
    ] = None
    max_length: Annotated[
        int | None,
        Field(
            alias='maxLength',
            description='Maximum string length.\n\nOptional. Omitted and `null` are equivalent and mean there is no maximum length constraint.',
            ge=0,
        ),
    ] = None
    pattern: Annotated[
        str | None,
        Field(
            description='Pattern the string must match.\n\nOptional. Omitted and `null` are equivalent and mean there is no pattern constraint.'
        ),
    ] = None
    format: Annotated[
        StringFormat | None,
        Field(
            description='String format.\n\nOptional. Omitted and `null` are equivalent and mean there is no format constraint.'
        ),
    ] = None
    default: Annotated[
        str | None,
        Field(
            description='Default value.\n\nOptional. Omitted and `null` are equivalent and mean no default value is provided.'
        ),
    ] = None
    enum: Annotated[
        list[str] | None,
        Field(
            description='Enum values for untitled single-select enums.\nMust contain at least one value when present.\nOptional. Omitted and `null` are equivalent and mean no untitled single-select choices are\ndeclared by `enum`.',
            min_length=1,
        ),
    ] = None
    one_of: Annotated[
        list[EnumOption] | None,
        Field(
            alias='oneOf',
            description='Titled enum options for titled single-select enums.\nMust contain at least one option when present.\nOptional. Omitted and `null` are equivalent and mean no titled single-select choices are\ndeclared by `oneOf`.',
            min_length=1,
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NumberPropertySchema(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    title: Annotated[
        str | None,
        Field(
            description='Optional title for the property.\n\nOptional. Omitted and `null` are equivalent and mean no title is provided.'
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(
            description='Human-readable description.\n\nOptional. Omitted and `null` are equivalent and mean no description is provided.'
        ),
    ] = None
    minimum: Annotated[
        float | None,
        Field(
            description='Minimum value (inclusive).\n\nOptional. Omitted and `null` are equivalent and mean there is no inclusive lower bound.'
        ),
    ] = None
    maximum: Annotated[
        float | None,
        Field(
            description='Maximum value (inclusive).\n\nOptional. Omitted and `null` are equivalent and mean there is no inclusive upper bound.'
        ),
    ] = None
    default: Annotated[
        float | None,
        Field(
            description='Default value.\n\nOptional. Omitted and `null` are equivalent and mean no default value is provided.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class IntegerPropertySchema(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    title: Annotated[
        str | None,
        Field(
            description='Optional title for the property.\n\nOptional. Omitted and `null` are equivalent and mean no title is provided.'
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(
            description='Human-readable description.\n\nOptional. Omitted and `null` are equivalent and mean no description is provided.'
        ),
    ] = None
    minimum: Annotated[
        int | None,
        Field(
            description='Minimum value (inclusive).\n\nOptional. Omitted and `null` are equivalent and mean there is no inclusive lower bound.'
        ),
    ] = None
    maximum: Annotated[
        int | None,
        Field(
            description='Maximum value (inclusive).\n\nOptional. Omitted and `null` are equivalent and mean there is no inclusive upper bound.'
        ),
    ] = None
    default: Annotated[
        int | None,
        Field(
            description='Default value.\n\nOptional. Omitted and `null` are equivalent and mean no default value is provided.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class BooleanPropertySchema(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    title: Annotated[
        str | None,
        Field(
            description='Optional title for the property.\n\nOptional. Omitted and `null` are equivalent and mean no title is provided.'
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(
            description='Human-readable description.\n\nOptional. Omitted and `null` are equivalent and mean no description is provided.'
        ),
    ] = None
    default: Annotated[
        bool | None,
        Field(
            description='Default value.\n\nOptional. Omitted and `null` are equivalent and mean no default value is provided.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class MultiSelectItems2(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future multi-select item type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class StringMultiSelectItems(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    enum: Annotated[
        list[str],
        Field(
            description='Allowed enum values. Must contain at least one value.',
            min_length=1,
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class TitledMultiSelectItems(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    any_of: Annotated[
        list[EnumOption],
        Field(
            alias='anyOf',
            description='Titled enum options. Must contain at least one option.',
            min_length=1,
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ElicitationId(RootModel[str]):
    root: Annotated[str, Field(description='Unique identifier for an elicitation.')]


class ElicitationUrlMode1(ElicitationSessionScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    elicitation_id: Annotated[
        ElicitationId,
        Field(
            alias='elicitationId',
            description='The unique identifier for this elicitation.',
        ),
    ]
    url: Annotated[AnyUrl, Field(description='The URL to direct the user to.')]


class ElicitationUrlMode2(ElicitationRequestScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    elicitation_id: Annotated[
        ElicitationId,
        Field(
            alias='elicitationId',
            description='The unique identifier for this elicitation.',
        ),
    ]
    url: Annotated[AnyUrl, Field(description='The URL to direct the user to.')]


class ElicitationUrlMode(RootModel[ElicitationUrlMode1 | ElicitationUrlMode2]):
    root: Annotated[
        ElicitationUrlMode1 | ElicitationUrlMode2,
        Field(
            description='URL-based elicitation mode where the client directs the user to a URL.'
        ),
    ]


class McpServerAcpId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nUnique identifier for an MCP server using the ACP transport.\n\nThe value is opaque and generated by the ACP component providing the MCP server. It is\nused by `mcp/connect` to route connection requests back to the component that declared the\nserver.'
        ),
    ]


class McpConnectionId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nA unique identifier for an active MCP-over-ACP connection.'
        ),
    ]


class DisconnectMcpRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    connection_id: Annotated[
        McpConnectionId,
        Field(
            alias='connectionId', description='The MCP-over-ACP connection to close.'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ExtRequest(RootModel[Any]):
    root: Annotated[
        Any,
        Field(
            description='Allows for sending an arbitrary request that is not part of the ACP spec.\nExtension methods provide a way to add custom functionality while maintaining\nprotocol compatibility.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)'
        ),
    ]


class ProtocolVersion(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description='Protocol version identifier.\n\nThis version is only bumped for breaking changes.\nNon-breaking changes should be introduced via capabilities.',
            ge=0,
            le=65535,
        ),
    ]


class Implementation(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[
        str,
        Field(
            description='Intended for programmatic or logical use, but can be used as a display\nname fallback if title isn’t present.'
        ),
    ]
    title: Annotated[
        str | None,
        Field(
            description='Intended for UI and end-user contexts — optimized to be human-readable\nand easily understood.\n\nIf not provided, the name should be used for display.'
        ),
    ] = None
    version: Annotated[
        str,
        Field(
            description='Version of the implementation. Can be displayed to the user or used\nfor debugging or metrics purposes. (e.g. "1.0.0").'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PromptImageCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PromptAudioCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PromptEmbeddedContextCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpStdioCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpHttpCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpAcpCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionDeleteCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionAdditionalDirectoriesCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionForkCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AgentAuthCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ProvidersCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesDocumentDidOpenCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class TextDocumentSyncKind(Enum):
    full = 'full'
    incremental = 'incremental'


class NesDocumentDidCloseCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesDocumentDidSaveCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesDocumentDidFocusCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesRecentFilesCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    max_count: Annotated[
        int | None,
        Field(
            alias='maxCount',
            description='Maximum number of recent files the agent can use.',
            ge=0,
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesRelatedSnippetsCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesEditHistoryCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    max_count: Annotated[
        int | None,
        Field(
            alias='maxCount',
            description='Maximum number of edit history entries the agent can use.',
            ge=0,
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesUserActionsCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    max_count: Annotated[
        int | None,
        Field(
            alias='maxCount',
            description='Maximum number of user actions the agent can use.',
            ge=0,
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesOpenFilesCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesDiagnosticsCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PositionEncodingKind(Enum):
    utf_16 = 'utf-16'
    utf_32 = 'utf-32'
    utf_8 = 'utf-8'


class AuthMethodId(RootModel[str]):
    root: Annotated[
        str,
        Field(description='Typed identifier used for auth method values on the wire.'),
    ]


class EnvVariable(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[str, Field(description='The name of the environment variable.')]
    value: Annotated[
        str, Field(description='The value to set for the environment variable.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AuthMethodTerminal(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    method_id: Annotated[
        AuthMethodId,
        Field(
            alias='methodId',
            description='Unique identifier for this authentication method.',
        ),
    ]
    name: Annotated[
        str, Field(description='Human-readable name of the authentication method.')
    ]
    description: Annotated[
        str | None,
        Field(
            description='Optional description providing more details about this authentication method.'
        ),
    ] = None
    args: Annotated[
        list[str] | None,
        Field(
            description='Additional arguments to append to the configured agent invocation for terminal auth.'
        ),
    ] = None
    env: Annotated[
        list[EnvVariable] | None,
        Field(
            description='Additional environment variables to set on the configured agent invocation for terminal auth.\nNames MUST be unique. These values override same-named variables in the\nbase launch configuration.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AuthMethodAgent(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    method_id: Annotated[
        AuthMethodId,
        Field(
            alias='methodId',
            description='Unique identifier for this authentication method.',
        ),
    ]
    name: Annotated[
        str, Field(description='Human-readable name of the authentication method.')
    ]
    description: Annotated[
        str | None,
        Field(
            description='Optional description providing more details about this authentication method.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class LoginAuthResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ProviderId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nUnique identifier for a configurable LLM provider.'
        ),
    ]


class LlmProtocol(
    RootModel[
        Literal['anthropic']
        | Literal['openai']
        | Literal['azure']
        | Literal['vertex']
        | Literal['bedrock']
        | str
    ]
):
    root: Annotated[
        Literal['anthropic']
        | Literal['openai']
        | Literal['azure']
        | Literal['vertex']
        | Literal['bedrock']
        | str,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nWell-known API protocol identifiers for LLM providers.\n\nAgents and clients MUST handle unknown protocol identifiers gracefully.\n\nProtocol names beginning with `_` are free for custom use, like other ACP extension methods.\nProtocol names that do not begin with `_` are reserved for the ACP spec.'
        ),
    ]


class ProviderCurrentConfig(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    api_type: Annotated[
        LlmProtocol,
        Field(alias='apiType', description='Protocol currently used by this provider.'),
    ]
    base_url: Annotated[
        AnyUrl,
        Field(alias='baseUrl', description='Base URL currently used by this provider.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SetProviderResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DisableProviderResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class LogoutAuthResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionConfigId(RootModel[str]):
    root: Annotated[
        str, Field(description='Unique identifier for a session configuration option.')
    ]


class SessionConfigOptionCategory(
    RootModel[
        Literal['mode']
        | Literal['model']
        | Literal['model_config']
        | Literal['thought_level']
        | str
    ]
):
    root: Annotated[
        Literal['mode']
        | Literal['model']
        | Literal['model_config']
        | Literal['thought_level']
        | str,
        Field(
            description='Semantic category for a session configuration option.\n\nThis is intended to help Clients distinguish broadly common selectors (e.g. model selector vs\nsession mode selector vs thought/reasoning level) for UX purposes (keyboard shortcuts, icons,\nplacement). It MUST NOT be required for correctness. Clients MUST handle missing or unknown\ncategories gracefully.\n\nCategory names beginning with `_` are free for custom use, like other ACP extension methods.\nCategory names that do not begin with `_` are reserved for the ACP spec.'
        ),
    ]


class SessionConfigValueId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='Unique identifier for a session configuration option value.'
        ),
    ]


class SessionConfigSelectOption(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    value: Annotated[
        SessionConfigValueId,
        Field(description='Unique identifier for this option value.'),
    ]
    name: Annotated[
        str, Field(description='Human-readable label for this option value.')
    ]
    description: Annotated[
        str | None, Field(description='Optional description for this option value.')
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionConfigGroupId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='Unique identifier for a session configuration option value group.'
        ),
    ]


class SessionConfigBoolean(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    current_value: Annotated[
        bool,
        Field(
            alias='currentValue', description='The current value of the boolean option.'
        ),
    ]


class SessionInfo(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='Unique identifier for the session'),
    ]
    cwd: Annotated[
        AbsolutePath,
        Field(
            description='The working directory for this session. Must be an absolute path.'
        ),
    ]
    additional_directories: Annotated[
        list[AbsolutePath] | None,
        Field(
            alias='additionalDirectories',
            description='Additional workspace roots reported for this session. Each path must be absolute.\n\nWhen present, this is the complete ordered additional-root list reported\nby the Agent. Omitted and empty values are equivalent: the response\nreports no additional roots.',
        ),
    ] = None
    title: Annotated[
        str | None, Field(description='Human-readable title for the session')
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(alias='updatedAt', description='RFC 3339 timestamp of last activity.'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionListCursor(RootModel[str]):
    root: Annotated[
        str,
        Field(description='An opaque cursor used to paginate `session/list` results.'),
    ]


class DeleteSessionResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class CloseSessionResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PromptResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class StartNesResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='The session ID for the newly started NES session.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesSuggestionId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nUnique identifier for an NES suggestion.'
        ),
    ]


class Position(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    line: Annotated[int, Field(description='Zero-based line number.', ge=0)]
    character: Annotated[
        int,
        Field(description='Zero-based character offset (encoding-dependent).', ge=0),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesJumpSuggestion(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    suggestion_id: Annotated[
        NesSuggestionId,
        Field(
            alias='suggestionId',
            description='Unique identifier for accept/reject tracking.',
        ),
    ]
    uri: Annotated[AnyUrl, Field(description='The file to navigate to.')]
    position: Annotated[
        Position, Field(description='The target position within the file.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesRenameSuggestion(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    suggestion_id: Annotated[
        NesSuggestionId,
        Field(
            alias='suggestionId',
            description='Unique identifier for accept/reject tracking.',
        ),
    ]
    uri: Annotated[AnyUrl, Field(description='The file URI containing the symbol.')]
    position: Annotated[
        Position, Field(description='The position of the symbol to rename.')
    ]
    new_name: Annotated[
        str, Field(alias='newName', description='The new name for the symbol.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesSearchAndReplaceSuggestion(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    suggestion_id: Annotated[
        NesSuggestionId,
        Field(
            alias='suggestionId',
            description='Unique identifier for accept/reject tracking.',
        ),
    ]
    uri: Annotated[AnyUrl, Field(description='The file URI to search within.')]
    search: Annotated[str, Field(description='The text or pattern to find.')]
    replace: Annotated[str, Field(description='The replacement text.')]
    is_regex: Annotated[
        bool | None,
        Field(
            alias='isRegex',
            description='Whether `search` is a regular expression. Defaults to `false`.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class CloseNesResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ExtResponse(RootModel[Any]):
    root: Annotated[
        Any,
        Field(
            description='Allows for sending an arbitrary response to an [`ExtRequest`] that is not part of the ACP spec.\nExtension methods provide a way to add custom functionality while maintaining\nprotocol compatibility.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)'
        ),
    ]


class MessageMcpResponse(RootModel[Any]):
    root: Annotated[
        Any,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nResponse to `mcp/message`.\n\nThis is the inner MCP response result payload. Any JSON value is valid.'
        ),
    ]


class ErrorCode(
    RootModel[
        Literal[-32700]
        | Literal[-32600]
        | Literal[-32601]
        | Literal[-32602]
        | Literal[-32603]
        | Literal[-32800]
        | Literal[-32000]
        | Literal[-32002]
        | int
    ]
):
    root: Annotated[
        Literal[-32700]
        | Literal[-32600]
        | Literal[-32601]
        | Literal[-32602]
        | Literal[-32603]
        | Literal[-32800]
        | Literal[-32000]
        | Literal[-32002]
        | int,
        Field(
            description='Predefined error codes for common JSON-RPC and ACP-specific errors.\n\nThese codes follow the JSON-RPC 2.0 specification for standard errors\nand use the reserved range (-32000 to -32099) for protocol-specific errors.'
        ),
    ]


class SessionUpdate74(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    state: Annotated[
        str,
        Field(
            description='Custom or future session state.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class SessionUpdate75(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['state_update'], Field(alias='sessionUpdate')]


class SessionUpdate79(SessionUpdate74, SessionUpdate75):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['state_update'], Field(alias='sessionUpdate')]


class SessionUpdate18(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        str,
        Field(
            alias='sessionUpdate',
            description='Custom or future session update type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.',
        ),
    ]


class MessageId(RootModel[str]):
    root: Annotated[
        str, Field(description='Unique identifier for a message within a session.')
    ]


class RunningStateUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class StopReason(
    RootModel[
        Literal['end_turn']
        | Literal['max_tokens']
        | Literal['max_turn_requests']
        | Literal['refusal']
        | Literal['cancelled']
        | str
    ]
):
    root: Annotated[
        Literal['end_turn']
        | Literal['max_tokens']
        | Literal['max_turn_requests']
        | Literal['refusal']
        | Literal['cancelled']
        | str,
        Field(
            description='Reasons why an agent stops active session work.\n\nSee protocol docs: [Stop Reasons](https://agentclientprotocol.com/protocol/v2/draft/prompt-lifecycle#stop-reasons)'
        ),
    ]


class Usage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    total_tokens: Annotated[
        int,
        Field(
            alias='totalTokens',
            description='Sum of all token types across session.',
            ge=0,
        ),
    ]
    input_tokens: Annotated[
        int, Field(alias='inputTokens', description='Total input tokens.', ge=0)
    ]
    output_tokens: Annotated[
        int, Field(alias='outputTokens', description='Total output tokens.', ge=0)
    ]
    thought_tokens: Annotated[
        int | None,
        Field(
            alias='thoughtTokens', description='Total thought/reasoning tokens', ge=0
        ),
    ] = None
    cached_read_tokens: Annotated[
        int | None,
        Field(alias='cachedReadTokens', description='Total cache read tokens.', ge=0),
    ] = None
    cached_write_tokens: Annotated[
        int | None,
        Field(alias='cachedWriteTokens', description='Total cache write tokens.', ge=0),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class IdleStateUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    stop_reason: Annotated[
        StopReason | None,
        Field(
            alias='stopReason',
            description='Indicates why foreground work stopped.\n\nOptional. Omitted or `null` both mean the agent is not reporting a stop reason.\nAgents SHOULD include this when the idle transition ends foreground work.',
        ),
    ] = None
    usage: Annotated[
        Usage | None,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nToken usage for completed foreground work.\n\nOptional. Omitted or `null` both mean the agent is not reporting token\nusage for this state update.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class RequiresActionStateUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class StateUpdate1(RunningStateUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    state: Literal['running']


class StateUpdate2(IdleStateUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    state: Literal['idle']


class StateUpdate3(RequiresActionStateUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    state: Literal['requires_action']


class StateUpdate4(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    state: Annotated[
        str,
        Field(
            description='Custom or future session state.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class StateUpdate(RootModel[StateUpdate1 | StateUpdate2 | StateUpdate3 | StateUpdate4]):
    root: Annotated[
        StateUpdate1 | StateUpdate2 | StateUpdate3 | StateUpdate4,
        Field(
            description="The state of the agent's foreground work has changed.\n\nBackground activity can continue and emit other `session/update` notifications\nwhile `idle`. Those notifications do not change this state."
        ),
    ]


class TerminalOutput(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    data: Annotated[
        str,
        Field(
            description='Base64-encoded replacement terminal output bytes.',
            json_schema_extra={'contentEncoding': 'base64'},
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. This metadata is scoped to the replacement snapshot. Omitted\nand `null` are equivalent and mean no snapshot metadata was provided.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class TerminalExitStatus(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    exit_code: Annotated[
        int | None,
        Field(
            alias='exitCode',
            description='Process exit code, when known. Omitted and `null` are equivalent.',
            ge=0,
        ),
    ] = None
    signal: Annotated[
        str | None,
        Field(
            description='Signal that terminated the process, when known.\n\nAgents should use the conventional platform signal name. POSIX examples\ninclude `SIGTERM`, `SIGKILL`, and `SIGINT`. Other platforms may use a\nplatform-specific name. Omitted and `null` are equivalent.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. This metadata is scoped to the exit information. Omitted\nand `null` are equivalent and mean no exit metadata was provided.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class TerminalUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    terminal_id: Annotated[
        TerminalId,
        Field(
            alias='terminalId',
            description='Unique identifier for this terminal within the session.',
        ),
    ]
    command: Annotated[str | None, Field(description='The command being run.')] = None
    cwd: Annotated[
        AbsolutePath | None,
        Field(description='The absolute working directory of the command.'),
    ] = None
    output: Annotated[
        TerminalOutput | None,
        Field(
            description='An authoritative replacement snapshot of terminal output bytes.'
        ),
    ] = None
    exit_status: Annotated[
        TerminalExitStatus | None,
        Field(
            alias='exitStatus',
            description='Exit information. A concrete object marks the terminal as exited.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Omitted means no metadata update; `null` is an\nexplicit clear signal. Implementations MUST NOT make assumptions about values at these keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class TerminalOutputChunk(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    terminal_id: Annotated[
        TerminalId,
        Field(alias='terminalId', description='The terminal receiving these bytes.'),
    ]
    data: Annotated[
        str,
        Field(
            description='Independently base64-encoded terminal output bytes.',
            json_schema_extra={'contentEncoding': 'base64'},
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. This field is chunk-scoped. Omitted and `null` are\nequivalent and mean no chunk metadata was provided.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PlanId(RootModel[str]):
    root: Annotated[
        str, Field(description='Unique identifier for a plan within a session.')
    ]


class PlanEntryPriority(
    RootModel[Literal['high'] | Literal['medium'] | Literal['low'] | str]
):
    root: Annotated[
        Literal['high'] | Literal['medium'] | Literal['low'] | str,
        Field(
            description='Priority levels for plan entries.\n\nUsed to indicate the relative importance or urgency of different\ntasks in the execution plan.\nSee protocol docs: [Plan Entries](https://agentclientprotocol.com/protocol/v2/draft/agent-plan#plan-entries)'
        ),
    ]


class PlanEntryStatus(
    RootModel[
        Literal['pending']
        | Literal['in_progress']
        | Literal['completed']
        | Literal['cancelled']
        | str
    ]
):
    root: Annotated[
        Literal['pending']
        | Literal['in_progress']
        | Literal['completed']
        | Literal['cancelled']
        | str,
        Field(
            description='Status of a plan entry in the execution flow.\n\nTracks the lifecycle of each task from planning through completion.\nSee protocol docs: [Plan Entries](https://agentclientprotocol.com/protocol/v2/draft/agent-plan#plan-entries)'
        ),
    ]


class PlanFile(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    plan_id: Annotated[
        PlanId, Field(alias='planId', description='The plan ID to update.')
    ]
    uri: Annotated[
        AnyUrl, Field(description='The URI of the file containing the plan.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PlanMarkdown(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    plan_id: Annotated[
        PlanId, Field(alias='planId', description='The plan ID to update.')
    ]
    content: Annotated[str, Field(description='Markdown content for the plan.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PlanRemoved(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    plan_id: Annotated[
        PlanId, Field(alias='planId', description='The plan ID to remove.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AvailableCommandInput2(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future command input type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class TextCommandInput(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    hint: Annotated[
        str,
        Field(description="A hint to display when the input hasn't been provided yet"),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionInfoUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    title: Annotated[
        str | None,
        Field(
            description='Human-readable title for the session. Set to null to clear.'
        ),
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(
            alias='updatedAt',
            description='RFC 3339 timestamp of last activity. Set to null to clear.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Omitted means no metadata update; `null` is an\nexplicit clear signal. Implementations MUST NOT make assumptions about values at these keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class Cost(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    amount: Annotated[float, Field(description='Total cumulative cost for session.')]
    currency: Annotated[
        str,
        Field(
            description='ISO 4217 currency code (e.g., "USD", "EUR").',
            pattern='^[A-Z]{3}$',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class UsageUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    used: Annotated[int, Field(description='Tokens currently in context.', ge=0)]
    size: Annotated[
        int, Field(description='Total context window size in tokens.', ge=0)
    ]
    cost: Annotated[
        Cost | None, Field(description='Cumulative session cost (optional).')
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class CompleteElicitationNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    elicitation_id: Annotated[
        ElicitationId,
        Field(
            alias='elicitationId',
            description='The ID of the elicitation that completed.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class MessageMcpNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    connection_id: Annotated[
        McpConnectionId,
        Field(
            alias='connectionId',
            description='The MCP-over-ACP connection this message is sent on.',
        ),
    ]
    method: Annotated[str, Field(description='The inner MCP method name.')]
    params: Annotated[
        dict[str, Any] | None,
        Field(
            description='Optional inner MCP params.\n\nIf omitted or set to `null`, the inner MCP message has no params.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ExtNotification(RootModel[Any]):
    root: Annotated[
        Any,
        Field(
            description='Allows the Agent to send an arbitrary notification that is not part of the ACP spec.\nExtension notifications provide a way to send one-way messages for custom functionality\nwhile maintaining protocol compatibility.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)'
        ),
    ]


class TerminalAuthCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ElicitationFormCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ElicitationUrlCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesJumpCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesRenameCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesSearchAndReplaceCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class LoginAuthRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    method_id: Annotated[
        AuthMethodId,
        Field(
            alias='methodId',
            description='The ID of the authentication method to use.\nMust be one of the methods advertised in the initialize response.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ListProvidersRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SetProviderRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    provider_id: Annotated[
        ProviderId, Field(alias='providerId', description='Provider ID to configure.')
    ]
    api_type: Annotated[
        LlmProtocol,
        Field(alias='apiType', description='Protocol type for this provider.'),
    ]
    base_url: Annotated[
        AnyUrl,
        Field(
            alias='baseUrl',
            description='Base URL for requests sent through this provider.',
        ),
    ]
    headers: Annotated[
        dict[str, str] | None,
        Field(
            description='Full headers map for this provider.\nMay include authorization, routing, or other integration-specific headers.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DisableProviderRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    provider_id: Annotated[
        ProviderId, Field(alias='providerId', description='Provider ID to disable.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class LogoutAuthRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpServer4(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future MCP server transport type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class HttpHeader(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[str, Field(description='The name of the HTTP header.')]
    value: Annotated[str, Field(description='The value to set for the HTTP header.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpServerHttp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[
        str, Field(description='Human-readable name identifying this MCP server.')
    ]
    url: Annotated[AnyUrl, Field(description='URL to the MCP server.')]
    headers: Annotated[
        list[HttpHeader] | None,
        Field(
            description='HTTP headers to set when making requests to the MCP server.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpServerAcp(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[
        str, Field(description='Human-readable name identifying this MCP server.')
    ]
    server_id: Annotated[
        McpServerAcpId,
        Field(
            alias='serverId',
            description='Unique identifier for this MCP server, generated by the component providing it.\n\nProviders MUST NOT reuse an ID for multiple ACP-transport MCP servers that are visible\non the same ACP connection.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpServerStdio(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[
        str, Field(description='Human-readable name identifying this MCP server.')
    ]
    command: Annotated[
        AbsolutePath, Field(description='Absolute path to the MCP server executable.')
    ]
    args: Annotated[
        list[str] | None,
        Field(description='Command-line arguments to pass to the MCP server.'),
    ] = None
    env: Annotated[
        list[EnvVariable] | None,
        Field(
            description='Environment variables to set when launching the MCP server.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ListSessionsRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    cwd: Annotated[
        AbsolutePath | None,
        Field(
            description='Filter sessions by working directory. Must be an absolute path.'
        ),
    ] = None
    cursor: Annotated[
        SessionListCursor | None,
        Field(
            description="Opaque cursor token from a previous response's nextCursor field for cursor-based pagination"
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DeleteSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The ID of the session to delete.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ReplayFrom2(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future replay cursor type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ReplayFromStart(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class CloseSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The ID of the session to close.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SetSessionConfigOptionRequest1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='The ID of the session to set the configuration option for.',
        ),
    ]
    config_id: Annotated[
        SessionConfigId,
        Field(
            alias='configId', description='The ID of the configuration option to set.'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    value: Annotated[SessionConfigValueId, Field(description='The value ID.')]
    type: Literal['id']


class SetSessionConfigOptionRequest2(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='The ID of the session to set the configuration option for.',
        ),
    ]
    config_id: Annotated[
        SessionConfigId,
        Field(
            alias='configId', description='The ID of the configuration option to set.'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    value: Annotated[bool, Field(description='The boolean value.')]
    type: Literal['boolean']


class SetSessionConfigOptionRequest3(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='The ID of the session to set the configuration option for.',
        ),
    ]
    config_id: Annotated[
        SessionConfigId,
        Field(
            alias='configId', description='The ID of the configuration option to set.'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    type: Annotated[
        str,
        Field(
            description='Custom or future session configuration option value type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]
    value: Annotated[
        Any, Field(description='Raw value payload for the custom or future value type.')
    ]


class SetSessionConfigOptionRequest(
    RootModel[
        SetSessionConfigOptionRequest1
        | SetSessionConfigOptionRequest2
        | SetSessionConfigOptionRequest3
    ]
):
    root: Annotated[
        SetSessionConfigOptionRequest1
        | SetSessionConfigOptionRequest2
        | SetSessionConfigOptionRequest3,
        Field(
            description='Request parameters for setting a session configuration option.'
        ),
    ]


class WorkspaceFolder(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    uri: Annotated[AnyUrl, Field(description='The URI of the folder.')]
    name: Annotated[str, Field(description='The display name of the folder.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesRepository(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[str, Field(description='The repository name.')]
    owner: Annotated[str, Field(description='The repository owner.')]
    remote_url: Annotated[
        str, Field(alias='remoteUrl', description='The remote URL of the repository.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesTriggerKind(
    RootModel[Literal['automatic'] | Literal['diagnostic'] | Literal['manual'] | str]
):
    root: Annotated[
        Literal['automatic'] | Literal['diagnostic'] | Literal['manual'] | str,
        Field(description='What triggered the suggestion request.'),
    ]


class NesRecentFile(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    uri: Annotated[AnyUrl, Field(description='The URI of the file.')]
    language_id: Annotated[
        str, Field(alias='languageId', description='The language identifier.')
    ]
    text: Annotated[str, Field(description='The full text content of the file.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesExcerpt(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    start_line: Annotated[
        int,
        Field(
            alias='startLine',
            description='The start line of the excerpt (zero-based).',
            ge=0,
        ),
    ]
    end_line: Annotated[
        int,
        Field(
            alias='endLine',
            description='The end line of the excerpt (zero-based).',
            ge=0,
        ),
    ]
    text: Annotated[str, Field(description='The text content of the excerpt.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesEditHistoryEntry(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    uri: Annotated[AnyUrl, Field(description='The URI of the edited file.')]
    diff: Annotated[str, Field(description='A diff representing the edit.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesUserAction(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    action: Annotated[
        str,
        Field(description='The kind of action (e.g., "insertChar", "cursorMovement").'),
    ]
    uri: Annotated[
        AnyUrl, Field(description='The URI of the file where the action occurred.')
    ]
    position: Annotated[
        Position, Field(description='The position where the action occurred.')
    ]
    timestamp_ms: Annotated[
        int,
        Field(
            alias='timestampMs',
            description='Timestamp in milliseconds since epoch.',
            ge=0,
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesDiagnosticSeverity(
    RootModel[
        Literal['error']
        | Literal['warning']
        | Literal['information']
        | Literal['hint']
        | str
    ]
):
    root: Annotated[
        Literal['error']
        | Literal['warning']
        | Literal['information']
        | Literal['hint']
        | str,
        Field(description='Severity of a diagnostic.'),
    ]


class CloseNesRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The ID of the NES session to close.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class RequestPermissionOutcome1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    outcome: Literal['cancelled']


class RequestPermissionOutcome3(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    outcome: Annotated[
        str,
        Field(
            description='Custom or future permission outcome.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class SelectedPermissionOutcome(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    option_id: Annotated[
        PermissionOptionId,
        Field(alias='optionId', description='The ID of the option the user selected.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class CreateElicitationResponse2(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    action: Literal['decline']


class CreateElicitationResponse3(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    action: Literal['cancel']


class CreateElicitationResponse4(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    action: Annotated[
        str,
        Field(
            description='Custom or future elicitation action.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class ElicitationContentValue(RootModel[str | int | float | bool | list[str]]):
    root: Annotated[
        str | int | float | bool | list[str],
        Field(
            description='Allowed wire representations for [`ElicitationContentValue`].'
        ),
    ]


class ElicitationAcceptAction(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    content: Annotated[
        dict[str, Any] | None,
        Field(
            description='The user-provided content, if any, as an object matching the requested schema.'
        ),
    ] = None


class ConnectMcpResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    connection_id: Annotated[
        McpConnectionId,
        Field(
            alias='connectionId',
            description='The unique identifier for this MCP-over-ACP connection.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DisconnectMcpResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class CancelSessionNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='The ID of the session to cancel operations for.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DidOpenDocumentNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this notification.'),
    ]
    uri: Annotated[AnyUrl, Field(description='The URI of the opened document.')]
    language_id: Annotated[
        str,
        Field(
            alias='languageId',
            description='The language identifier of the document (e.g., "rust", "python").',
        ),
    ]
    version: Annotated[int, Field(description='The version number of the document.')]
    text: Annotated[str, Field(description='The full text content of the document.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DidCloseDocumentNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this notification.'),
    ]
    uri: Annotated[AnyUrl, Field(description='The URI of the closed document.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DidSaveDocumentNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this notification.'),
    ]
    uri: Annotated[AnyUrl, Field(description='The URI of the saved document.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AcceptNesNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this notification.'),
    ]
    suggestion_id: Annotated[
        NesSuggestionId,
        Field(alias='suggestionId', description='The ID of the accepted suggestion.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesRejectReason(
    RootModel[
        Literal['rejected']
        | Literal['ignored']
        | Literal['replaced']
        | Literal['cancelled']
        | str
    ]
):
    root: Annotated[
        Literal['rejected']
        | Literal['ignored']
        | Literal['replaced']
        | Literal['cancelled']
        | str,
        Field(description='The reason a suggestion was rejected.'),
    ]


class CancelRequestNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    request_id: Annotated[
        RequestId | None,
        Field(alias='requestId', description='The ID of the request to cancel.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class RequestPermissionSubject2(CommandPermissionSubject):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['command']


class ToolCallContent3(Terminal):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['terminal']


class Annotations(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    audience: Annotated[
        list[Role] | None,
        Field(
            description='Intended recipients for this content, such as the user or assistant.'
        ),
    ] = None
    last_modified: Annotated[
        AwareDatetime | None,
        Field(
            alias='lastModified',
            description='Timestamp indicating when the underlying resource was last modified.\n\nMust be an RFC 3339 formatted string (e.g., "2025-01-12T15:00:58Z").',
        ),
    ] = None
    priority: Annotated[
        float | None,
        Field(
            description='Relative importance of this content when clients choose what to surface.',
            ge=0.0,
            le=1.0,
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class TextContent(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    text: Annotated[
        str, Field(description='Text payload carried by this content block.')
    ]
    annotations: Annotated[
        Annotations | None,
        Field(
            description='Optional annotations that help clients decide how to display or route this content.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ImageContent(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    data: Annotated[
        str,
        Field(
            description='Base64-encoded media payload.',
            json_schema_extra={'contentEncoding': 'base64'},
        ),
    ]
    mime_type: Annotated[
        MediaType,
        Field(
            alias='mimeType',
            description='MIME type describing the encoded media payload.',
        ),
    ]
    uri: Annotated[
        AnyUrl | None,
        Field(description='URI associated with this resource or media payload.'),
    ] = None
    annotations: Annotated[
        Annotations | None,
        Field(
            description='Optional annotations that help clients decide how to display or route this content.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AudioContent(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    data: Annotated[
        str,
        Field(
            description='Base64-encoded media payload.',
            json_schema_extra={'contentEncoding': 'base64'},
        ),
    ]
    mime_type: Annotated[
        MediaType,
        Field(
            alias='mimeType',
            description='MIME type describing the encoded media payload.',
        ),
    ]
    annotations: Annotated[
        Annotations | None,
        Field(
            description='Optional annotations that help clients decide how to display or route this content.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class Icon(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    src: Annotated[
        AnyUrl, Field(description='A standard URI pointing to an icon resource.')
    ]
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='Optional MIME type override if the source MIME type is missing or generic.',
        ),
    ] = None
    sizes: Annotated[
        list[str] | None,
        Field(
            description='Optional array of strings that specify sizes at which the icon can be used.\nEach string should be in `WxH` format (e.g., `"48x48"`, `"96x96"`) or\n`"any"` for scalable formats like SVG.\n\nIf not provided, the client should assume that the icon can be used at any size.'
        ),
    ] = None
    theme: Annotated[
        IconTheme | None, Field(description='Optional theme this icon is designed for.')
    ] = None


class ResourceLink(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[
        str, Field(description='Human-readable name shown for this protocol object.')
    ]
    uri: Annotated[
        AnyUrl, Field(description='URI associated with this resource or media payload.')
    ]
    title: Annotated[
        str | None, Field(description='Optional display title for end-user UI.')
    ] = None
    description: Annotated[
        str | None,
        Field(
            description='Optional human-readable details shown with this protocol object.'
        ),
    ] = None
    icons: Annotated[
        list[Icon] | None,
        Field(
            description='Optional set of sized icons that the client can display in a user interface.'
        ),
    ] = None
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type describing the encoded media payload.',
        ),
    ] = None
    size: Annotated[
        int | None,
        Field(description='Optional size of the linked resource in bytes, if known.'),
    ] = None
    annotations: Annotated[
        Annotations | None,
        Field(
            description='Optional annotations that help clients decide how to display or route this content.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class EmbeddedResourceResource(RootModel[TextResourceContents | BlobResourceContents]):
    root: Annotated[
        TextResourceContents | BlobResourceContents,
        Field(description='Resource content that can be embedded in a message.'),
    ]


class EmbeddedResource(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    resource: Annotated[
        EmbeddedResourceResource,
        Field(description='Embedded resource payload, either text or binary data.'),
    ]
    annotations: Annotated[
        Annotations | None,
        Field(
            description='Optional annotations that help clients decide how to display or route this content.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DiffChange1(DiffPathChange):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    file_type: Annotated[
        DiffFileType | None,
        Field(
            alias='fileType',
            description='File content kind.\n\nOmitted or `null` means the content kind is unknown.',
        ),
    ] = None
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type of the file contents.\n\nOmitted or `null` means the MIME type is unknown.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    operation: Literal['add']


class DiffChange2(DiffPathChange):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    file_type: Annotated[
        DiffFileType | None,
        Field(
            alias='fileType',
            description='File content kind.\n\nOmitted or `null` means the content kind is unknown.',
        ),
    ] = None
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type of the file contents.\n\nOmitted or `null` means the MIME type is unknown.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    operation: Literal['delete']


class DiffChange3(DiffPathChange):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    file_type: Annotated[
        DiffFileType | None,
        Field(
            alias='fileType',
            description='File content kind.\n\nOmitted or `null` means the content kind is unknown.',
        ),
    ] = None
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type of the file contents.\n\nOmitted or `null` means the MIME type is unknown.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    operation: Literal['modify']


class DiffChange4(DiffPathPairChange):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    file_type: Annotated[
        DiffFileType | None,
        Field(
            alias='fileType',
            description='File content kind.\n\nOmitted or `null` means the content kind is unknown.',
        ),
    ] = None
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type of the file contents.\n\nOmitted or `null` means the MIME type is unknown.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    operation: Literal['move']


class DiffChange5(DiffPathPairChange):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    file_type: Annotated[
        DiffFileType | None,
        Field(
            alias='fileType',
            description='File content kind.\n\nOmitted or `null` means the content kind is unknown.',
        ),
    ] = None
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type of the file contents.\n\nOmitted or `null` means the MIME type is unknown.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    operation: Literal['copy']


class DiffChange6(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    file_type: Annotated[
        DiffFileType | None,
        Field(
            alias='fileType',
            description='File content kind.\n\nOmitted or `null` means the content kind is unknown.',
        ),
    ] = None
    mime_type: Annotated[
        MediaType | None,
        Field(
            alias='mimeType',
            description='MIME type of the file contents.\n\nOmitted or `null` means the MIME type is unknown.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    operation: Annotated[
        str,
        Field(
            description='Custom or future file operation.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class DiffChange(
    RootModel[
        DiffChange1
        | DiffChange2
        | DiffChange3
        | DiffChange4
        | DiffChange5
        | DiffChange6
    ]
):
    root: Annotated[
        DiffChange1
        | DiffChange2
        | DiffChange3
        | DiffChange4
        | DiffChange5
        | DiffChange6,
        Field(
            description='One file-level change described by a [`Diff`].\n\nStructured change metadata lets clients identify affected files and\noperations without parsing the text patch.'
        ),
    ]


class DiffPatch(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    format: Annotated[
        DiffPatchFormat,
        Field(description='Patch format. The only ACP-defined value is `git_patch`.'),
    ]
    text: Annotated[
        str, Field(description='Patch text in the format named by `format`.')
    ]


class Diff(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    changes: Annotated[
        list[DiffChange],
        Field(
            description='Structured file changes described by this diff.\n\nClients can use this field without parsing patch text to determine affected paths.'
        ),
    ]
    patch: Annotated[
        DiffPatch | None,
        Field(
            description='Renderable patch text for some or all of the structured changes.\n\nAgents SHOULD provide patch text whenever feasible. Omitted or `null`\nmeans no renderable patch text was provided.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PermissionOption(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    option_id: Annotated[
        PermissionOptionId,
        Field(
            alias='optionId',
            description='Unique identifier for this permission option.',
        ),
    ]
    name: Annotated[
        str, Field(description='Human-readable label to display to the user.')
    ]
    kind: Annotated[
        PermissionOptionKind,
        Field(description='Hint about the nature of this permission option.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class CreateElicitationRequest21(ElicitationSessionScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    elicitation_id: Annotated[
        ElicitationId,
        Field(
            alias='elicitationId',
            description='The unique identifier for this elicitation.',
        ),
    ]
    url: Annotated[AnyUrl, Field(description='The URL to direct the user to.')]


class CreateElicitationRequest22(ElicitationRequestScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    elicitation_id: Annotated[
        ElicitationId,
        Field(
            alias='elicitationId',
            description='The unique identifier for this elicitation.',
        ),
    ]
    url: Annotated[AnyUrl, Field(description='The URL to direct the user to.')]


class CreateElicitationRequest24(
    CreateElicitationRequest21, CreateElicitationRequest23
):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message: Annotated[
        str,
        Field(description='A human-readable message describing what input is needed.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    mode: Literal['url']


class CreateElicitationRequest25(
    CreateElicitationRequest22, CreateElicitationRequest23
):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message: Annotated[
        str,
        Field(description='A human-readable message describing what input is needed.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    mode: Literal['url']


class CreateElicitationRequest2(
    RootModel[CreateElicitationRequest24 | CreateElicitationRequest25]
):
    root: Annotated[
        CreateElicitationRequest24 | CreateElicitationRequest25,
        Field(
            description='URL-based elicitation where the client directs the user to a URL.'
        ),
    ]


class CreateElicitationRequest3(ElicitationSessionScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message: Annotated[
        str,
        Field(description='A human-readable message describing what input is needed.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    mode: Annotated[
        str,
        Field(
            description='Custom or future elicitation mode.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class CreateElicitationRequest4(ElicitationRequestScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message: Annotated[
        str,
        Field(description='A human-readable message describing what input is needed.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    mode: Annotated[
        str,
        Field(
            description='Custom or future elicitation mode.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class ElicitationPropertySchema1(StringPropertySchema):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['string']


class ElicitationPropertySchema2(NumberPropertySchema):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['number']


class ElicitationPropertySchema3(IntegerPropertySchema):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['integer']


class ElicitationPropertySchema4(BooleanPropertySchema):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['boolean']


class MultiSelectItems1(StringMultiSelectItems):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['string']


class MultiSelectItems(
    RootModel[MultiSelectItems1 | MultiSelectItems2 | TitledMultiSelectItems]
):
    root: Annotated[
        MultiSelectItems1 | MultiSelectItems2 | TitledMultiSelectItems,
        Field(description='Items for a multi-select (array) property schema.'),
    ]


class MultiSelectPropertySchema(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    title: Annotated[
        str | None,
        Field(
            description='Optional title for the property.\n\nOptional. Omitted and `null` are equivalent and mean no title is provided.'
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(
            description='Human-readable description.\n\nOptional. Omitted and `null` are equivalent and mean no description is provided.'
        ),
    ] = None
    min_items: Annotated[
        int | None,
        Field(
            alias='minItems',
            description='Minimum number of items to select.\n\nOptional. Omitted and `null` are equivalent and mean there is no minimum selection count.',
            ge=0,
        ),
    ] = None
    max_items: Annotated[
        int | None,
        Field(
            alias='maxItems',
            description='Maximum number of items to select.\n\nOptional. Omitted and `null` are equivalent and mean there is no maximum selection count.',
            ge=0,
        ),
    ] = None
    items: Annotated[
        MultiSelectItems,
        Field(description='The items definition describing allowed values.'),
    ]
    default: Annotated[
        list[str] | None,
        Field(
            description='Default selected values.\n\nOptional. Omitted and `null` are equivalent and mean no default selections are provided.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ConnectMcpRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    server_id: Annotated[
        McpServerAcpId,
        Field(
            alias='serverId',
            description='The ACP MCP server ID that was provided by the component declaring the MCP server.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class MessageMcpRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    connection_id: Annotated[
        McpConnectionId,
        Field(
            alias='connectionId',
            description='The MCP-over-ACP connection this message is sent on.',
        ),
    ]
    method: Annotated[str, Field(description='The inner MCP method name.')]
    params: Annotated[
        dict[str, Any] | None,
        Field(
            description='Optional inner MCP params.\n\nIf omitted or set to `null`, the inner MCP message has no params.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PromptCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    image: Annotated[
        PromptImageCapabilities | None,
        Field(
            description='Agent supports [`ContentBlock::Image`].\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports image content in prompts.'
        ),
    ] = None
    audio: Annotated[
        PromptAudioCapabilities | None,
        Field(
            description='Agent supports [`ContentBlock::Audio`].\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports audio content in prompts.'
        ),
    ] = None
    embedded_context: Annotated[
        PromptEmbeddedContextCapabilities | None,
        Field(
            alias='embeddedContext',
            description='Agent supports embedded context in `session/prompt` requests.\n\nWhen enabled, the Client is allowed to include [`ContentBlock::Resource`]\nin prompt requests for pieces of context that are referenced in the message.\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports embedded context in prompts.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    stdio: Annotated[
        McpStdioCapabilities | None,
        Field(
            description='Agent supports [`McpServer::Stdio`].\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports stdio MCP server transports.'
        ),
    ] = None
    http: Annotated[
        McpHttpCapabilities | None,
        Field(
            description='Agent supports [`McpServer::Http`].\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports HTTP MCP server transports.'
        ),
    ] = None
    acp: Annotated[
        McpAcpCapabilities | None,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nAgent supports [`McpServer::Acp`].\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports ACP MCP server transports.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesDocumentDidChangeCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    sync_kind: Annotated[
        TextDocumentSyncKind,
        Field(
            alias='syncKind',
            description='The sync kind the agent wants: `"full"` or `"incremental"`.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesContextCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    recent_files: Annotated[
        NesRecentFilesCapabilities | None,
        Field(
            alias='recentFiles',
            description='Whether the agent wants recent files context.',
        ),
    ] = None
    related_snippets: Annotated[
        NesRelatedSnippetsCapabilities | None,
        Field(
            alias='relatedSnippets',
            description='Whether the agent wants related snippets context.',
        ),
    ] = None
    edit_history: Annotated[
        NesEditHistoryCapabilities | None,
        Field(
            alias='editHistory',
            description='Whether the agent wants edit history context.',
        ),
    ] = None
    user_actions: Annotated[
        NesUserActionsCapabilities | None,
        Field(
            alias='userActions',
            description='Whether the agent wants user actions context.',
        ),
    ] = None
    open_files: Annotated[
        NesOpenFilesCapabilities | None,
        Field(
            alias='openFiles', description='Whether the agent wants open files context.'
        ),
    ] = None
    diagnostics: Annotated[
        NesDiagnosticsCapabilities | None,
        Field(description='Whether the agent wants diagnostics context.'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AuthMethod1(AuthMethodTerminal):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['terminal']


class AuthMethod2(AuthMethodAgent):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['agent']


class AuthMethod3(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future authentication method type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]
    method_id: Annotated[
        AuthMethodId,
        Field(
            alias='methodId',
            description='Unique identifier for this authentication method.',
        ),
    ]
    name: Annotated[
        str, Field(description='Human-readable name of the authentication method.')
    ]
    description: Annotated[
        str | None,
        Field(
            description='Optional description providing more details about this authentication method.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AuthMethod(RootModel[AuthMethod1 | AuthMethod2 | AuthMethod3]):
    root: Annotated[
        AuthMethod1 | AuthMethod2 | AuthMethod3,
        Field(
            description='Describes an available authentication method.\n\nThe `type` field acts as the discriminator in the serialized JSON form.'
        ),
    ]


class ProviderInfo(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    provider_id: Annotated[
        ProviderId,
        Field(
            alias='providerId',
            description='Provider identifier, for example "main" or "openai".',
        ),
    ]
    supported: Annotated[
        list[LlmProtocol],
        Field(description='Supported protocol types for this provider.'),
    ]
    required: Annotated[
        bool,
        Field(
            description='Whether this provider is mandatory and cannot be disabled via `providers/disable`.\nIf true, clients must not call `providers/disable` for this provider ID.'
        ),
    ]
    current: Annotated[
        ProviderCurrentConfig | None,
        Field(
            description='Current effective non-secret routing config.\nNull or omitted means provider is disabled.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionConfigOption2(SessionConfigBoolean):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    config_id: Annotated[
        SessionConfigId,
        Field(
            alias='configId',
            description='Unique identifier for the configuration option.',
        ),
    ]
    name: Annotated[str, Field(description='Human-readable label for the option.')]
    description: Annotated[
        str | None,
        Field(
            description='Optional description for the Client to display to the user.'
        ),
    ] = None
    category: Annotated[
        SessionConfigOptionCategory | None,
        Field(description='Optional semantic category for this option (UX only).'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    type: Literal['boolean']


class SessionConfigOption3(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    config_id: Annotated[
        SessionConfigId,
        Field(
            alias='configId',
            description='Unique identifier for the configuration option.',
        ),
    ]
    name: Annotated[str, Field(description='Human-readable label for the option.')]
    description: Annotated[
        str | None,
        Field(
            description='Optional description for the Client to display to the user.'
        ),
    ] = None
    category: Annotated[
        SessionConfigOptionCategory | None,
        Field(description='Optional semantic category for this option (UX only).'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    type: Annotated[
        str,
        Field(
            description='Custom or future session configuration option type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]


class SessionConfigSelectGroup(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    group_id: Annotated[
        SessionConfigGroupId,
        Field(alias='groupId', description='Unique identifier for this group.'),
    ]
    name: Annotated[str, Field(description='Human-readable label for this group.')]
    options: Annotated[
        list[SessionConfigSelectOption],
        Field(description='The set of option values in this group.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ListSessionsResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    sessions: Annotated[
        list[SessionInfo], Field(description='Array of session information objects.')
    ]
    next_cursor: Annotated[
        SessionListCursor | None,
        Field(
            alias='nextCursor',
            description="Opaque cursor token. If present, pass this in the next request's cursor parameter\nto fetch the next page. If absent, there are no more results.",
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesSuggestion2(NesJumpSuggestion):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    kind: Literal['jump']


class NesSuggestion3(NesRenameSuggestion):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    kind: Literal['rename']


class NesSuggestion4(NesSearchAndReplaceSuggestion):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    kind: Literal['searchAndReplace']


class NesSuggestion5(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    kind: Annotated[
        str,
        Field(
            description='Custom or future NES suggestion kind.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]
    suggestion_id: Annotated[
        NesSuggestionId,
        Field(
            alias='suggestionId',
            description='Unique identifier for accept/reject tracking.',
        ),
    ]


class Range(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    start: Annotated[Position, Field(description='The start position (inclusive).')]
    end: Annotated[Position, Field(description='The end position (exclusive).')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class Error(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    code: Annotated[
        ErrorCode,
        Field(
            description='A number indicating the error type that occurred.\nThis must be an integer as defined in the JSON-RPC specification.'
        ),
    ]
    message: Annotated[
        str,
        Field(
            description='A string providing a short description of the error.\nThe message should be limited to a concise single sentence.'
        ),
    ]
    data: Annotated[
        Any | None,
        Field(
            description='Optional primitive or structured value that contains additional information about the error.\nThis may include debugging information or context-specific details.'
        ),
    ] = None


class SessionUpdate71(RunningStateUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    state: Literal['running']


class SessionUpdate72(IdleStateUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    state: Literal['idle']


class SessionUpdate73(RequiresActionStateUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    state: Literal['requires_action']


class SessionUpdate76(SessionUpdate71, SessionUpdate75):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['state_update'], Field(alias='sessionUpdate')]


class SessionUpdate77(SessionUpdate72, SessionUpdate75):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['state_update'], Field(alias='sessionUpdate')]


class SessionUpdate78(SessionUpdate73, SessionUpdate75):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['state_update'], Field(alias='sessionUpdate')]


class SessionUpdate7(
    RootModel[SessionUpdate76 | SessionUpdate77 | SessionUpdate78 | SessionUpdate79]
):
    root: Annotated[
        SessionUpdate76 | SessionUpdate77 | SessionUpdate78 | SessionUpdate79,
        Field(description="The state of the agent's foreground work has changed."),
    ]


class SessionUpdate10(TerminalUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['terminal_update'], Field(alias='sessionUpdate')]


class SessionUpdate11(TerminalOutputChunk):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        Literal['terminal_output_chunk'], Field(alias='sessionUpdate')
    ]


class SessionUpdate13(PlanRemoved):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['plan_removed'], Field(alias='sessionUpdate')]


class SessionUpdate16(SessionInfoUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        Literal['session_info_update'], Field(alias='sessionUpdate')
    ]


class SessionUpdate17(UsageUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['usage_update'], Field(alias='sessionUpdate')]


class PlanUpdateContent2(PlanFile):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['file']


class PlanUpdateContent3(PlanMarkdown):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['markdown']


class PlanUpdateContent4(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        str,
        Field(
            description='Custom or future plan update content type.\n\nValues beginning with `_` are reserved for implementation-specific\nextensions. Unknown values that do not begin with `_` are reserved for\nfuture ACP variants.'
        ),
    ]
    plan_id: Annotated[
        PlanId, Field(alias='planId', description='The plan ID to update.')
    ]


class PlanEntry(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    content: Annotated[
        str,
        Field(
            description='Human-readable description of what this task aims to accomplish.'
        ),
    ]
    priority: Annotated[
        PlanEntryPriority,
        Field(
            description='The relative importance of this task.\nUsed to indicate which tasks are most critical to the overall goal.'
        ),
    ]
    status: Annotated[
        PlanEntryStatus, Field(description='Current execution status of this task.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PlanItems(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    plan_id: Annotated[
        PlanId, Field(alias='planId', description='The plan ID to update.')
    ]
    entries: Annotated[
        list[PlanEntry],
        Field(
            description='The list of tasks to be accomplished.\n\nWhen updating an item-based plan, the agent must send a complete list of all entries\nwith their current status. The client replaces that plan with each update.'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AvailableCommandInput1(TextCommandInput):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['text']


class AvailableCommandInput(RootModel[AvailableCommandInput1 | AvailableCommandInput2]):
    root: Annotated[
        AvailableCommandInput1 | AvailableCommandInput2,
        Field(description='The input specification for a command.'),
    ]


class AuthCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    terminal: Annotated[
        TerminalAuthCapabilities | None,
        Field(
            description='Whether the client supports `terminal` authentication methods.\n\nOptional. Omitted or `null` both mean the client does not advertise support.\nThe client should supply `{}` only when it can reproduce the configured\nagent invocation in an interactive terminal. Supplying `{}` means the\nagent may include `terminal` entries in its authentication methods.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ElicitationCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    form: Annotated[
        ElicitationFormCapabilities | None,
        Field(
            description='Whether the client supports form-based elicitation.\n\nOptional. Omitted and `null` are equivalent and mean form support is not advertised.\nSupplying `{}` explicitly advertises form support.'
        ),
    ] = None
    url: Annotated[
        ElicitationUrlCapabilities | None,
        Field(
            description='Whether the client supports URL-based elicitation.\n\nOptional. Omitted or `null` both mean the client does not advertise support.\nSupplying `{}` means the client supports URL-based elicitation.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ClientNesCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    jump: Annotated[
        NesJumpCapabilities | None,
        Field(description='Whether the client supports the `jump` suggestion kind.'),
    ] = None
    rename: Annotated[
        NesRenameCapabilities | None,
        Field(description='Whether the client supports the `rename` suggestion kind.'),
    ] = None
    search_and_replace: Annotated[
        NesSearchAndReplaceCapabilities | None,
        Field(
            alias='searchAndReplace',
            description='Whether the client supports the `searchAndReplace` suggestion kind.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class McpServer1(McpServerHttp):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['http']


class McpServer2(McpServerAcp):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['acp']


class McpServer3(McpServerStdio):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['stdio']


class McpServer(RootModel[McpServer1 | McpServer2 | McpServer3 | McpServer4]):
    root: Annotated[
        McpServer1 | McpServer2 | McpServer3 | McpServer4,
        Field(
            description='Configuration for connecting to an MCP (Model Context Protocol) server.\n\nMCP servers provide tools and context that the agent can use when\nprocessing prompts.\n\nSee protocol docs: [MCP Servers](https://agentclientprotocol.com/protocol/v2/draft/session-setup#mcp-servers)'
        ),
    ]


class ForkSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The ID of the session to fork.'),
    ]
    cwd: Annotated[
        AbsolutePath,
        Field(
            description='The working directory for this session. Must be an absolute path.'
        ),
    ]
    additional_directories: Annotated[
        list[AbsolutePath] | None,
        Field(
            alias='additionalDirectories',
            description='Additional workspace roots to activate for this session. Each path must be absolute.\n\nWhen omitted or empty, no additional roots are activated. When non-empty,\nthis is the complete resulting additional-root list for the forked\nsession.',
        ),
    ] = None
    mcp_servers: Annotated[
        list[McpServer] | None,
        Field(
            alias='mcpServers',
            description='List of MCP servers to connect to for this session.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ReplayFrom1(ReplayFromStart):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['start']


class ReplayFrom(RootModel[ReplayFrom1 | ReplayFrom2]):
    root: Annotated[
        ReplayFrom1 | ReplayFrom2,
        Field(
            description='Inclusive cursor describing where replayed session history should begin.\n\nReplay includes the position identified by the cursor.'
        ),
    ]


class StartNesRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    workspace_uri: Annotated[
        AnyUrl | None,
        Field(alias='workspaceUri', description='The root URI of the workspace.'),
    ] = None
    workspace_folders: Annotated[
        list[WorkspaceFolder] | None,
        Field(alias='workspaceFolders', description='The workspace folders.'),
    ] = None
    repository: Annotated[
        NesRepository | None,
        Field(description='Repository metadata, if the workspace is a git repository.'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesRelatedSnippet(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    uri: Annotated[
        AnyUrl, Field(description='The URI of the file containing the snippets.')
    ]
    excerpts: Annotated[list[NesExcerpt], Field(description='The code excerpts.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesOpenFile(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    uri: Annotated[AnyUrl, Field(description='The URI of the file.')]
    language_id: Annotated[
        str, Field(alias='languageId', description='The language identifier.')
    ]
    visible_range: Annotated[
        Range | None,
        Field(
            alias='visibleRange', description='The visible range in the editor, if any.'
        ),
    ] = None
    last_focused_ms: Annotated[
        int | None,
        Field(
            alias='lastFocusedMs',
            description='Timestamp in milliseconds since epoch of when the file was last focused.',
            ge=0,
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesDiagnostic(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    uri: Annotated[
        AnyUrl, Field(description='The URI of the file containing the diagnostic.')
    ]
    range: Annotated[Range, Field(description='The range of the diagnostic.')]
    severity: Annotated[
        NesDiagnosticSeverity, Field(description='The severity of the diagnostic.')
    ]
    message: Annotated[str, Field(description='The diagnostic message.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ClientResponse2(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    id: Annotated[
        RequestId | None,
        Field(description='The id of the request this response answers.'),
    ]
    error: Annotated[Error, Field(description='Method-specific error data.')]


class RequestPermissionOutcome2(SelectedPermissionOutcome):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    outcome: Literal['selected']


class RequestPermissionOutcome(
    RootModel[
        RequestPermissionOutcome1
        | RequestPermissionOutcome2
        | RequestPermissionOutcome3
    ]
):
    root: Annotated[
        RequestPermissionOutcome1
        | RequestPermissionOutcome2
        | RequestPermissionOutcome3,
        Field(description='The outcome of a permission request.'),
    ]


class CreateElicitationResponse1(ElicitationAcceptAction):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    action: Literal['accept']


class CreateElicitationResponse(
    RootModel[
        CreateElicitationResponse1
        | CreateElicitationResponse2
        | CreateElicitationResponse3
        | CreateElicitationResponse4
    ]
):
    root: Annotated[
        CreateElicitationResponse1
        | CreateElicitationResponse2
        | CreateElicitationResponse3
        | CreateElicitationResponse4,
        Field(description='Response from the client to an elicitation request.'),
    ]


class TextDocumentContentChangeEvent(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    range: Annotated[
        Range | None,
        Field(
            description='The range of the document that changed. If `None`, the entire content is replaced.'
        ),
    ] = None
    text: Annotated[
        str,
        Field(
            description='The new text for the range, or the full document content if `range` is `None`.'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DidFocusDocumentNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this notification.'),
    ]
    uri: Annotated[AnyUrl, Field(description='The URI of the focused document.')]
    version: Annotated[int, Field(description='The version number of the document.')]
    position: Annotated[Position, Field(description='The current cursor position.')]
    visible_range: Annotated[
        Range,
        Field(
            alias='visibleRange',
            description='The portion of the file currently visible in the editor viewport.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class RejectNesNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this notification.'),
    ]
    suggestion_id: Annotated[
        NesSuggestionId,
        Field(alias='suggestionId', description='The ID of the rejected suggestion.'),
    ]
    reason: Annotated[
        NesRejectReason | None, Field(description='The reason for rejection.')
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ProtocolLevelNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    method: Annotated[str, Field(description='The notification method name.')]
    params: Annotated[
        CancelRequestNotification | None,
        Field(description='Method-specific notification parameters.'),
    ] = None


class ToolCallContent2(Diff):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['diff']


class ContentBlock1(TextContent):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['text']


class ContentBlock2(ImageContent):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['image']


class ContentBlock3(AudioContent):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['audio']


class ContentBlock4(ResourceLink):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['resource_link']


class ContentBlock5(EmbeddedResource):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['resource']


class ContentBlock(
    RootModel[
        ContentBlock1
        | ContentBlock2
        | ContentBlock3
        | ContentBlock4
        | ContentBlock5
        | ContentBlock6
    ]
):
    root: Annotated[
        ContentBlock1
        | ContentBlock2
        | ContentBlock3
        | ContentBlock4
        | ContentBlock5
        | ContentBlock6,
        Field(
            description="Content blocks represent displayable information in the Agent Client Protocol.\n\nThey provide a structured way to handle various types of user-facing content—whether\nit's text from language models, images for analysis, or embedded resources for context.\n\nContent blocks appear in:\n- User prompts sent via `session/prompt`\n- Language model output reported through `session/update` notifications as\n  message updates or streamed chunks\n- Progress updates and results from tool calls\n\nThis structure is compatible with the Model Context Protocol (MCP), enabling\nagents to seamlessly forward content from MCP tool outputs without transformation.\n\nSee protocol docs: [Content](https://agentclientprotocol.com/protocol/v2/draft/content)"
        ),
    ]


class Content(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    content: Annotated[ContentBlock, Field(description='The actual content block.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ElicitationPropertySchema5(MultiSelectPropertySchema):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['array']


class ElicitationPropertySchema(
    RootModel[
        ElicitationPropertySchema1
        | ElicitationPropertySchema2
        | ElicitationPropertySchema3
        | ElicitationPropertySchema4
        | ElicitationPropertySchema5
        | ElicitationPropertySchema6
    ]
):
    root: Annotated[
        ElicitationPropertySchema1
        | ElicitationPropertySchema2
        | ElicitationPropertySchema3
        | ElicitationPropertySchema4
        | ElicitationPropertySchema5
        | ElicitationPropertySchema6,
        Field(
            description='Property schema for elicitation form fields.\n\nEach variant corresponds to a JSON Schema `"type"` value.\nSingle-select enums use the `String` variant with `enum` or `oneOf` set.\nMulti-select enums use the `Array` variant.'
        ),
    ]


class AgentResponse2(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    id: Annotated[
        RequestId | None,
        Field(description='The id of the request this response answers.'),
    ]
    error: Annotated[Error, Field(description='Method-specific error data.')]


class SessionCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    prompt: Annotated[
        PromptCapabilities | None,
        Field(
            description='Prompt capabilities supported by the agent in `session/prompt` requests.\n\nOptional. Omitted or `null` both mean the agent does not advertise any\nprompt extensions beyond the baseline text and resource-link content\nrequired by `session/prompt`.'
        ),
    ] = None
    mcp: Annotated[
        McpCapabilities | None,
        Field(
            description='MCP capabilities supported by the agent for session lifecycle requests.\n\nOptional. Omitted or `null` both mean the agent does not advertise MCP\nserver transport support for sessions.'
        ),
    ] = None
    delete: Annotated[
        SessionDeleteCapabilities | None,
        Field(
            description='Whether the agent supports `session/delete`.\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports deleting sessions from `session/list`.'
        ),
    ] = None
    additional_directories: Annotated[
        SessionAdditionalDirectoriesCapabilities | None,
        Field(
            alias='additionalDirectories',
            description='Whether the agent supports `additionalDirectories` on supported session lifecycle requests.\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports `additionalDirectories` on\nsupported session lifecycle requests.\n\nAgents may return `SessionInfo.additionalDirectories` to report the\ncomplete ordered additional-root list associated with a listed session.',
        ),
    ] = None
    fork: Annotated[
        SessionForkCapabilities | None,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nWhether the agent supports `session/fork`.\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports forking sessions.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesDocumentEventCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    did_open: Annotated[
        NesDocumentDidOpenCapabilities | None,
        Field(
            alias='didOpen',
            description='Whether the agent wants `document/didOpen` events.',
        ),
    ] = None
    did_change: Annotated[
        NesDocumentDidChangeCapabilities | None,
        Field(
            alias='didChange',
            description='Whether the agent wants `document/didChange` events, and the sync kind.',
        ),
    ] = None
    did_close: Annotated[
        NesDocumentDidCloseCapabilities | None,
        Field(
            alias='didClose',
            description='Whether the agent wants `document/didClose` events.',
        ),
    ] = None
    did_save: Annotated[
        NesDocumentDidSaveCapabilities | None,
        Field(
            alias='didSave',
            description='Whether the agent wants `document/didSave` events.',
        ),
    ] = None
    did_focus: Annotated[
        NesDocumentDidFocusCapabilities | None,
        Field(
            alias='didFocus',
            description='Whether the agent wants `document/didFocus` events.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ListProvidersResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    providers: Annotated[
        list[ProviderInfo],
        Field(
            description='Configurable providers with current routing info suitable for UI display.'
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionConfigSelectOptions(
    RootModel[list[SessionConfigSelectOption] | list[SessionConfigSelectGroup]]
):
    root: Annotated[
        list[SessionConfigSelectOption] | list[SessionConfigSelectGroup],
        Field(description='Possible values for a session configuration option.'),
    ]


class SessionConfigSelect(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    current_value: Annotated[
        SessionConfigValueId,
        Field(alias='currentValue', description='The currently selected value.'),
    ]
    options: Annotated[
        SessionConfigSelectOptions, Field(description='The set of selectable options.')
    ]


class NesTextEdit(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    range: Annotated[Range, Field(description='The range to replace.')]
    new_text: Annotated[
        str, Field(alias='newText', description='The replacement text.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesEditSuggestion(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    suggestion_id: Annotated[
        NesSuggestionId,
        Field(
            alias='suggestionId',
            description='Unique identifier for accept/reject tracking.',
        ),
    ]
    uri: Annotated[AnyUrl, Field(description='The URI of the file to edit.')]
    edits: Annotated[
        list[NesTextEdit],
        Field(
            description='The text edits to apply. Must contain at least one edit.',
            min_length=1,
        ),
    ]
    cursor_position: Annotated[
        Position | None,
        Field(
            alias='cursorPosition',
            description='Optional suggested cursor position after applying edits.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ContentChunk(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message_id: Annotated[
        MessageId,
        Field(
            alias='messageId',
            description='A unique identifier for the message this chunk belongs to.\n\nAll chunks belonging to the same message share the same `messageId`.\nA change in `messageId` indicates a new message has started.',
        ),
    ]
    content: Annotated[ContentBlock, Field(description='A single item of content')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. This field is chunk-scoped.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class UserMessage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message_id: Annotated[
        MessageId,
        Field(alias='messageId', description='A unique identifier for the message.'),
    ]
    content: Annotated[
        list[ContentBlock] | None,
        Field(description='Complete replacement content for this message.'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. Omitted means no metadata update; `null` is an explicit clear signal.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AgentMessage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message_id: Annotated[
        MessageId,
        Field(alias='messageId', description='A unique identifier for the message.'),
    ]
    content: Annotated[
        list[ContentBlock] | None,
        Field(description='Complete replacement content for this message.'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. Omitted means no metadata update; `null` is an explicit clear signal.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AgentThought(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message_id: Annotated[
        MessageId,
        Field(
            alias='messageId',
            description='A unique identifier for the thought message.',
        ),
    ]
    content: Annotated[
        list[ContentBlock] | None,
        Field(description='Complete replacement content for this thought message.'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. Omitted means no metadata update; `null` is an explicit clear signal.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PlanUpdateContent1(PlanItems):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['items']


class PlanUpdateContent(
    RootModel[
        PlanUpdateContent1
        | PlanUpdateContent2
        | PlanUpdateContent3
        | PlanUpdateContent4
    ]
):
    root: Annotated[
        PlanUpdateContent1
        | PlanUpdateContent2
        | PlanUpdateContent3
        | PlanUpdateContent4,
        Field(description='Updated content for a plan.'),
    ]


class PlanUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    plan: Annotated[PlanUpdateContent, Field(description='The updated plan content.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AvailableCommand(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    name: Annotated[
        str,
        Field(description='Command name (e.g., `create_plan`, `research_codebase`).'),
    ]
    description: Annotated[
        str, Field(description='Human-readable description of what the command does.')
    ]
    input: Annotated[
        AvailableCommandInput | None,
        Field(description='Input for the command if required'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AvailableCommandsUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    available_commands: Annotated[
        list[AvailableCommand],
        Field(alias='availableCommands', description='Commands the agent can execute.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ClientCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    auth: Annotated[
        AuthCapabilities | None,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nAuthentication capabilities supported by the client.\nDetermines which authentication method types the agent may include\nin its `InitializeResponse`.\n\nOptional. Omitted or `null` both mean the client does not advertise any\nauthentication-method extensions.'
        ),
    ] = None
    elicitation: Annotated[
        ElicitationCapabilities | None,
        Field(
            description='Elicitation capabilities supported by the client.\nDetermines which elicitation modes the agent may use.\n\nOptional. Omitted or `null` both mean the client does not advertise\nelicitation support.'
        ),
    ] = None
    nes: Annotated[
        ClientNesCapabilities | None,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nNES (Next Edit Suggestions) capabilities supported by the client.\n\nOptional. Omitted or `null` both mean the client does not advertise any\nNES suggestion-kind extensions.'
        ),
    ] = None
    position_encodings: Annotated[
        list[PositionEncodingKind] | None,
        Field(
            alias='positionEncodings',
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nThe position encodings supported by the client, in order of preference.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NewSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    cwd: Annotated[
        AbsolutePath,
        Field(
            description='The working directory for this session. Must be an absolute path.'
        ),
    ]
    additional_directories: Annotated[
        list[AbsolutePath] | None,
        Field(
            alias='additionalDirectories',
            description="Additional workspace roots for this session. Each path must be absolute.\n\nThese expand the session's workspace scope without changing `cwd`, which\nremains the base for relative paths. When omitted or empty, no\nadditional roots are activated for the new session.",
        ),
    ] = None
    mcp_servers: Annotated[
        list[McpServer] | None,
        Field(
            alias='mcpServers',
            description='List of MCP (Model Context Protocol) servers the agent should connect to.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ResumeSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The ID of the session to resume.'),
    ]
    cwd: Annotated[
        AbsolutePath,
        Field(
            description='The working directory for this session. Must be an absolute path.'
        ),
    ]
    additional_directories: Annotated[
        list[AbsolutePath] | None,
        Field(
            alias='additionalDirectories',
            description="Additional workspace roots to activate for this session. Each path must be absolute.\n\nWhen omitted or empty, no additional roots are activated. When non-empty,\nthis is the complete resulting additional-root list for the resumed\nsession. It may differ from any previously used or reported list as long as\nthe request `cwd` matches the session's `cwd`.",
        ),
    ] = None
    mcp_servers: Annotated[
        list[McpServer] | None,
        Field(
            alias='mcpServers',
            description='List of MCP servers to connect to for this session.',
        ),
    ] = None
    replay_from: Annotated[
        ReplayFrom | None,
        Field(
            alias='replayFrom',
            description='Inclusive cursor describing where conversation replay should begin.\n\nOptional. Omitted or `null` both mean the Agent should resume without\nreplaying previous conversation history. Replay cursors are inclusive:\nreplay includes the position identified by the cursor. Supplying\n`{ "type": "start" }` means the Agent should replay the whole\nconversation before responding.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class PromptRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='The ID of the session to send this user message to',
        ),
    ]
    prompt: Annotated[
        list[ContentBlock],
        Field(
            description="The blocks of content that compose the user's message.\n\nAs a baseline, the Agent MUST support [`ContentBlock::Text`] and [`ContentBlock::ResourceLink`],\nwhile other variants are optionally enabled via [`PromptCapabilities`].\n\nThe Client MUST adapt its interface according to [`PromptCapabilities`].\n\nThe client MAY include referenced pieces of context as either\n[`ContentBlock::Resource`] or [`ContentBlock::ResourceLink`].\n\nWhen available, [`ContentBlock::Resource`] is preferred\nas it avoids extra round-trips and allows the message to include\npieces of context from sources the agent may not have access to."
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesSuggestContext(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    recent_files: Annotated[
        list[NesRecentFile] | None,
        Field(alias='recentFiles', description='Recently accessed files.'),
    ] = None
    related_snippets: Annotated[
        list[NesRelatedSnippet] | None,
        Field(alias='relatedSnippets', description='Related code snippets.'),
    ] = None
    edit_history: Annotated[
        list[NesEditHistoryEntry] | None,
        Field(alias='editHistory', description='Recent edit history.'),
    ] = None
    user_actions: Annotated[
        list[NesUserAction] | None,
        Field(
            alias='userActions',
            description='Recent user actions (typing, navigation, etc.).',
        ),
    ] = None
    open_files: Annotated[
        list[NesOpenFile] | None,
        Field(alias='openFiles', description='Currently open files in the editor.'),
    ] = None
    diagnostics: Annotated[
        list[NesDiagnostic] | None,
        Field(description='Current diagnostics (errors, warnings).'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class RequestPermissionResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    outcome: Annotated[
        RequestPermissionOutcome,
        Field(description="The user's decision on the permission request."),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class DidChangeDocumentNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this notification.'),
    ]
    uri: Annotated[AnyUrl, Field(description='The URI of the changed document.')]
    version: Annotated[
        int, Field(description='The new version number of the document.')
    ]
    content_changes: Annotated[
        list[TextDocumentContentChangeEvent],
        Field(alias='contentChanges', description='The content changes.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ToolCallContent1(Content):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['content']


class ToolCallContent(
    RootModel[ToolCallContent1 | ToolCallContent2 | ToolCallContent3 | ToolCallContent4]
):
    root: Annotated[
        ToolCallContent1 | ToolCallContent2 | ToolCallContent3 | ToolCallContent4,
        Field(
            description='Content produced by a tool call.\n\nTool calls can produce different types of content including standard\ncontent blocks (text, images), file diffs, or display-only terminals.\n\nSee protocol docs: [Content](https://agentclientprotocol.com/protocol/v2/draft/tool-calls#content)'
        ),
    ]


class ElicitationSchema(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Annotated[
        ElicitationSchemaType | None,
        Field(description='Type discriminator. Always `"object"`.'),
    ] = 'object'
    title: Annotated[
        str | None,
        Field(
            description='Optional title for the schema.\n\nOptional. Omitted and `null` are equivalent and mean no title is provided.'
        ),
    ] = None
    properties: Annotated[
        dict[str, ElicitationPropertySchema] | None,
        Field(
            description='Property definitions (must be primitive types).',
            validate_default=True,
        ),
    ] = {}
    required: Annotated[
        list[str] | None,
        Field(
            description='List of required property names.\n\nOptional. Omitted and `null` are equivalent and mean no property names are required.'
        ),
    ] = None
    description: Annotated[
        str | None,
        Field(
            description='Optional description of what this schema represents.\n\nOptional. Omitted and `null` are equivalent and mean no schema description is provided.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ElicitationFormMode1(ElicitationSessionScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    requested_schema: Annotated[
        ElicitationSchema,
        Field(
            alias='requestedSchema',
            description='A JSON Schema describing the form fields to present to the user.',
        ),
    ]


class ElicitationFormMode2(ElicitationRequestScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    requested_schema: Annotated[
        ElicitationSchema,
        Field(
            alias='requestedSchema',
            description='A JSON Schema describing the form fields to present to the user.',
        ),
    ]


class ElicitationFormMode(RootModel[ElicitationFormMode1 | ElicitationFormMode2]):
    root: Annotated[
        ElicitationFormMode1 | ElicitationFormMode2,
        Field(
            description='Form-based elicitation mode where the client renders a form from the provided schema.'
        ),
    ]


class NesEventCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    document: Annotated[
        NesDocumentEventCapabilities | None,
        Field(description='Document event capabilities.'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionConfigOption1(SessionConfigSelect):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    config_id: Annotated[
        SessionConfigId,
        Field(
            alias='configId',
            description='Unique identifier for the configuration option.',
        ),
    ]
    name: Annotated[str, Field(description='Human-readable label for the option.')]
    description: Annotated[
        str | None,
        Field(
            description='Optional description for the Client to display to the user.'
        ),
    ] = None
    category: Annotated[
        SessionConfigOptionCategory | None,
        Field(description='Optional semantic category for this option (UX only).'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    type: Literal['select']


class SessionConfigOption(
    RootModel[SessionConfigOption1 | SessionConfigOption2 | SessionConfigOption3]
):
    root: Annotated[
        SessionConfigOption1 | SessionConfigOption2 | SessionConfigOption3,
        Field(
            description='A session configuration option selector and its current state.'
        ),
    ]


class ForkSessionResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='Unique identifier for the newly created forked session.',
        ),
    ]
    config_options: Annotated[
        list[SessionConfigOption] | None,
        Field(
            alias='configOptions', description='Initial session configuration options.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ResumeSessionResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    config_options: Annotated[
        list[SessionConfigOption] | None,
        Field(
            alias='configOptions', description='Initial session configuration options.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SetSessionConfigOptionResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    config_options: Annotated[
        list[SessionConfigOption],
        Field(
            alias='configOptions',
            description='The full set of configuration options and their current values.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NesSuggestion1(NesEditSuggestion):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    kind: Literal['edit']


class NesSuggestion(
    RootModel[
        NesSuggestion1
        | NesSuggestion2
        | NesSuggestion3
        | NesSuggestion4
        | NesSuggestion5
    ]
):
    root: Annotated[
        NesSuggestion1
        | NesSuggestion2
        | NesSuggestion3
        | NesSuggestion4
        | NesSuggestion5,
        Field(description='A suggestion returned by the agent.'),
    ]


class SessionUpdate1(ContentChunk):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        Literal['user_message_chunk'], Field(alias='sessionUpdate')
    ]


class SessionUpdate2(UserMessage):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['user_message'], Field(alias='sessionUpdate')]


class SessionUpdate3(ContentChunk):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        Literal['agent_message_chunk'], Field(alias='sessionUpdate')
    ]


class SessionUpdate4(AgentMessage):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['agent_message'], Field(alias='sessionUpdate')]


class SessionUpdate5(ContentChunk):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        Literal['agent_thought_chunk'], Field(alias='sessionUpdate')
    ]


class SessionUpdate6(AgentThought):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['agent_thought'], Field(alias='sessionUpdate')]


class SessionUpdate12(PlanUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['plan_update'], Field(alias='sessionUpdate')]


class SessionUpdate14(AvailableCommandsUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        Literal['available_commands_update'], Field(alias='sessionUpdate')
    ]


class ToolCallContentChunk(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    tool_call_id: Annotated[
        ToolCallId,
        Field(
            alias='toolCallId',
            description='The ID of the tool call this content belongs to.',
        ),
    ]
    content: Annotated[
        ToolCallContent,
        Field(description='A single item of content produced by the tool call.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys. This field is chunk-scoped.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ConfigOptionUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    config_options: Annotated[
        list[SessionConfigOption],
        Field(
            alias='configOptions',
            description='The full set of configuration options and their current values.',
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class InitializeRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    protocol_version: Annotated[
        ProtocolVersion,
        Field(
            alias='protocolVersion',
            description='The latest protocol version supported by the client.',
        ),
    ]
    info: Annotated[
        Implementation,
        Field(
            description='Information about the implementation sending this initialize request.'
        ),
    ]
    capabilities: Annotated[
        ClientCapabilities | None,
        Field(
            description='Capabilities supported by the client.', validate_default=True
        ),
    ] = {}
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SuggestNesRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this request.'),
    ]
    uri: Annotated[AnyUrl, Field(description='The URI of the document to suggest for.')]
    version: Annotated[int, Field(description='The version number of the document.')]
    position: Annotated[Position, Field(description='The current cursor position.')]
    selection: Annotated[
        Range | None, Field(description='The current text selection range, if any.')
    ] = None
    trigger_kind: Annotated[
        NesTriggerKind,
        Field(
            alias='triggerKind', description='What triggered this suggestion request.'
        ),
    ]
    context: Annotated[
        NesSuggestContext | None,
        Field(
            description='Context for the suggestion, included based on agent capabilities.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ClientResponse1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    id: Annotated[
        RequestId | None,
        Field(description='The id of the request this response answers.'),
    ]
    result: Annotated[
        RequestPermissionResponse
        | CreateElicitationResponse
        | ConnectMcpResponse
        | DisconnectMcpResponse
        | MessageMcpResponse
        | ExtResponse,
        Field(description='Method-specific response data.'),
    ]


class ClientResponse(RootModel[ClientResponse1 | ClientResponse2]):
    root: Annotated[
        ClientResponse1 | ClientResponse2,
        Field(description='A JSON-RPC response object.'),
    ]


class ClientNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    method: Annotated[str, Field(description='The notification method name.')]
    params: Annotated[
        CancelSessionNotification
        | DidOpenDocumentNotification
        | DidChangeDocumentNotification
        | DidCloseDocumentNotification
        | DidSaveDocumentNotification
        | DidFocusDocumentNotification
        | AcceptNesNotification
        | RejectNesNotification
        | MessageMcpNotification
        | ExtNotification
        | None,
        Field(description='Method-specific notification parameters.'),
    ] = None


class ToolCallUpdate(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    tool_call_id: Annotated[
        ToolCallId,
        Field(
            alias='toolCallId',
            description='Unique identifier for this tool call within the session.',
        ),
    ]
    name: Annotated[
        str | None,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nProgrammatic name of the tool being invoked.\n\nThis field is optional and has patch semantics. Omission means no\nchange, `null` clears the name, and a string replaces it. For a tool\ncall ID the client has not seen before, omission or `null` means that no\ntool name is available.'
        ),
    ] = None
    title: Annotated[
        str | None,
        Field(description='Human-readable title describing what the tool is doing.'),
    ] = None
    kind: Annotated[
        ToolKind | None,
        Field(
            description='The category of tool being invoked.\nHelps clients choose appropriate icons and UI treatment.'
        ),
    ] = None
    status: Annotated[
        ToolCallStatus | None,
        Field(description='Current execution status of the tool call.'),
    ] = None
    content: Annotated[
        list[ToolCallContent] | None,
        Field(description='Content produced by the tool call.'),
    ] = None
    locations: Annotated[
        list[ToolCallLocation] | None,
        Field(
            description='File locations affected by this tool call.\nEnables "follow-along" features in clients.'
        ),
    ] = None
    raw_input: Annotated[
        Any | None,
        Field(alias='rawInput', description='Raw input parameters sent to the tool.'),
    ] = None
    raw_output: Annotated[
        Any | None,
        Field(alias='rawOutput', description='Raw output returned by the tool.'),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Omitted means no metadata update; `null` is an\nexplicit clear signal. Implementations MUST NOT make assumptions about values at these keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class ToolCallPermissionSubject(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    tool_call: Annotated[
        ToolCallUpdate,
        Field(
            alias='toolCall',
            description='Details about the tool call requiring permission.',
        ),
    ]


class CreateElicitationRequest11(ElicitationSessionScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    requested_schema: Annotated[
        ElicitationSchema,
        Field(
            alias='requestedSchema',
            description='A JSON Schema describing the form fields to present to the user.',
        ),
    ]


class CreateElicitationRequest12(ElicitationRequestScope):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    requested_schema: Annotated[
        ElicitationSchema,
        Field(
            alias='requestedSchema',
            description='A JSON Schema describing the form fields to present to the user.',
        ),
    ]


class CreateElicitationRequest14(
    CreateElicitationRequest11, CreateElicitationRequest13
):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message: Annotated[
        str,
        Field(description='A human-readable message describing what input is needed.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    mode: Literal['form']


class CreateElicitationRequest15(
    CreateElicitationRequest12, CreateElicitationRequest13
):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    message: Annotated[
        str,
        Field(description='A human-readable message describing what input is needed.'),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nOptional. Omitted and `null` are equivalent and mean no metadata.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None
    mode: Literal['form']


class CreateElicitationRequest1(
    RootModel[CreateElicitationRequest14 | CreateElicitationRequest15]
):
    root: Annotated[
        CreateElicitationRequest14 | CreateElicitationRequest15,
        Field(
            description='Form-based elicitation where the client renders a form from the provided schema.'
        ),
    ]


class CreateElicitationRequest(
    RootModel[
        CreateElicitationRequest1
        | CreateElicitationRequest2
        | CreateElicitationRequest3
        | CreateElicitationRequest4
    ]
):
    root: Annotated[
        CreateElicitationRequest1
        | CreateElicitationRequest2
        | CreateElicitationRequest3
        | CreateElicitationRequest4,
        Field(
            description='Request from the agent to elicit structured user input.\n\nThe agent sends this to the client to request information from the user,\neither via a form or by directing them to a URL.\nElicitations are tied to a session (optionally a tool call) or a request.'
        ),
    ]


class NesCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    events: Annotated[
        NesEventCapabilities | None,
        Field(description='Events the agent wants to receive.'),
    ] = None
    context: Annotated[
        NesContextCapabilities | None,
        Field(
            description='Context the agent wants attached to each suggestion request.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class NewSessionResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='Unique identifier for the created session.\n\nUsed in all subsequent requests for this conversation.',
        ),
    ]
    config_options: Annotated[
        list[SessionConfigOption] | None,
        Field(
            alias='configOptions', description='Initial session configuration options.'
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SuggestNesResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    suggestions: Annotated[
        list[NesSuggestion], Field(description='The list of suggestions.')
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class SessionUpdate8(ToolCallContentChunk):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        Literal['tool_call_content_chunk'], Field(alias='sessionUpdate')
    ]


class SessionUpdate9(ToolCallUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[Literal['tool_call_update'], Field(alias='sessionUpdate')]


class SessionUpdate15(ConfigOptionUpdate):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_update: Annotated[
        Literal['config_option_update'], Field(alias='sessionUpdate')
    ]


class SessionUpdate(
    RootModel[
        SessionUpdate1
        | SessionUpdate2
        | SessionUpdate3
        | SessionUpdate4
        | SessionUpdate5
        | SessionUpdate6
        | SessionUpdate7
        | SessionUpdate8
        | SessionUpdate9
        | SessionUpdate10
        | SessionUpdate11
        | SessionUpdate12
        | SessionUpdate13
        | SessionUpdate14
        | SessionUpdate15
        | SessionUpdate16
        | SessionUpdate17
        | SessionUpdate18
    ]
):
    root: Annotated[
        SessionUpdate1
        | SessionUpdate2
        | SessionUpdate3
        | SessionUpdate4
        | SessionUpdate5
        | SessionUpdate6
        | SessionUpdate7
        | SessionUpdate8
        | SessionUpdate9
        | SessionUpdate10
        | SessionUpdate11
        | SessionUpdate12
        | SessionUpdate13
        | SessionUpdate14
        | SessionUpdate15
        | SessionUpdate16
        | SessionUpdate17
        | SessionUpdate18,
        Field(
            description='Different types of updates that can be sent while a session exists.\n\nThese updates report messages, progress, and other session activity.\n\nSee protocol docs: [Agent Reports Output](https://agentclientprotocol.com/protocol/v2/draft/prompt-lifecycle#3-agent-reports-output)'
        ),
    ]


class ClientRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    id: Annotated[
        RequestId | None,
        Field(description='The request id used to correlate the matching response.'),
    ]
    method: Annotated[str, Field(description='The method name to invoke.')]
    params: Annotated[
        InitializeRequest
        | LoginAuthRequest
        | ListProvidersRequest
        | SetProviderRequest
        | DisableProviderRequest
        | LogoutAuthRequest
        | NewSessionRequest
        | ListSessionsRequest
        | DeleteSessionRequest
        | ForkSessionRequest
        | ResumeSessionRequest
        | CloseSessionRequest
        | SetSessionConfigOptionRequest
        | PromptRequest
        | StartNesRequest
        | SuggestNesRequest
        | CloseNesRequest
        | MessageMcpRequest
        | ExtRequest
        | None,
        Field(description='Method-specific request parameters.'),
    ] = None


class RequestPermissionSubject1(ToolCallPermissionSubject):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    type: Literal['tool_call']


class RequestPermissionSubject(
    RootModel[
        RequestPermissionSubject1
        | RequestPermissionSubject2
        | RequestPermissionSubject3
    ]
):
    root: Annotated[
        RequestPermissionSubject1
        | RequestPermissionSubject2
        | RequestPermissionSubject3,
        Field(description='The operation requiring permission.'),
    ]


class AgentCapabilities(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session: Annotated[
        SessionCapabilities | None,
        Field(
            description='Session capabilities supported by the agent.\n\nOptional. Omitted or `null` both mean the agent does not support the\n`session/*` method surface. Supplying `{}` means the agent supports the\nbaseline session methods: `session/new`, `session/prompt`,\n`session/cancel`, and `session/update`.'
        ),
    ] = None
    auth: Annotated[
        AgentAuthCapabilities | None,
        Field(
            description='Authentication-related extension capabilities supported by the agent.\n\nOptional. Omitted or `null` both mean the agent does not advertise any\nauthentication-related extensions. This field does not advertise support\nfor `auth/login` or `auth/logout`; those methods are advertised by a\nnon-empty `authMethods` list in the `initialize` response.'
        ),
    ] = None
    providers: Annotated[
        ProvidersCapabilities | None,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nProvider configuration capabilities supported by the agent.\n\nOptional. Omitted or `null` both mean the agent does not advertise support.\nSupplying `{}` means the agent supports provider configuration methods.'
        ),
    ] = None
    nes: Annotated[
        NesCapabilities | None,
        Field(
            description='**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nNES (Next Edit Suggestions) capabilities supported by the agent.\n\nOptional. Omitted or `null` both mean the agent does not advertise support\nfor NES methods.'
        ),
    ] = None
    position_encoding: Annotated[
        PositionEncodingKind | None,
        Field(
            alias='positionEncoding',
            description="**UNSTABLE**\n\nThis capability is not part of the spec yet, and may be removed or changed at any point.\n\nThe position encoding selected by the agent from the client's supported encodings.",
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class UpdateSessionNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(
            alias='sessionId',
            description='The ID of the session this update pertains to.',
        ),
    ]
    update: Annotated[SessionUpdate, Field(description='The actual update content.')]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class RequestPermissionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    session_id: Annotated[
        SessionId,
        Field(alias='sessionId', description='The session ID for this request.'),
    ]
    title: Annotated[
        str,
        Field(
            description="Human-readable title for the permission prompt.\n\nThis title is specific to the permission prompt and does not update any\nsubject's displayed title."
        ),
    ]
    description: Annotated[
        str | None,
        Field(
            description="Optional human-readable explanation of why permission is needed.\n\nThis text is specific to the permission prompt and does not update any\nsubject's displayed content. Omitted or `null` both mean no separate\npermission description was provided."
        ),
    ] = None
    subject: Annotated[
        RequestPermissionSubject | None,
        Field(
            description='Optional structured context about the operation requiring permission.\n\nOmitted or `null` both mean no structured subject was provided.'
        ),
    ] = None
    options: Annotated[
        list[PermissionOption],
        Field(
            description='Available permission options for the user to choose from.\nMust contain at least one option.',
            min_length=1,
        ),
    ]
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class InitializeResponse(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    protocol_version: Annotated[
        ProtocolVersion,
        Field(
            alias='protocolVersion',
            description="The protocol version the client specified if supported by the agent,\nor the latest protocol version supported by the agent.\n\nThe client should disconnect, if it doesn't support this version.",
        ),
    ]
    info: Annotated[
        Implementation,
        Field(
            description='Information about the implementation sending this initialize response.'
        ),
    ]
    capabilities: Annotated[
        AgentCapabilities | None,
        Field(
            description='Capabilities supported by the agent.', validate_default=True
        ),
    ] = {}
    auth_methods: Annotated[
        list[AuthMethod] | None,
        Field(
            alias='authMethods',
            description='Authentication methods supported by the agent.\n\nOptional. Omitted or empty means the agent does not advertise the\nauthentication method surface. Supplying one or more valid methods means\nthe agent MUST support both `auth/login` and `auth/logout`.',
        ),
    ] = None
    field_meta: Annotated[
        dict[str, Any] | None,
        Field(
            alias='_meta',
            description='The _meta property is reserved by ACP to allow clients and agents to attach additional\nmetadata to their interactions. Implementations MUST NOT make assumptions about values at\nthese keys.\n\nSee protocol docs: [Extensibility](https://agentclientprotocol.com/protocol/v2/draft/extensibility)',
        ),
    ] = None


class AgentNotification(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    method: Annotated[str, Field(description='The notification method name.')]
    params: Annotated[
        UpdateSessionNotification
        | CompleteElicitationNotification
        | MessageMcpNotification
        | ExtNotification
        | None,
        Field(description='Method-specific notification parameters.'),
    ] = None


class AgentRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    id: Annotated[
        RequestId | None,
        Field(description='The request id used to correlate the matching response.'),
    ]
    method: Annotated[str, Field(description='The method name to invoke.')]
    params: Annotated[
        RequestPermissionRequest
        | CreateElicitationRequest
        | ConnectMcpRequest
        | MessageMcpRequest
        | DisconnectMcpRequest
        | ExtRequest
        | None,
        Field(description='Method-specific request parameters.'),
    ] = None


class AgentResponse1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        populate_by_name=True,
    )
    id: Annotated[
        RequestId | None,
        Field(description='The id of the request this response answers.'),
    ]
    result: Annotated[
        InitializeResponse
        | LoginAuthResponse
        | ListProvidersResponse
        | SetProviderResponse
        | DisableProviderResponse
        | LogoutAuthResponse
        | NewSessionResponse
        | ListSessionsResponse
        | DeleteSessionResponse
        | ForkSessionResponse
        | ResumeSessionResponse
        | CloseSessionResponse
        | SetSessionConfigOptionResponse
        | PromptResponse
        | StartNesResponse
        | SuggestNesResponse
        | CloseNesResponse
        | ExtResponse
        | MessageMcpResponse,
        Field(description='Method-specific response data.'),
    ]


class AgentResponse(RootModel[AgentResponse1 | AgentResponse2]):
    root: Annotated[
        AgentResponse1 | AgentResponse2,
        Field(description='A JSON-RPC response object.'),
    ]
