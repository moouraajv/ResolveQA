"""Unit tests and regression test suite for ResolveQA contracts (RFC-0001 §3)."""

from dataclasses import FrozenInstanceError
from typing import Any
import unittest

from resolveqa.contracts import (
    Attempts,
    BlockedReason,
    BlockedTerminalReason,
    CaseState,
    ChannelType,
    ContractValidationError,
    CustomerMessage,
    DeliveryKind,
    DeliveryResult,
    DeliveryStage,
    Event,
    EventSource,
    EventType,
    Evidence,
    EvidenceKind,
    ExecResult,
    FixStage,
    InfraErrorTerminalReason,
    IntakeStage,
    LLMResult,
    LLMStage,
    NeedsInfo,
    NeedsInfoTerminalReason,
    Patch,
    ReplayRef,
    ReplyStage,
    ReportInput,
    ReproOutcome,
    ReproductionStage,
    ReproResult,
    RunState,
    SandboxStage,
    TestRun as ContractTestRun,
    TerminalReason,
    TriageRecord,
    TriageStage,
    Verdict,
    VerdictResult,
    VerificationStage,
)


class TestImmutabilityAndFrozenContract(unittest.TestCase):
    """Test requirement 1: dataclasses are frozen=True and collections are immutable."""

    def test_run_state_is_frozen_and_collections_immutable(self) -> None:
        rs = RunState(
            case_id="c-1",
            client_id="client-1",
            repo_ref="repo/1",
            channel=ChannelType.API,
            report_text="text",
            state=CaseState.CREATED,
            created_at="2026-11-07T12:00:00Z",
            updated_at="2026-11-07T12:00:00Z",
            evidence_ids=("ev-1", "ev-2"),
        )
        self.assertIsInstance(rs.evidence_ids, tuple)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            rs.state = CaseState.TRIAGING  # type: ignore

        # transition_to produces a new instance and does not mutate original
        rs2 = rs.transition_to(CaseState.TRIAGING, updated_at="2026-11-07T12:01:00Z")
        self.assertEqual(rs.state, CaseState.CREATED)
        self.assertEqual(rs2.state, CaseState.TRIAGING)
        self.assertIsNot(rs, rs2)

    def test_attempts_is_frozen(self) -> None:
        att = Attempts(fix=1, llm_calls=2)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            att.fix = 2  # type: ignore

    def test_other_dataclasses_are_frozen_and_have_immutable_tuples(self) -> None:
        tr = TriageRecord(input="i", expected="e", observed="o", suspect_files=("f1.py",))
        self.assertIsInstance(tr.suspect_files, tuple)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            tr.input = "new"  # type: ignore

        patch = Patch(diff_ref="diff-1", files_changed=("f1.py",))
        self.assertIsInstance(patch.files_changed, tuple)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            patch.diff_ref = "new"  # type: ignore

        verdict = Verdict(
            before=ContractTestRun("pytest", 1, 1.0, "l1"),
            after=ContractTestRun("pytest", 0, 1.0, "l2"),
            suite=ContractTestRun("pytest", 0, 2.0, "l3"),
            base_revision="base",
            fix_revision="fix",
            result=VerdictResult.VERIFIED,
            reasons=("all good",),
        )
        self.assertIsInstance(verdict.reasons, tuple)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            verdict.result = VerdictResult.REJECTED  # type: ignore


