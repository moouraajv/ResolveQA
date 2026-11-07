"""Contracts package for ResolveQA (RFC-0001 §3)."""

from .enums import (
    BlockedReason,
    CaseState,
    ChannelType,
    DeliveryKind,
    EventSource,
    EventType,
    EvidenceKind,
    ReproOutcome,
    TERMINAL_STATES,
    VerdictResult,
)
from .errors import ContractValidationError
from .events import Event, ReplayRef
from .evidence import Evidence
from .run_state import Attempts, RunState
from .stages import (
    CustomerMessage,
    DeliveryResult,
    DeliveryStage,
    ExecResult,
    FixStage,
    IntakeStage,
    LLMResult,
    LLMStage,
    NeedsInfo,
    Patch,
    ReplyStage,
    ReportInput,
    ReproductionStage,
    ReproResult,
    SandboxStage,
    TestRun,
    TriageRecord,
    TriageStage,
    Verdict,
    VerificationStage,
)

__all__ = [
    # Enums & Constants
    "BlockedReason",
    "CaseState",
    "ChannelType",
    "DeliveryKind",
    "EventSource",
    "EventType",
    "EvidenceKind",
    "ReproOutcome",
    "TERMINAL_STATES",
    "VerdictResult",
    # Errors
    "ContractValidationError",
    # Core Models
    "Attempts",
    "RunState",
    "Event",
    "ReplayRef",
    "Evidence",
    # Stage Models
    "ReportInput",
    "TriageRecord",
    "NeedsInfo",
    "ReproResult",
    "Patch",
    "TestRun",
    "Verdict",
    "DeliveryResult",
    "CustomerMessage",
    "ExecResult",
    "LLMResult",
    # Stage Protocols
    "IntakeStage",
    "TriageStage",
    "ReproductionStage",
    "FixStage",
    "VerificationStage",
    "DeliveryStage",
    "ReplyStage",
    "SandboxStage",
    "LLMStage",
]
