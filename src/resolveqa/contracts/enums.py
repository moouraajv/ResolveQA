"""Enumerations defined in RFC-0001 §3."""

from enum import Enum


class CaseState(str, Enum):
    """Case states across the ResolveQA pipeline (RFC-0001 §3.1)."""
    CREATED = "created"
    TRIAGING = "triaging"
    TRIAGED = "triaged"
    REPRODUCING = "reproducing"
    REPRODUCED = "reproduced"
    FIXING = "fixing"
    FIXED = "fixed"
    VERIFYING = "verifying"
    # Terminal states (RFC-0001 §4)
    VERIFIED = "verified"
    NEEDS_INFO = "needs_info"
    BLOCKED = "blocked"
    INFRA_ERROR = "infra_error"


TERMINAL_STATES = frozenset({
    CaseState.VERIFIED,
    CaseState.NEEDS_INFO,
    CaseState.BLOCKED,
    CaseState.INFRA_ERROR,
})


class ChannelType(str, Enum):
    """Allowed intake/notification channels (RFC-0001 §3.1)."""
    API = "api"
    FORM = "form"
    SIMULATED_CHAT = "simulated_chat"


class EventSource(str, Enum):
    """Origin of a recorded event (RFC-0001 §3.2)."""
    INTAKE = "intake"
    ORCHESTRATOR = "orchestrator"
    TRIAGE = "triage"
    REPRODUCTION = "reproduction"
    FIX = "fix"
    VERIFICATION = "verification"
    DELIVERY = "delivery"
    REPLY = "reply"


class EventType(str, Enum):
    """Type of recorded event (RFC-0001 §3.2)."""
    CASE_CREATED = "CaseCreated"
    STATE_CHANGED = "StateChanged"
    EVIDENCE_ADDED = "EvidenceAdded"
    LIMIT_REACHED = "LimitReached"
    MESSAGE_SENT = "MessageSent"
    REPLAY_STARTED = "ReplayStarted"


class ReproOutcome(str, Enum):
    """Reproduction execution outcome (RFC-0001 §3.3)."""
    RED_ON_ASSERTION = "red_on_assertion"
    GREEN = "green"
    ENV_ERROR = "env_error"


class VerdictResult(str, Enum):
    """Verification verdict outcome (RFC-0001 §3.3)."""
    VERIFIED = "verified"
    REJECTED = "rejected"
    ENV_ERROR = "env_error"


class DeliveryKind(str, Enum):
    """Delivery artifact kind (RFC-0001 §3.3)."""
    DRAFT_PR = "draft_pr"
    LOCAL_PACKAGE = "local_package"


class EvidenceKind(str, Enum):
    """Evidence artifact classification (RFC-0001 §3.4)."""
    REPORT = "report"
    TRIAGE_RECORD = "triage_record"
    TEST_SOURCE = "test_source"
    TEST_LOG = "test_log"
    EXIT_CODE = "exit_code"
    DIFF = "diff"
    VERDICT = "verdict"
    PR_PACKAGE = "pr_package"
    CUSTOMER_MESSAGE = "customer_message"