class TestRunStateContract(unittest.TestCase):
    """Test suite for RunState invariants and serialization (RFC-0001 §3.1)."""

    def setUp(self) -> None:
        self.valid_payload = {
            "case_id": "case-123",
            "client_id": "client-abc",
            "repo_ref": "org/repo",
            "channel": "simulated_chat",
            "report_text": "Cupom de R$ 20 nao aplicou no total de R$ 200",
            "state": "created",
            "created_at": "2026-11-07T12:00:00Z",
            "updated_at": "2026-11-07T12:00:00Z",
            "terminal_reason": None,
            "attempts": {"fix": 0, "llm_calls": 0},
            "base_revision": "abc1234",
            "fix_revision": None,
            "evidence_ids": ["ev-1", "ev-2"],
        }

    def test_run_state_instantiation_and_fields(self) -> None:
        run_state = RunState.from_dict(self.valid_payload)
        self.assertEqual(run_state.case_id, "case-123")
        self.assertEqual(run_state.client_id, "client-abc")
        self.assertEqual(run_state.repo_ref, "org/repo")
        self.assertEqual(run_state.channel, ChannelType.SIMULATED_CHAT)
        self.assertEqual(run_state.report_text, "Cupom de R$ 20 nao aplicou no total de R$ 200")
        self.assertEqual(run_state.state, CaseState.CREATED)
        self.assertIsNone(run_state.terminal_reason)
        self.assertEqual(run_state.attempts.fix, 0)
        self.assertEqual(run_state.attempts.llm_calls, 0)
        self.assertEqual(run_state.base_revision, "abc1234")
        self.assertIsNone(run_state.fix_revision)
        self.assertEqual(run_state.evidence_ids, ("ev-1", "ev-2"))

    def test_client_id_must_be_strictly_non_empty_str(self) -> None:
        """Finding 2: client_id cannot become string from numbers, objects, empty, or whitespace."""
        invalid_values = ["", "   ", None, 123, 0, {}, [], True, False]
        for val in invalid_values:
            with self.subTest(val=val):
                payload = dict(self.valid_payload)
                payload["client_id"] = val
                with self.assertRaises(ContractValidationError):
                    RunState.from_dict(payload)

    def test_missing_required_fields_in_from_dict(self) -> None:
        """Finding 2: missing keys in payload must raise ContractValidationError."""
        for field_name in ["case_id", "client_id", "repo_ref", "channel", "report_text", "state"]:
            with self.subTest(missing_field=field_name):
                payload = dict(self.valid_payload)
                del payload[field_name]
                with self.assertRaises(ContractValidationError):
                    RunState.from_dict(payload)

    def test_reject_invalid_enums_in_run_state(self) -> None:
        """Finding 1: RunState rejects state='verifed' and channel='bad'."""
        payload = dict(self.valid_payload)
        payload["state"] = "verifed"
        with self.assertRaises(ContractValidationError) as ctx:
            RunState.from_dict(payload)
        self.assertIn("state", str(ctx.exception))

        payload = dict(self.valid_payload)
        payload["channel"] = "bad"
        with self.assertRaises(ContractValidationError) as ctx:
            RunState.from_dict(payload)
        self.assertIn("channel", str(ctx.exception))

    def test_run_state_timestamps_require_utc_iso8601(self) -> None:
        """Timestamps created_at/updated_at require UTC ISO 8601 (with Z or +00:00)."""
        p_offset = dict(self.valid_payload)
        p_offset["created_at"] = "2026-11-07T12:00:00+00:00"
        p_offset["updated_at"] = "2026-11-07T12:05:00+00:00"
        rs = RunState.from_dict(p_offset)
        self.assertEqual(rs.created_at, "2026-11-07T12:00:00+00:00")

        invalid_timestamps = [
            "2026-11-07T12:00:00",  # naive, no tz
            "2026-11-07T12:00:00+03:00",  # non-UTC tz
            "2026-11-07T12:00:00-03:00",  # non-UTC tz
            "x",
            "not-a-date",
            "",
            None,
        ]
        for bad_ts in invalid_timestamps:
            for field_name in ["created_at", "updated_at"]:
                with self.subTest(field=field_name, ts=bad_ts):
                    p = dict(self.valid_payload)
                    p[field_name] = bad_ts
                    with self.assertRaises(ContractValidationError):
                        RunState.from_dict(p)

    def test_terminal_states_require_terminal_reason(self) -> None:
        """Terminal states other than verified require terminal_reason."""
        non_verified_terminals = [
            CaseState.NEEDS_INFO,
            CaseState.BLOCKED,
            CaseState.INFRA_ERROR,
        ]

        for term_state in non_verified_terminals:
            with self.subTest(state=term_state):
                payload = dict(self.valid_payload)
                payload["state"] = term_state.value
                payload["terminal_reason"] = None
                with self.assertRaises(ContractValidationError) as ctx:
                    RunState.from_dict(payload)
                self.assertIn("requires", str(ctx.exception).lower())

                payload["terminal_reason"] = "   "
                with self.assertRaises(ContractValidationError):
                    RunState.from_dict(payload)

    def test_structured_terminal_reason_by_state(self) -> None:
        """Requirement 2: terminal_reason structured invariants by state."""
        # 1. verified state MUST NOT have terminal_reason
        p_ver = dict(self.valid_payload)
        p_ver["state"] = CaseState.VERIFIED.value
        p_ver["terminal_reason"] = None
        rs_ver = RunState.from_dict(p_ver)
        self.assertIsNone(rs_ver.terminal_reason)

        p_ver_bad = dict(p_ver)
        p_ver_bad["terminal_reason"] = {"code": "limit_exceeded"}
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ver_bad)

        p_ver_str = dict(p_ver)
        p_ver_str["terminal_reason"] = "verified with success"
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ver_str)

        # 2. non-terminal state MUST NOT have terminal_reason
        p_created = dict(self.valid_payload)
        p_created["state"] = CaseState.CREATED.value
        p_created["terminal_reason"] = {"code": "limit_exceeded"}
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_created)

        # 3. needs_info state requires NeedsInfoTerminalReason (question_to_support)
        p_ni = dict(self.valid_payload)
        p_ni["state"] = CaseState.NEEDS_INFO.value
        p_ni["terminal_reason"] = {"question_to_support": "Qual o codigo do cupom?"}
        rs_ni = RunState.from_dict(p_ni)
        self.assertIsInstance(rs_ni.terminal_reason, NeedsInfoTerminalReason)
        self.assertEqual(rs_ni.terminal_reason.question_to_support, "Qual o codigo do cupom?")
        # JSON roundtrip
        ni_json = rs_ni.to_json()
        rs_ni_recovered = RunState.from_json(ni_json)
        self.assertEqual(rs_ni, rs_ni_recovered)

        # String is strictly rejected
        p_ni_str = dict(p_ni)
        p_ni_str["terminal_reason"] = "Qual o codigo do cupom?"
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ni_str)

        # Needs_info rejects other reason structures or extra fields
        p_ni_wrong = dict(p_ni)
        p_ni_wrong["terminal_reason"] = {"code": "limit_exceeded"}
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ni_wrong)

        p_ni_extra = dict(p_ni)
        p_ni_extra["terminal_reason"] = {"question_to_support": "Q?", "detail": "extra"}
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ni_extra)

        p_ni["terminal_reason"] = None
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ni)

        # 4. infra_error requires InfraErrorTerminalReason (detail)
        p_ie = dict(self.valid_payload)
        p_ie["state"] = CaseState.INFRA_ERROR.value
        p_ie["terminal_reason"] = {"detail": "Sandbox container timed out after 600s"}
        rs_ie = RunState.from_dict(p_ie)
        self.assertIsInstance(rs_ie.terminal_reason, InfraErrorTerminalReason)
        self.assertEqual(rs_ie.terminal_reason.detail, "Sandbox container timed out after 600s")
        # JSON roundtrip
        ie_json = rs_ie.to_json()
        rs_ie_recovered = RunState.from_json(ie_json)
        self.assertEqual(rs_ie, rs_ie_recovered)

        # String is rejected
        p_ie_str = dict(p_ie)
        p_ie_str["terminal_reason"] = "Sandbox container timed out"
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ie_str)

        # Extra fields or wrong reason rejected
        p_ie_extra = dict(p_ie)
        p_ie_extra["terminal_reason"] = {"detail": "err", "question_to_support": "extra"}
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ie_extra)

        p_ie["terminal_reason"] = None
        with self.assertRaises(ContractValidationError):
            RunState.from_dict(p_ie)

        # 5. blocked requires BlockedTerminalReason (code enum + optional detail)
        p_blk = dict(self.valid_payload)
        p_blk["state"] = CaseState.BLOCKED.value

        valid_blocked_payloads = [
            {"code": "limit_exceeded"},
            {"code": "not_reproduced"},
            {"code": "patch_rejected"},
            {"code": "limit_exceeded", "detail": "max fix attempts reached"},
            {"code": "not_reproduced", "detail": "assertion did not fail on test"},
            {"code": "patch_rejected", "detail": "touched test files in fix"},
        ]
        for b_dict in valid_blocked_payloads:
            with self.subTest(reason=b_dict):
                p_blk["terminal_reason"] = b_dict
                rs_b = RunState.from_dict(p_blk)
                self.assertIsInstance(rs_b.terminal_reason, BlockedTerminalReason)
                self.assertEqual(rs_b.terminal_reason.code.value, b_dict["code"])
                self.assertEqual(rs_b.terminal_reason.detail, b_dict.get("detail"))
                # JSON roundtrip
                rs_b_recovered = RunState.from_json(rs_b.to_json())
                self.assertEqual(rs_b, rs_b_recovered)

        # Rejection of strings (including limit_exceeded string)
        for bad_str in ["limit_exceeded", "not_reproduced", "patch_rejected", "limit_exceeded: max"]:
            with self.subTest(bad_str=bad_str):
                p_blk["terminal_reason"] = bad_str
                with self.assertRaises(ContractValidationError):
                    RunState.from_dict(p_blk)

        # Rejection of wrong fields, invalid codes, empty detail
        invalid_blocked_payloads = [
            None,
            {},
            {"code": "unknown_reason"},
            {"code": "limit_exceeded", "detail": ""},
            {"code": "limit_exceeded", "detail": "   "},
            {"code": "limit_exceeded", "question_to_support": "extra"},
        ]
        for bad_payload in invalid_blocked_payloads:
            with self.subTest(bad_payload=bad_payload):
                p_blk["terminal_reason"] = bad_payload
                with self.assertRaises(ContractValidationError):
                    RunState.from_dict(p_blk)

    def test_verified_terminal_state_does_not_require_reason(self) -> None:
        """Verified terminal state does not allow a terminal_reason (RFC-0001 §4)."""
        payload = dict(self.valid_payload)
        payload["state"] = CaseState.VERIFIED.value
        payload["terminal_reason"] = None
        run_state = RunState.from_dict(payload)
        self.assertEqual(run_state.state, CaseState.VERIFIED)
        self.assertIsNone(run_state.terminal_reason)

    def test_transition_to_validates_invariants(self) -> None:
        run_state = RunState.from_dict(self.valid_payload)

        # Transition to valid non-terminal state
        s2 = run_state.transition_to(CaseState.TRIAGING, updated_at="2026-11-07T12:01:00Z")
        self.assertEqual(s2.state, CaseState.TRIAGING)

        # Transition to invalid state string
        with self.assertRaises(ContractValidationError):
            run_state.transition_to("verifed", updated_at="2026-11-07T12:01:00Z")

        # Transition with naive updated_at
        with self.assertRaises(ContractValidationError):
            run_state.transition_to(CaseState.TRIAGING, updated_at="2026-11-07 12:01:00")

        # Transition to blocked without terminal_reason must fail
        with self.assertRaises(ContractValidationError):
            run_state.transition_to(CaseState.BLOCKED, updated_at="2026-11-07T12:02:00Z")

        # Transition to blocked with valid terminal_reason succeeds
        reason = BlockedTerminalReason(BlockedReason.NOT_REPRODUCED, "assertion did not trigger")
        s3 = run_state.transition_to(
            CaseState.BLOCKED,
            updated_at="2026-11-07T12:02:00Z",
            terminal_reason=reason,
        )
        self.assertEqual(s3.state, CaseState.BLOCKED)
        self.assertEqual(s3.terminal_reason, reason)

    def test_json_serialization_roundtrip(self) -> None:
        original = RunState.from_dict(self.valid_payload)
        json_output = original.to_json()
        self.assertIsInstance(json_output, str)

        restored = RunState.from_json(json_output)
        self.assertEqual(original.to_dict(), restored.to_dict())
        self.assertEqual(restored.case_id, original.case_id)
        self.assertEqual(restored.client_id, original.client_id)
        self.assertEqual(restored.state, original.state)
        self.assertEqual(restored.attempts.to_dict(), original.attempts.to_dict())

        # Invalid JSON translation
        with self.assertRaises(ContractValidationError):
            RunState.from_json("not valid json")
        with self.assertRaises(ContractValidationError):
            RunState.from_json("[1, 2, 3]")
        with self.assertRaises(ContractValidationError):
            RunState.from_json("12345")


