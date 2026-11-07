"""Unit tests and regression test suite for ResolveQA contracts (RFC-0001 §3)."""

from dataclasses import FrozenInstanceError
import unittest

from resolveqa.contracts import (
    Attempts,
    CaseState,
    ChannelType,
    ContractValidationError,
    CustomerMessage,
    DeliveryKind,
    DeliveryResult,
    Event,
    EventSource,
    EventType,
    Evidence,
    EvidenceKind,
    ExecResult,
    LLMResult,
    NeedsInfo,
    Patch,
    ReplayRef,
    ReportInput,
    ReproOutcome,
    ReproResult,
    RunState,
    TestRun as ContractTestRun,
    TriageRecord,
    Verdict,
    VerdictResult,
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
        # Valid with +00:00 offset
        p_offset = dict(self.valid_payload)
        p_offset["created_at"] = "2026-11-07T12:00:00+00:00"
        p_offset["updated_at"] = "2026-11-07T12:05:00+00:00"
        rs = RunState.from_dict(p_offset)
        self.assertEqual(rs.created_at, "2026-11-07T12:00:00+00:00")

        # Invalid timestamps: naive, non-UTC offset, invalid strings, non-string
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
                self.assertIn("requires terminal_reason", str(ctx.exception))

                payload["terminal_reason"] = "   "
                with self.assertRaises(ContractValidationError):
                    RunState.from_dict(payload)

                payload["terminal_reason"] = "limit_exceeded"
                run_state = RunState.from_dict(payload)
                self.assertEqual(run_state.state, term_state)
                self.assertEqual(run_state.terminal_reason, "limit_exceeded")

    def test_verified_terminal_state_does_not_require_reason(self) -> None:
        """Verified terminal state does not require a terminal_reason (RFC-0001 §4)."""
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

        # Transition to blocked with terminal_reason must succeed
        s3 = run_state.transition_to(
            CaseState.BLOCKED,
            updated_at="2026-11-07T12:02:00Z",
            terminal_reason="not_reproduced",
        )
        self.assertEqual(s3.state, CaseState.BLOCKED)
        self.assertEqual(s3.terminal_reason, "not_reproduced")

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

    def test_event_json_serialization_roundtrip(self) -> None:
        event = Event.from_dict(self.valid_event_payload)
        json_str = event.to_json()
        restored = Event.from_json(json_str)

        self.assertEqual(event.to_dict(), restored.to_dict())
        self.assertEqual(restored.event_id, "evt-001")


class TestEvidenceContract(unittest.TestCase):
    """Test suite for Evidence model and serialization (RFC-0001 §3.4)."""

    def setUp(self) -> None:
        # Note: path is relative to runs/<case_id>/ per RFC-0001 §3.4
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

    def test_evidence_created_at_requires_utc_iso8601(self) -> None:
        """Evidence.created_at requires valid UTC ISO 8601 timestamp."""
        # Valid with +00:00
        p = dict(self.valid_evidence_payload)
        p["created_at"] = "2026-11-07T12:05:00+00:00"
        ev = Evidence.from_dict(p)
        self.assertEqual(ev.created_at, "2026-11-07T12:05:00+00:00")

        # Invalid
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
    """Test all stage input/output models from RFC-0001 §3.3."""

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

        # 7. Non-verified verdicts allow exit codes != 0 and are not constrained by verified rules
        rejected = Verdict(
            before=ContractTestRun(command="pytest", exit_code=0, duration_s=1.0, log_ref="l"),
            after=ContractTestRun(command="pytest", exit_code=1, duration_s=1.0, log_ref="l"),
            suite=ContractTestRun(command="pytest", exit_code=1, duration_s=1.0, log_ref="l"),
            base_revision="rev-before",
            fix_revision="rev-after",
            result=VerdictResult.REJECTED,
        )
        self.assertEqual(rejected.result, VerdictResult.REJECTED)

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


if __name__ == "__main__":
    unittest.main()
