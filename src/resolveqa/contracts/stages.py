"""Stage input/output contracts and component protocols (RFC-0001 §3.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from .enums import ChannelType, DeliveryKind, ReproOutcome, VerdictResult
from .errors import ContractValidationError
from .run_state import RunState
from .validators import (
    parse_enum,
    require_bool,
    require_int,
    require_non_empty_str,
    require_optional_non_empty_str,
    require_tuple_of_strings,
)


@dataclass(frozen=True)
class ReportInput:
    """Input payload for case creation at Intake (RFC-0001 §3.3, RF-01)."""
    client_id: str
    repo_ref: str
    channel: ChannelType
    report_text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_id", require_non_empty_str(self.client_id, "client_id"))
        object.__setattr__(self, "repo_ref", require_non_empty_str(self.repo_ref, "repo_ref"))
        object.__setattr__(self, "channel", parse_enum(ChannelType, self.channel, "channel"))
        object.__setattr__(self, "report_text", require_non_empty_str(self.report_text, "report_text"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "repo_ref": self.repo_ref,
            "channel": self.channel.value,
            "report_text": self.report_text,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> ReportInput:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"ReportInput payload must be a dict, got {type(data).__name__}."
            )
        for field_name in ["client_id", "repo_ref", "channel", "report_text"]:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in ReportInput."
                )
        return cls(
            client_id=data["client_id"],
            repo_ref=data["repo_ref"],
            channel=data["channel"],
            report_text=data["report_text"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> ReportInput:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class TriageRecord:
    """Structured analysis produced by Triage when data is sufficient (RFC-0001 §3.3, RF-03)."""
    input: str
    expected: str
    observed: str
    suspect_files: tuple[str, ...] = ()
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "input", require_non_empty_str(self.input, "input"))
        object.__setattr__(self, "expected", require_non_empty_str(self.expected, "expected"))
        object.__setattr__(self, "observed", require_non_empty_str(self.observed, "observed"))
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ContractValidationError(
                f"'confidence' must be a float or int, got {type(self.confidence).__name__}."
            )
        conf_val = float(self.confidence)
        if not (0.0 <= conf_val <= 1.0):
            raise ContractValidationError("confidence must be between 0.0 and 1.0.")
        object.__setattr__(self, "confidence", conf_val)
        object.__setattr__(
            self, "suspect_files", require_tuple_of_strings(self.suspect_files, "suspect_files")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "expected": self.expected,
            "observed": self.observed,
            "suspect_files": list(self.suspect_files),
            "confidence": self.confidence,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> TriageRecord:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"TriageRecord payload must be a dict, got {type(data).__name__}."
            )
        for field_name in ["input", "expected", "observed"]:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in TriageRecord."
                )
        return cls(
            input=data["input"],
            expected=data["expected"],
            observed=data["observed"],
            suspect_files=tuple(data.get("suspect_files", ())),
            confidence=data.get("confidence", 1.0),
        )

    @classmethod
    def from_json(cls, json_str: str) -> TriageRecord:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class NeedsInfo:
    """Information request produced by Triage when report is insufficient (RFC-0001 §3.3, RF-03)."""
    missing_fields: tuple[str, ...]
    question_to_support: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "question_to_support",
            require_non_empty_str(self.question_to_support, "question_to_support"),
        )
        object.__setattr__(
            self, "missing_fields", require_tuple_of_strings(self.missing_fields, "missing_fields")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "missing_fields": list(self.missing_fields),
            "question_to_support": self.question_to_support,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> NeedsInfo:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"NeedsInfo payload must be a dict, got {type(data).__name__}."
            )
        if "missing_fields" not in data or "question_to_support" not in data:
            raise ContractValidationError("Missing required fields in NeedsInfo.")
        return cls(
            missing_fields=tuple(data["missing_fields"]),
            question_to_support=data["question_to_support"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> NeedsInfo:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class ReproResult:
    """Output from Reproduction stage running the newly synthesized test (RFC-0001 §3.3, RF-04)."""
    test_path: str
    test_source_ref: str
    exit_code: int
    outcome: ReproOutcome
    failing_assertion: Optional[str] = None
    log_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_path", require_non_empty_str(self.test_path, "test_path"))
        object.__setattr__(
            self, "test_source_ref", require_non_empty_str(self.test_source_ref, "test_source_ref")
        )
        object.__setattr__(self, "exit_code", require_int(self.exit_code, "exit_code"))
        object.__setattr__(self, "outcome", parse_enum(ReproOutcome, self.outcome, "outcome"))
        object.__setattr__(
            self,
            "failing_assertion",
            require_optional_non_empty_str(self.failing_assertion, "failing_assertion"),
        )
        if not isinstance(self.log_ref, str):
            raise ContractValidationError(
                f"'log_ref' must be a str, got {type(self.log_ref).__name__}."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_path": self.test_path,
            "test_source_ref": self.test_source_ref,
            "exit_code": self.exit_code,
            "outcome": self.outcome.value,
            "failing_assertion": self.failing_assertion,
            "log_ref": self.log_ref,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> ReproResult:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"ReproResult payload must be a dict, got {type(data).__name__}."
            )
        for field_name in ["test_path", "test_source_ref", "exit_code", "outcome"]:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in ReproResult."
                )
        return cls(
            test_path=data["test_path"],
            test_source_ref=data["test_source_ref"],
            exit_code=data["exit_code"],
            outcome=data["outcome"],
            failing_assertion=data.get("failing_assertion"),
            log_ref=data.get("log_ref", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> ReproResult:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class Patch:
    """Proposed fix patch produced by Fix stage (RFC-0001 §3.3, RF-05)."""
    diff_ref: str
    files_changed: tuple[str, ...]
    touches_tests: bool = False
    touches_ci: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "diff_ref", require_non_empty_str(self.diff_ref, "diff_ref"))
        object.__setattr__(self, "touches_tests", require_bool(self.touches_tests, "touches_tests"))
        object.__setattr__(self, "touches_ci", require_bool(self.touches_ci, "touches_ci"))
        object.__setattr__(
            self, "files_changed", require_tuple_of_strings(self.files_changed, "files_changed")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diff_ref": self.diff_ref,
            "files_changed": list(self.files_changed),
            "touches_tests": self.touches_tests,
            "touches_ci": self.touches_ci,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> Patch:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"Patch payload must be a dict, got {type(data).__name__}."
            )
        if "diff_ref" not in data or "files_changed" not in data:
            raise ContractValidationError("Missing required field 'diff_ref' or 'files_changed'.")
        return cls(
            diff_ref=data["diff_ref"],
            files_changed=tuple(data["files_changed"]),
            touches_tests=data.get("touches_tests", False),
            touches_ci=data.get("touches_ci", False),
        )

    @classmethod
    def from_json(cls, json_str: str) -> Patch:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class TestRun:
    """Execution telemetry of a single test run within Verification (RFC-0001 §3.3)."""
    command: str
    exit_code: int
    duration_s: float
    log_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", require_non_empty_str(self.command, "command"))
        object.__setattr__(self, "exit_code", require_int(self.exit_code, "exit_code"))
        if isinstance(self.duration_s, bool) or not isinstance(self.duration_s, (int, float)):
            raise ContractValidationError(
                f"'duration_s' must be numeric, got {type(self.duration_s).__name__}."
            )
        dur = float(self.duration_s)
        if dur < 0:
            raise ContractValidationError("'duration_s' must be non-negative.")
        object.__setattr__(self, "duration_s", dur)
        if not isinstance(self.log_ref, str):
            raise ContractValidationError(
                f"'log_ref' must be str, got {type(self.log_ref).__name__}."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "duration_s": self.duration_s,
            "log_ref": self.log_ref,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> TestRun:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"TestRun payload must be a dict, got {type(data).__name__}."
            )
        for field_name in ["command", "exit_code", "duration_s", "log_ref"]:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in TestRun."
                )
        return cls(
            command=data["command"],
            exit_code=data["exit_code"],
            duration_s=data["duration_s"],
            log_ref=data["log_ref"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> TestRun:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class Verdict:
    """Deterministic verdict produced by Verification stage (RFC-0001 §3.3, RF-06)."""
    before: TestRun
    after: TestRun
    suite: TestRun
    base_revision: str
    fix_revision: str
    result: VerdictResult
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.before, dict):
            object.__setattr__(self, "before", TestRun.from_dict(self.before))
        elif not isinstance(self.before, TestRun):
            raise ContractValidationError(
                f"'before' must be TestRun or dict, got {type(self.before).__name__}."
            )

        if isinstance(self.after, dict):
            object.__setattr__(self, "after", TestRun.from_dict(self.after))
        elif not isinstance(self.after, TestRun):
            raise ContractValidationError(
                f"'after' must be TestRun or dict, got {type(self.after).__name__}."
            )

        if isinstance(self.suite, dict):
            object.__setattr__(self, "suite", TestRun.from_dict(self.suite))
        elif not isinstance(self.suite, TestRun):
            raise ContractValidationError(
                f"'suite' must be TestRun or dict, got {type(self.suite).__name__}."
            )

        object.__setattr__(self, "result", parse_enum(VerdictResult, self.result, "result"))
        object.__setattr__(self, "reasons", require_tuple_of_strings(self.reasons, "reasons"))

        self.validate()

    def validate(self) -> None:
        """Validate Verdict invariants per RFC-0001 §3.3."""
        if self.result == VerdictResult.VERIFIED:
            if self.before.exit_code == 0:
                raise ContractValidationError(
                    "Verified verdict requires before.exit_code != 0 (reproduction failing before fix)."
                )
            if self.after.exit_code != 0:
                raise ContractValidationError(
                    f"Verified verdict requires after.exit_code == 0, got {self.after.exit_code}."
                )
            if self.suite.exit_code != 0:
                raise ContractValidationError(
                    f"Verified verdict requires suite.exit_code == 0, got {self.suite.exit_code}."
                )
            require_non_empty_str(self.base_revision, "base_revision")
            require_non_empty_str(self.fix_revision, "fix_revision")
        else:
            if self.base_revision is not None and not isinstance(self.base_revision, str):
                raise ContractValidationError(
                    f"'base_revision' must be str or None, got {type(self.base_revision).__name__}."
                )
            if self.fix_revision is not None and not isinstance(self.fix_revision, str):
                raise ContractValidationError(
                    f"'fix_revision' must be str or None, got {type(self.fix_revision).__name__}."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "suite": self.suite.to_dict(),
            "base_revision": self.base_revision,
            "fix_revision": self.fix_revision,
            "result": self.result.value,
            "reasons": list(self.reasons),
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> Verdict:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"Verdict payload must be a dict, got {type(data).__name__}."
            )
        for field_name in ["before", "after", "suite", "base_revision", "fix_revision", "result"]:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in Verdict."
                )
        return cls(
            before=data["before"],
            after=data["after"],
            suite=data["suite"],
            base_revision=data["base_revision"],
            fix_revision=data["fix_revision"],
            result=data["result"],
            reasons=tuple(data.get("reasons", ())),
        )

    @classmethod
    def from_json(cls, json_str: str) -> Verdict:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class DeliveryResult:
    """Output of Delivery stage packaging the verified fix (RFC-0001 §3.3, RF-08)."""
    kind: DeliveryKind
    url_or_path: str
    label: Optional[str] = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", parse_enum(DeliveryKind, self.kind, "kind"))
        object.__setattr__(
            self, "url_or_path", require_non_empty_str(self.url_or_path, "url_or_path")
        )
        object.__setattr__(self, "label", require_optional_non_empty_str(self.label, "label"))
        object.__setattr__(
            self, "evidence_refs", require_tuple_of_strings(self.evidence_refs, "evidence_refs")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "url_or_path": self.url_or_path,
            "label": self.label,
            "evidence_refs": list(self.evidence_refs),
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> DeliveryResult:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"DeliveryResult payload must be a dict, got {type(data).__name__}."
            )
        if "kind" not in data or "url_or_path" not in data:
            raise ContractValidationError("Missing required fields in DeliveryResult.")
        return cls(
            kind=data["kind"],
            url_or_path=data["url_or_path"],
            label=data.get("label"),
            evidence_refs=tuple(data.get("evidence_refs", ())),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DeliveryResult:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class CustomerMessage:
    """Message returned to the customer channel (RFC-0001 §3.3, RF-09)."""
    channel: ChannelType
    text: str
    sent_after_event_seq: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", parse_enum(ChannelType, self.channel, "channel"))
        object.__setattr__(self, "text", require_non_empty_str(self.text, "text"))
        object.__setattr__(
            self,
            "sent_after_event_seq",
            require_int(self.sent_after_event_seq, "sent_after_event_seq", min_value=0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel.value,
            "text": self.text,
            "sent_after_event_seq": self.sent_after_event_seq,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> CustomerMessage:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"CustomerMessage payload must be a dict, got {type(data).__name__}."
            )
        for field_name in ["channel", "text", "sent_after_event_seq"]:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in CustomerMessage."
                )
        return cls(
            channel=data["channel"],
            text=data["text"],
            sent_after_event_seq=data["sent_after_event_seq"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> CustomerMessage:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class ExecResult:
    """Sandbox execution outcome (RFC-0001 §3.3, RNF-01)."""
    exit_code: int
    stdout_ref: str
    stderr_ref: str
    timed_out: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "exit_code", require_int(self.exit_code, "exit_code"))
        if not isinstance(self.stdout_ref, str):
            raise ContractValidationError(
                f"'stdout_ref' must be str, got {type(self.stdout_ref).__name__}."
            )
        if not isinstance(self.stderr_ref, str):
            raise ContractValidationError(
                f"'stderr_ref' must be str, got {type(self.stderr_ref).__name__}."
            )
        object.__setattr__(self, "timed_out", require_bool(self.timed_out, "timed_out"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout_ref": self.stdout_ref,
            "stderr_ref": self.stderr_ref,
            "timed_out": self.timed_out,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> ExecResult:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"ExecResult payload must be a dict, got {type(data).__name__}."
            )
        if "exit_code" not in data:
            raise ContractValidationError("Missing 'exit_code' in ExecResult.")
        return cls(
            exit_code=data["exit_code"],
            stdout_ref=data.get("stdout_ref", ""),
            stderr_ref=data.get("stderr_ref", ""),
            timed_out=data.get("timed_out", False),
        )

    @classmethod
    def from_json(cls, json_str: str) -> ExecResult:
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class LLMResult:
    """Normalized response from LLM adapter (RFC-0001 §3.3, RNF-03)."""
    content: str
    tokens_in: int
    tokens_out: int
    provider: str
    model: str
    mock: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", require_non_empty_str(self.content, "content"))
        object.__setattr__(
            self, "tokens_in", require_int(self.tokens_in, "tokens_in", min_value=0)
        )
        object.__setattr__(
            self, "tokens_out", require_int(self.tokens_out, "tokens_out", min_value=0)
        )
        object.__setattr__(self, "provider", require_non_empty_str(self.provider, "provider"))
        object.__setattr__(self, "model", require_non_empty_str(self.model, "model"))
        object.__setattr__(self, "mock", require_bool(self.mock, "mock"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "provider": self.provider,
            "model": self.model,
            "mock": self.mock,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Any) -> LLMResult:
        if not isinstance(data, dict):
            raise ContractValidationError(
                f"LLMResult payload must be a dict, got {type(data).__name__}."
            )
        for field_name in ["content", "provider", "model"]:
            if field_name not in data:
                raise ContractValidationError(
                    f"Missing required field '{field_name}' in LLMResult."
                )
        return cls(
            content=data["content"],
            tokens_in=data.get("tokens_in", 0),
            tokens_out=data.get("tokens_out", 0),
            provider=data["provider"],
            model=data["model"],
            mock=data.get("mock", False),
        )

    @classmethod
    def from_json(cls, json_str: str) -> LLMResult:
        return cls.from_dict(json.loads(json_str))


# Stage Component Protocols (RFC-0001 §3.3)


@runtime_checkable
class IntakeStage(Protocol):
    def create(self, report: ReportInput) -> RunState: ...


@runtime_checkable
class TriageStage(Protocol):
    def run(self, case: RunState) -> TriageRecord | NeedsInfo: ...


@runtime_checkable
class ReproductionStage(Protocol):
    def run(self, case: RunState, triage: TriageRecord) -> ReproResult: ...


@runtime_checkable
class FixStage(Protocol):
    def run(self, case: RunState, triage: TriageRecord, repro: ReproResult) -> Patch: ...


@runtime_checkable
class VerificationStage(Protocol):
    def run(self, case: RunState, repro: ReproResult, patch: Patch) -> Verdict: ...


@runtime_checkable
class DeliveryStage(Protocol):
    def build(self, case: RunState, verdict: Verdict) -> DeliveryResult: ...


@runtime_checkable
class ReplyStage(Protocol):
    def compose(self, case: RunState, outcome: Any) -> CustomerMessage: ...


@runtime_checkable
class SandboxStage(Protocol):
    def exec(self, workdir_ref: str, command: str, timeout_s: float) -> ExecResult: ...


@runtime_checkable
class LLMStage(Protocol):
    def complete(
        self,
        purpose: str,
        messages: list[dict[str, str]],
        schema: Optional[dict[str, Any]] = None,
    ) -> LLMResult: ...