class TestEventContract(unittest.TestCase):
    """Test suite for Event model and serialization (RFC-0001 §3.2)."""

    def setUp(self) -> None:
        self.valid_event_payload = {
            "event_id": "evt-001",
            "case_id": "case-123",
            "seq": 1,
            "ts": "2026-11-07T12:00:00Z",
            "source": "orchestrator",
            "type": "StateChanged",
            "from_state": "created",
            "to_state": "triaging",
            "reason": "Starting triage",
            "evidence_refs": ["ev-1"],
            "replay_of": None,
        }

    def test_event_instantiation_and_fields(self) -> None:
        event = Event.from_dict(self.valid_event_payload)
        self.assertEqual(event.event_id, "evt-001")
        self.assertEqual(event.case_id, "case-123")
        self.assertEqual(event.seq, 1)
        self.assertEqual(event.source, EventSource.ORCHESTRATOR)
        self.assertEqual(event.type, EventType.STATE_CHANGED)
        self.assertEqual(event.from_state, CaseState.CREATED)
        self.assertEqual(event.to_state, CaseState.TRIAGING)
        self.assertEqual(event.reason, "Starting triage")
        self.assertEqual(event.evidence_refs, ("ev-1",))
        self.assertIsNone(event.replay_of)

    def test_event_rejects_invalid_enums(self) -> None:
        """Finding 1: Event rejects invalid enum values in source, type, from_state, to_state."""
        for field_name in ["source", "type", "from_state", "to_state"]:
            with self.subTest(field=field_name):
                payload = dict(self.valid_event_payload)
                payload[field_name] = "invalid_enum_val"
                with self.assertRaises(ContractValidationError):
                    Event.from_dict(payload)

    def test_event_ts_requires_utc_iso8601(self) -> None:
        """Event.ts requires valid UTC ISO 8601 timestamp."""
        # Valid with +00:00
        p = dict(self.valid_event_payload)
        p["ts"] = "2026-11-07T12:00:00+00:00"
        evt = Event.from_dict(p)
        self.assertEqual(evt.ts, "2026-11-07T12:00:00+00:00")

        # Invalid
        for bad_ts in ["2026-11-07T12:00:00", "2026-11-07T12:00:00-05:00", "bad-date", ""]:
            with self.subTest(ts=bad_ts):
                p_bad = dict(self.valid_event_payload)
                p_bad["ts"] = bad_ts
                with self.assertRaises(ContractValidationError):
                    Event.from_dict(p_bad)

    def test_replay_event_requires_replay_of_with_valid_ts(self) -> None:
        payload = dict(self.valid_event_payload)
        payload["type"] = EventType.REPLAY_STARTED.value
        payload["from_state"] = None
        payload["to_state"] = None
        payload["replay_of"] = None

        with self.assertRaises(ContractValidationError) as ctx:
            Event.from_dict(payload)
        self.assertIn("replay_of is required", str(ctx.exception))

        # ReplayRef with valid timestamp
        payload["replay_of"] = {"case_id": "orig-123", "original_ts": "2026-11-06T10:00:00Z"}
        event = Event.from_dict(payload)
        self.assertEqual(event.type, EventType.REPLAY_STARTED)
        self.assertIsNotNone(event.replay_of)
        self.assertEqual(event.replay_of.case_id, "orig-123")

        # ReplayRef with invalid timestamp
        payload["replay_of"] = {"case_id": "orig-123", "original_ts": "naive-2026-11-06T10:00:00"}
        with self.assertRaises(ContractValidationError):
            Event.from_dict(payload)

    def test_state_changed_invariants_and_other_events_forbid_states(self) -> None:
        """Requirement 4: StateChanged requires valid different from/to, other events forbid both."""
        # 1. StateChanged with identical from and to must fail
        p_same = dict(self.valid_event_payload)
        p_same["from_state"] = "created"
        p_same["to_state"] = "created"
        with self.assertRaises(ContractValidationError) as ctx:
            Event.from_dict(p_same)
        self.assertIn("different", str(ctx.exception))

        # 2. StateChanged with missing from_state or to_state must fail
        p_missing_from = dict(self.valid_event_payload)
        p_missing_from["from_state"] = None
        with self.assertRaises(ContractValidationError):
            Event.from_dict(p_missing_from)

        p_missing_to = dict(self.valid_event_payload)
        p_missing_to["to_state"] = None
        with self.assertRaises(ContractValidationError):
            Event.from_dict(p_missing_to)

        # 3. Other events forbid from_state and to_state
        for non_state_type in [
            EventType.CASE_CREATED,
            EventType.EVIDENCE_ADDED,
            EventType.LIMIT_REACHED,
            EventType.MESSAGE_SENT,
        ]:
            with self.subTest(event_type=non_state_type):
                p_other = {
                    "event_id": "evt-002",
                    "case_id": "case-123",
                    "seq": 2,
                    "ts": "2026-11-07T12:00:00Z",
                    "source": "orchestrator",
                    "type": non_state_type.value,
                    "from_state": "created",
                    "to_state": None,
                }
                with self.assertRaises(ContractValidationError):
                    Event.from_dict(p_other)

                p_other["from_state"] = None
                p_other["to_state"] = "triaging"
                with self.assertRaises(ContractValidationError):
                    Event.from_dict(p_other)

                # Valid when both are None
                p_other["to_state"] = None
                ev = Event.from_dict(p_other)
                self.assertIsNone(ev.from_state)
                self.assertIsNone(ev.to_state)

    def test_state_reconstruction_via_events(self) -> None:
        """Requirement 4: State reconstruction via sequential StateChanged events."""
        events = [
            Event(
                event_id="e1",
                case_id="case-1",
                seq=0,
                ts="2026-11-07T10:00:00Z",
                source=EventSource.INTAKE,
                type=EventType.CASE_CREATED,
            ),
            Event(
                event_id="e2",
                case_id="case-1",
                seq=1,
                ts="2026-11-07T10:01:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.CREATED,
                to_state=CaseState.TRIAGING,
            ),
            Event(
                event_id="e3",
                case_id="case-1",
                seq=2,
                ts="2026-11-07T10:02:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.TRIAGING,
                to_state=CaseState.TRIAGED,
            ),
            Event(
                event_id="e4",
                case_id="case-1",
                seq=3,
                ts="2026-11-07T10:03:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.TRIAGED,
                to_state=CaseState.REPRODUCING,
            ),
            Event(
                event_id="e5",
                case_id="case-1",
                seq=4,
                ts="2026-11-07T10:04:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.REPRODUCING,
                to_state=CaseState.REPRODUCED,
            ),
            Event(
                event_id="e6",
                case_id="case-1",
                seq=5,
                ts="2026-11-07T10:05:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.REPRODUCED,
                to_state=CaseState.FIXING,
            ),
            Event(
                event_id="e7",
                case_id="case-1",
                seq=6,
                ts="2026-11-07T10:06:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.FIXING,
                to_state=CaseState.FIXED,
            ),
            Event(
                event_id="e8",
                case_id="case-1",
                seq=7,
                ts="2026-11-07T10:07:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.FIXED,
                to_state=CaseState.VERIFYING,
            ),
            Event(
                event_id="e9",
                case_id="case-1",
                seq=8,
                ts="2026-11-07T10:08:00Z",
                source=EventSource.ORCHESTRATOR,
                type=EventType.STATE_CHANGED,
                from_state=CaseState.VERIFYING,
                to_state=CaseState.VERIFIED,
            ),
        ]

        current_state = CaseState.CREATED
        for ev in events:
            if ev.type == EventType.STATE_CHANGED:
                self.assertEqual(ev.from_state, current_state)
                current_state = ev.to_state

        self.assertEqual(current_state, CaseState.VERIFIED)

    def test_event_json_serialization_roundtrip(self) -> None:
        event = Event.from_dict(self.valid_event_payload)
        json_str = event.to_json()
        restored = Event.from_json(json_str)

        self.assertEqual(event.to_dict(), restored.to_dict())
        self.assertEqual(restored.event_id, "evt-001")


class TestEvidenceContract(unittest.TestCase):
    """Test suite for Evidence model and serialization (RFC-0001 §3.4)."""

    def setUp(self) -> None:
        self.valid_evidence_payload = {
            "evidence_id": "ev-001",
            "case_id": "case-123",
            "kind": "diff",
            "path": "evidence/ev-001.patch",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "revision": "abc1234",
            "created_at": "2026-11-07T12:05:00Z",
            "simulated": False,
        }

    def test_evidence_instantiation_and_fields(self) -> None:
        evidence = Evidence.from_dict(self.valid_evidence_payload)
        self.assertEqual(evidence.evidence_id, "ev-001")
        self.assertEqual(evidence.case_id, "case-123")
        self.assertEqual(evidence.kind, EvidenceKind.DIFF)
        self.assertEqual(evidence.path, "evidence/ev-001.patch")
        self.assertEqual(evidence.sha256, self.valid_evidence_payload["sha256"])
        self.assertEqual(evidence.revision, "abc1234")
        self.assertFalse(evidence.simulated)

    def test_path_posix_relative_normalization_and_rejections(self) -> None:
        """Requirement 3: Evidence.path POSIX relative normalization and strict rejections."""
        # 1. Normalization of redundant slashes or ./
        p = dict(self.valid_evidence_payload)
        p["path"] = "./evidence/sub//ev-001.patch"
        ev = Evidence.from_dict(p)
        self.assertEqual(ev.path, "evidence/sub/ev-001.patch")

        # Legitimate prefix ..hidden (not a .. directory traversal segment)
        p_hid = dict(self.valid_evidence_payload)
        p_hid["path"] = "..hidden"
        ev_hid = Evidence.from_dict(p_hid)
        self.assertEqual(ev_hid.path, "..hidden")

        p_hid_sub = dict(self.valid_evidence_payload)
        p_hid_sub["path"] = "..hidden/ev-001.patch"
        ev_hid_sub = Evidence.from_dict(p_hid_sub)
        self.assertEqual(ev_hid_sub.path, "..hidden/ev-001.patch")

        # 2. Rejections (including exact user examples)
        invalid_paths = [
            "/etc/passwd",  # absolute
            "../x",  # parent traversal
            "a/../../x",  # parent traversal
            "C:\\x",  # drive letter + backslash
            "",  # empty
            "./C:/x",  # drive letter after normalization
            "evidence/\0bad",  # null byte
            "/runs/case-123/evidence/ev.patch",  # absolute
            "/evidence/ev.patch",  # absolute
            "evidence/../ev.patch",  # parent traversal ..
            "../ev.patch",
            "evidence/..",
            "..",
            "evidence\\ev.patch",  # backslash
            "C:evidence/ev.patch",  # drive letter
            "d:/evidence/ev.patch",  # drive letter
            "   ",  # whitespace
            ".",  # dot
            "./",  # dot-slash
        ]
        for bad_path in invalid_paths:
            with self.subTest(bad_path=bad_path):
                p_bad = dict(self.valid_evidence_payload)
                p_bad["path"] = bad_path
                with self.assertRaises(ContractValidationError):
                    Evidence.from_dict(p_bad)

    def test_sha256_lowercase_hex_validation(self) -> None:
        """Requirement 3: sha256 exactly 64 lowercase hex characters."""
        # 1. Exactly 64 lowercase hex is valid
        valid_sha = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        p = dict(self.valid_evidence_payload)
        p["sha256"] = valid_sha
        ev = Evidence.from_dict(p)
        self.assertEqual(ev.sha256, valid_sha)

        # 2. Rejections: uppercase hex, length != 64, non-hex chars, trailing newline
        invalid_shas = [
            valid_sha + "\n",  # trailing newline rejected by fullmatch
            "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",  # uppercase
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b85",  # 63 chars
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b8550",  # 65 chars
            "g3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # non-hex char 'g'
            "",
            None,
        ]
        for bad_sha in invalid_shas:
            with self.subTest(bad_sha=bad_sha):
                p_bad = dict(self.valid_evidence_payload)
                p_bad["sha256"] = bad_sha
                with self.assertRaises(ContractValidationError):
                    Evidence.from_dict(p_bad)

    def test_evidence_created_at_requires_utc_iso8601(self) -> None:
        """Evidence.created_at requires valid UTC ISO 8601 timestamp."""
        p = dict(self.valid_evidence_payload)
        p["created_at"] = "2026-11-07T12:05:00+00:00"
        ev = Evidence.from_dict(p)
        self.assertEqual(ev.created_at, "2026-11-07T12:05:00+00:00")

        for bad_ts in ["2026-11-07T12:05:00", "2026-11-07T12:05:00+04:00", "bad_date", None]:
            with self.subTest(ts=bad_ts):
                p_bad = dict(self.valid_evidence_payload)
                p_bad["created_at"] = bad_ts
                with self.assertRaises(ContractValidationError):
                    Evidence.from_dict(p_bad)

    def test_evidence_rejects_none_and_whitespace_strings(self) -> None:
        """Finding 2: Evidence.from_dict with None or empty must not become string 'None'."""
        for field_name in ["evidence_id", "case_id", "path", "sha256", "created_at"]:
            for invalid_val in [None, "", "   ", 123, {}]:
                with self.subTest(field=field_name, val=invalid_val):
                    payload = dict(self.valid_evidence_payload)
                    payload[field_name] = invalid_val
                    with self.assertRaises(ContractValidationError):
                        Evidence.from_dict(payload)

    def test_evidence_rejects_invalid_kind_enum(self) -> None:
        """Finding 1: Evidence rejects invalid kind enum values."""
        payload = dict(self.valid_evidence_payload)
        payload["kind"] = "not_a_kind"
        with self.assertRaises(ContractValidationError):
            Evidence.from_dict(payload)

    def test_evidence_simulated_rejects_non_bool(self) -> None:
        """Finding 4: Reject non-bool for simulated (e.g. 'false', 'true', 0, 1, None)."""
        for invalid_bool in ["false", "true", 0, 1, None, "0", "1"]:
            with self.subTest(val=invalid_bool):
                payload = dict(self.valid_evidence_payload)
                payload["simulated"] = invalid_bool
                with self.assertRaises(ContractValidationError):
                    Evidence.from_dict(payload)

    def test_evidence_json_serialization_roundtrip(self) -> None:
        evidence = Evidence.from_dict(self.valid_evidence_payload)
        json_str = evidence.to_json()
        restored = Evidence.from_json(json_str)

        self.assertEqual(evidence.to_dict(), restored.to_dict())
        self.assertEqual(restored.evidence_id, "ev-001")
        self.assertEqual(restored.kind, EvidenceKind.DIFF)


class TestStageContracts(unittest.TestCase):
    """Test all stage input/output models and protocols (RFC-0001 §3.3)."""

    def test_report_input_valid_and_invalid_channel(self) -> None:
        """Finding 1: ReportInput.channel rejects invalid enums."""
        item = ReportInput.from_dict({
            "client_id": "c1",
            "repo_ref": "org/repo",
            "channel": "api",
            "report_text": "text",
        })
        self.assertEqual(item.client_id, "c1")
        self.assertEqual(item.channel, ChannelType.API)

        with self.assertRaises(ContractValidationError):
            ReportInput.from_dict({
                "client_id": "c1",
                "repo_ref": "org/repo",
                "channel": "bad_channel",
                "report_text": "text",
            })

    def test_triage_record_and_needs_info(self) -> None:
        tr = TriageRecord.from_dict({
            "input": "coupon code 20OFF",
            "expected": "180.00",
            "observed": "200.00",
            "suspect_files": ["cart.py"],
            "confidence": 0.95,
        })
        self.assertEqual(tr.expected, "180.00")
        self.assertEqual(tr.confidence, 0.95)
        self.assertEqual(tr.suspect_files, ("cart.py",))

        with self.assertRaises(ContractValidationError):
            TriageRecord(input="a", expected="b", observed="c", confidence=1.5)

        ni = NeedsInfo.from_dict({
            "missing_fields": ["coupon_code"],
            "question_to_support": "Qual o codigo do cupom utilizado?",
        })
        self.assertEqual(ni.missing_fields, ("coupon_code",))
        self.assertIn("codigo", ni.question_to_support)

    def test_repro_result_valid_and_invalid_outcome(self) -> None:
        """Finding 1: ReproResult rejects invalid outcome enums."""
        rr = ReproResult.from_dict({
            "test_path": "tests/test_coupon.py",
            "test_source_ref": "ev-src-1",
            "exit_code": 1,
            "outcome": "red_on_assertion",
            "failing_assertion": "assert total == 180",
            "log_ref": "ev-log-1",
        })
        self.assertEqual(rr.outcome, ReproOutcome.RED_ON_ASSERTION)
        self.assertEqual(rr.exit_code, 1)

        with self.assertRaises(ContractValidationError):
            ReproResult.from_dict({
                "test_path": "tests/test_coupon.py",
                "test_source_ref": "ev-src-1",
                "exit_code": 1,
                "outcome": "orange",
            })

    def test_patch_rejects_non_bool_flags(self) -> None:
        """Finding 4: touches_tests and touches_ci reject non-bool."""
        valid_payload = {
            "diff_ref": "ev-diff-1",
            "files_changed": ["cart.py"],
            "touches_tests": False,
            "touches_ci": False,
        }
        patch = Patch.from_dict(valid_payload)
        self.assertFalse(patch.touches_tests)
        self.assertEqual(patch.files_changed, ("cart.py",))

        for invalid_val in ["false", "true", 0, 1, None]:
            with self.subTest(field="touches_tests", val=invalid_val):
                p = dict(valid_payload)
                p["touches_tests"] = invalid_val
                with self.assertRaises(ContractValidationError):
                    Patch.from_dict(p)

            with self.subTest(field="touches_ci", val=invalid_val):
                p = dict(valid_payload)
                p["touches_ci"] = invalid_val
                with self.assertRaises(ContractValidationError):
                    Patch.from_dict(p)

    def test_verdict_verified_invariants(self) -> None:
        """Finding 3: Verdict verified consistency rules (RFC-0001 §3.3)."""
        valid_before = ContractTestRun(command="pytest test_repro.py", exit_code=1, duration_s=1.2, log_ref="log1")
        valid_after = ContractTestRun(command="pytest test_repro.py", exit_code=0, duration_s=1.1, log_ref="log2")
        valid_suite = ContractTestRun(command="pytest", exit_code=0, duration_s=5.4, log_ref="log3")

        # 1. Valid verified verdict succeeds
        verdict = Verdict(
            before=valid_before,
            after=valid_after,
            suite=valid_suite,
            base_revision="rev-before",
            fix_revision="rev-after",
            result=VerdictResult.VERIFIED,
            reasons=["Bug verified"],
        )
        self.assertEqual(verdict.result, VerdictResult.VERIFIED)

        # 2. Negative condition: before.exit_code == 0
        with self.assertRaises(ContractValidationError) as ctx:
            Verdict(
                before=ContractTestRun(command="pytest", exit_code=0, duration_s=1.0, log_ref="l"),
                after=valid_after,
                suite=valid_suite,
                base_revision="rev-before",
                fix_revision="rev-after",
                result=VerdictResult.VERIFIED,
            )
        self.assertIn("before.exit_code != 0", str(ctx.exception))

        # 3. Negative condition: after.exit_code != 0
        with self.assertRaises(ContractValidationError) as ctx:
            Verdict(
                before=valid_before,
                after=ContractTestRun(command="pytest", exit_code=1, duration_s=1.0, log_ref="l"),
                suite=valid_suite,
                base_revision="rev-before",
                fix_revision="rev-after",
                result=VerdictResult.VERIFIED,
            )
        self.assertIn("after.exit_code == 0", str(ctx.exception))

        # 4. Negative condition: suite.exit_code != 0
        with self.assertRaises(ContractValidationError) as ctx:
            Verdict(
                before=valid_before,
                after=valid_after,
                suite=ContractTestRun(command="pytest", exit_code=2, duration_s=1.0, log_ref="l"),
                base_revision="rev-before",
                fix_revision="rev-after",
                result=VerdictResult.VERIFIED,
            )
        self.assertIn("suite.exit_code == 0", str(ctx.exception))

        # 5. Negative condition: base_revision empty / whitespace
        for empty_rev in ["", "   "]:
            with self.assertRaises(ContractValidationError):
                Verdict(
                    before=valid_before,
                    after=valid_after,
                    suite=valid_suite,
                    base_revision=empty_rev,
                    fix_revision="rev-after",
                    result=VerdictResult.VERIFIED,
                )

        # 6. Negative condition: fix_revision empty / whitespace
        for empty_rev in ["", "   "]:
            with self.assertRaises(ContractValidationError):
                Verdict(
                    before=valid_before,
                    after=valid_after,
                    suite=valid_suite,
                    base_revision="rev-before",
                    fix_revision=empty_rev,
                    result=VerdictResult.VERIFIED,
                )

        # 7. Non-verified verdicts allow exit codes != 0 and rejected requires explanatory reasons
        rejected = Verdict(
            before=ContractTestRun(command="pytest", exit_code=0, duration_s=1.0, log_ref="l"),
            after=ContractTestRun(command="pytest", exit_code=1, duration_s=1.0, log_ref="l"),
            suite=ContractTestRun(command="pytest", exit_code=1, duration_s=1.0, log_ref="l"),
            base_revision="rev-before",
            fix_revision="rev-after",
            result=VerdictResult.REJECTED,
            reasons=("reproduction still failed after fix",),
        )
        self.assertEqual(rejected.result, VerdictResult.REJECTED)

    def test_verdict_reasons_and_rejected_strictness(self) -> None:
        """Requirement 5: reasons non-empty strings, rejected requires reason and both revisions."""
        valid_before = ContractTestRun("pytest repro.py", 1, 1.2, "log1")
        valid_after = ContractTestRun("pytest repro.py", 0, 1.1, "log2")
        valid_suite = ContractTestRun("pytest", 0, 5.4, "log3")

        # 1. reasons cannot contain empty items
        with self.assertRaises(ContractValidationError):
            Verdict(
                before=valid_before,
                after=valid_after,
                suite=valid_suite,
                base_revision="b1",
                fix_revision="f1",
                result=VerdictResult.VERIFIED,
                reasons=("valid", ""),
            )

        # 2. rejected requires reasons to have at least one item
        with self.assertRaises(ContractValidationError):
            Verdict(
                before=valid_before,
                after=ContractTestRun("pytest repro.py", 1, 1.0, "l"),
                suite=valid_suite,
                base_revision="b1",
                fix_revision="f1",
                result=VerdictResult.REJECTED,
                reasons=(),
            )

        # 3. rejected requires both base_revision and fix_revision non-empty
        with self.assertRaises(ContractValidationError):
            Verdict(
                before=valid_before,
                after=ContractTestRun("pytest repro.py", 1, 1.0, "l"),
                suite=valid_suite,
                base_revision="",
                fix_revision="f1",
                result=VerdictResult.REJECTED,
                reasons=("patch introduced regression",),
            )
        with self.assertRaises(ContractValidationError):
            Verdict(
                before=valid_before,
                after=ContractTestRun("pytest repro.py", 1, 1.0, "l"),
                suite=valid_suite,
                base_revision="b1",
                fix_revision="   ",
                result=VerdictResult.REJECTED,
                reasons=("patch introduced regression",),
            )

        # 4. Valid rejected verdict
        v_rej = Verdict(
            before=valid_before,
            after=ContractTestRun("pytest repro.py", 1, 1.0, "l"),
            suite=valid_suite,
            base_revision="b1",
            fix_revision="f1",
            result=VerdictResult.REJECTED,
            reasons=("patch did not resolve assertion",),
        )
        self.assertEqual(v_rej.result, VerdictResult.REJECTED)

    def test_delivery_result_and_invalid_kind(self) -> None:
        """Finding 1: DeliveryResult rejects invalid kind enums."""
        deliv = DeliveryResult.from_dict({
            "kind": "local_package",
            "url_or_path": "runs/case-1/delivery/",
            "label": "PR não publicado",
            "evidence_refs": ["ev-1"],
        })
        self.assertEqual(deliv.kind, DeliveryKind.LOCAL_PACKAGE)
        self.assertEqual(deliv.evidence_refs, ("ev-1",))

        with self.assertRaises(ContractValidationError):
            DeliveryResult.from_dict({
                "kind": "ftp_upload",
                "url_or_path": "runs/case-1/",
            })

    def test_customer_message_and_invalid_channel(self) -> None:
        """Finding 1: CustomerMessage rejects invalid channel enums."""
        msg = CustomerMessage.from_dict({
            "channel": "simulated_chat",
            "text": "O desconto de cupom foi corrigido.",
            "sent_after_event_seq": 10,
        })
        self.assertEqual(msg.channel, ChannelType.SIMULATED_CHAT)

        with self.assertRaises(ContractValidationError):
            CustomerMessage.from_dict({
                "channel": "slack",
                "text": "test",
                "sent_after_event_seq": 1,
            })

    def test_exec_result_rejects_non_bool_timed_out(self) -> None:
        """Finding 4: timed_out rejects non-bool."""
        res = ExecResult.from_dict({
            "exit_code": 0,
            "stdout_ref": "ev-out",
            "stderr_ref": "ev-err",
            "timed_out": False,
        })
        self.assertFalse(res.timed_out)

        for invalid_val in ["false", "true", 0, 1, None]:
            with self.subTest(val=invalid_val):
                with self.assertRaises(ContractValidationError):
                    ExecResult.from_dict({
                        "exit_code": 0,
                        "stdout_ref": "ev-out",
                        "stderr_ref": "ev-err",
                        "timed_out": invalid_val,
                    })

    def test_llm_result_rejects_non_bool_mock(self) -> None:
        """Finding 4: mock rejects non-bool."""
        llm = LLMResult.from_dict({
            "content": '{"analysis": "ok"}',
            "tokens_in": 120,
            "tokens_out": 45,
            "provider": "mock",
            "model": "mock-v1",
            "mock": True,
        })
        self.assertTrue(llm.mock)

        for invalid_val in ["false", "true", 0, 1, None]:
            with self.subTest(val=invalid_val):
                with self.assertRaises(ContractValidationError):
                    LLMResult.from_dict({
                        "content": "test",
                        "provider": "mock",
                        "model": "mock-v1",
                        "mock": invalid_val,
                    })

    def test_stage_models_roundtrip(self) -> None:
        """Requirement 7: Roundtrip tests for DeliveryResult, CustomerMessage and others."""
        # DeliveryResult
        dr = DeliveryResult(
            kind=DeliveryKind.LOCAL_PACKAGE,
            url_or_path="runs/case-123/delivery/",
            label="PR não publicado",
            evidence_refs=("ev-1", "ev-2"),
        )
        dr_json = dr.to_json()
        dr_restored = DeliveryResult.from_json(dr_json)
        self.assertEqual(dr.to_dict(), dr_restored.to_dict())

        # CustomerMessage
        cm = CustomerMessage(
            channel=ChannelType.SIMULATED_CHAT,
            text="O cupom foi aplicado com sucesso.",
            sent_after_event_seq=15,
        )
        cm_json = cm.to_json()
        cm_restored = CustomerMessage.from_json(cm_json)
        self.assertEqual(cm.to_dict(), cm_restored.to_dict())

        # Test from_json error translation for stage models
        for model_cls in [ReportInput, TriageRecord, NeedsInfo, ReproResult, Patch, ContractTestRun, Verdict, DeliveryResult, CustomerMessage, ExecResult, LLMResult]:
            with self.subTest(cls=model_cls.__name__):
                with self.assertRaises(ContractValidationError):
                    model_cls.from_json("invalid json syntax")
                with self.assertRaises(ContractValidationError):
                    model_cls.from_json("[1, 2, 3]")

    def test_protocols_structural_verification(self) -> None:
        """Requirement 7: Protocols structural verification with minimal implementations."""

        class MinimalIntake:
            def create(self, report: ReportInput) -> RunState:
                return RunState(
                    case_id="c-1",
                    client_id=report.client_id,
                    repo_ref=report.repo_ref,
                    channel=report.channel,
                    report_text=report.report_text,
                    state=CaseState.CREATED,
                    created_at="2026-11-07T12:00:00Z",
                    updated_at="2026-11-07T12:00:00Z",
                )

        class MinimalTriage:
            def run(self, case: RunState) -> TriageRecord | NeedsInfo:
                return TriageRecord(input="in", expected="exp", observed="obs")

        class MinimalReproduction:
            def run(self, case: RunState, triage: TriageRecord) -> ReproResult:
                return ReproResult("test.py", "ref1", 1, ReproOutcome.RED_ON_ASSERTION)

        class MinimalFix:
            def run(self, case: RunState, triage: TriageRecord, repro: ReproResult) -> Patch:
                return Patch("diff1", ("app.py",))

        class MinimalVerification:
            def run(self, case: RunState, repro: ReproResult, patch: Patch) -> Verdict:
                tr = ContractTestRun("cmd", 0, 1.0, "log")
                return Verdict(tr, tr, tr, "b", "f", VerdictResult.ENV_ERROR)

        class MinimalDelivery:
            def build(self, case: RunState, verdict: Verdict) -> DeliveryResult:
                return DeliveryResult(DeliveryKind.LOCAL_PACKAGE, "pkg/path")

        class MinimalReply:
            def compose(self, case: RunState, outcome: Any) -> CustomerMessage:
                return CustomerMessage(ChannelType.API, "msg", 1)

        class MinimalSandbox:
            def exec(self, workdir_ref: str, command: str, timeout_s: float) -> ExecResult:
                return ExecResult(0, "out", "err")

        class MinimalLLM:
            def complete(self, purpose: str, messages: list[dict[str, str]], schema: Any = None) -> LLMResult:
                return LLMResult("content", 1, 1, "mock", "v1")

        self.assertIsInstance(MinimalIntake(), IntakeStage)
        self.assertIsInstance(MinimalTriage(), TriageStage)
        self.assertIsInstance(MinimalReproduction(), ReproductionStage)
        self.assertIsInstance(MinimalFix(), FixStage)
        self.assertIsInstance(MinimalVerification(), VerificationStage)
        self.assertIsInstance(MinimalDelivery(), DeliveryStage)
        self.assertIsInstance(MinimalReply(), ReplyStage)
        self.assertIsInstance(MinimalSandbox(), SandboxStage)
        self.assertIsInstance(MinimalLLM(), LLMStage)

    def test_collections_raw_validation_rejects_non_sequences(self) -> None:
        """Finding 2: Collections in from_dict/from_json must reject null, 42, string, dict."""
        import json

        bad_values = [None, 42, "a_raw_string", {"key": "val"}]

        run_state_payload = {
            "case_id": "case-123",
            "client_id": "client-abc",
            "repo_ref": "octocat/Hello-World",
            "channel": "slack",
            "report_text": "Bug report text",
            "state": "created",
            "created_at": "2026-11-07T12:00:00Z",
            "updated_at": "2026-11-07T12:00:00Z",
        }
        event_payload = {
            "case_id": "case-123",
            "event_id": "evt-001",
            "ts": "2026-11-07T12:00:00Z",
            "source": "coordinator",
            "type": "note_added",
        }

        # 1. RunState.evidence_ids
        for bad_val in bad_values:
            with self.subTest(collection="RunState.evidence_ids", val=bad_val):
                p = dict(run_state_payload)
                p["evidence_ids"] = bad_val
                with self.assertRaises(ContractValidationError):
                    RunState.from_dict(p)
                with self.assertRaises(ContractValidationError):
                    RunState.from_json(json.dumps(p))

        # 2. Event.evidence_refs
        for bad_val in bad_values:
            with self.subTest(collection="Event.evidence_refs", val=bad_val):
                p = dict(event_payload)
                p["evidence_refs"] = bad_val
                with self.assertRaises(ContractValidationError):
                    Event.from_dict(p)
                with self.assertRaises(ContractValidationError):
                    Event.from_json(json.dumps(p))

        # 3. TriageRecord.suspect_files
        for bad_val in bad_values:
            with self.subTest(collection="TriageRecord.suspect_files", val=bad_val):
                p = {"input": "in", "expected": "exp", "observed": "obs", "suspect_files": bad_val}
                with self.assertRaises(ContractValidationError):
                    TriageRecord.from_dict(p)
                with self.assertRaises(ContractValidationError):
                    TriageRecord.from_json(json.dumps(p))

        # 4. NeedsInfo.missing_fields
        for bad_val in bad_values:
            with self.subTest(collection="NeedsInfo.missing_fields", val=bad_val):
                p = {"missing_fields": bad_val, "question_to_support": "Why?"}
                with self.assertRaises(ContractValidationError):
                    NeedsInfo.from_dict(p)
                with self.assertRaises(ContractValidationError):
                    NeedsInfo.from_json(json.dumps(p))

        # 5. Patch.files_changed
        for bad_val in bad_values:
            with self.subTest(collection="Patch.files_changed", val=bad_val):
                p = {"diff_ref": "diff/1", "files_changed": bad_val}
                with self.assertRaises(ContractValidationError):
                    Patch.from_dict(p)
                with self.assertRaises(ContractValidationError):
                    Patch.from_json(json.dumps(p))

        # 6. Verdict.reasons
        for bad_val in bad_values:
            with self.subTest(collection="Verdict.reasons", val=bad_val):
                tr = {"command": "pytest", "exit_code": 0, "duration_s": 1.0, "output_ref": "out"}
                p = {
                    "before": tr,
                    "after": tr,
                    "suite": tr,
                    "base_revision": "rev1",
                    "fix_revision": "rev2",
                    "result": "env_error",
                    "reasons": bad_val,
                }
                with self.assertRaises(ContractValidationError):
                    Verdict.from_dict(p)
                with self.assertRaises(ContractValidationError):
                    Verdict.from_json(json.dumps(p))

        # 7. DeliveryResult.evidence_refs
        for bad_val in bad_values:
            with self.subTest(collection="DeliveryResult.evidence_refs", val=bad_val):
                p = {"kind": "local_package", "url_or_path": "path/pkg", "evidence_refs": bad_val}
                with self.assertRaises(ContractValidationError):
                    DeliveryResult.from_dict(p)
                with self.assertRaises(ContractValidationError):
                    DeliveryResult.from_json(json.dumps(p))


if __name__ == "__main__":
    unittest.main()
