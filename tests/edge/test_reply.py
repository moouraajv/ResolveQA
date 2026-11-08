"""Edge tests for Reply.compose (issue #17, RF-09)."""

from __future__ import annotations

import unittest

from resolveqa.contracts import (
    BlockedReason,
    BlockedTerminalReason,
    CaseState,
    ChannelType,
    Event,
    EventSource,
    EventType,
    InfraErrorTerminalReason,
    NeedsInfoTerminalReason,
    RunState,
)
from resolveqa.reply import ReplyComposeError, ReplyComposer, ReplyOutcome


def _case(*, state: CaseState, channel: ChannelType = ChannelType.SIMULATED_CHAT, **kwargs) -> RunState:
    return RunState(
        case_id=kwargs.get("case_id", "case-reply-1"),
        client_id="client-demo",
        repo_ref="demo-target",
        channel=channel,
        report_text="total saiu R$ 200,00 em vez de R$ 180,00",
        state=state,
        created_at="2026-11-07T12:00:00Z",
        updated_at="2026-11-07T12:05:00Z",
        terminal_reason=kwargs.get("terminal_reason"),
    )


def _verified_events(case_id: str = "case-reply-1") -> list[Event]:
    return [
        Event(
            event_id="e0",
            case_id=case_id,
            seq=0,
            ts="2026-11-07T12:00:00Z",
            source=EventSource.INTAKE,
            type=EventType.CASE_CREATED,
        ),
        Event(
            event_id="e1",
            case_id=case_id,
            seq=1,
            ts="2026-11-07T12:04:00Z",
            source=EventSource.VERIFICATION,
            type=EventType.STATE_CHANGED,
            from_state=CaseState.VERIFYING,
            to_state=CaseState.VERIFIED,
        ),
    ]


class TestReplyCompose(unittest.TestCase):
    def setUp(self) -> None:
        self.composer = ReplyComposer()

    def test_verified_message_cites_corrected_behavior(self) -> None:
        message = self.composer.compose(
            _case(state=CaseState.VERIFIED),
            ReplyOutcome(corrected_behavior="total agora R$ 180,00"),
            events=_verified_events(),
        )
        self.assertEqual(message.channel, ChannelType.SIMULATED_CHAT)
        self.assertIn("total agora R$ 180,00", message.text)
        self.assertGreater(message.sent_after_event_seq, 1)

    def test_success_never_before_verified_event(self) -> None:
        with self.assertRaises(ReplyComposeError):
            self.composer.compose(
                _case(state=CaseState.VERIFIED),
                ReplyOutcome(corrected_behavior="total agora R$ 180,00"),
                events=[],
            )
        with self.assertRaises(ReplyComposeError):
            self.composer.compose(
                _case(state=CaseState.VERIFIED),
                ReplyOutcome(corrected_behavior="total agora R$ 180,00"),
                events=_verified_events(),
                sent_after_event_seq=1,  # not strictly after verified seq
            )
        with self.assertRaises(ReplyComposeError):
            self.composer.compose(
                _case(state=CaseState.FIXED),
                ReplyOutcome(corrected_behavior="total agora R$ 180,00"),
                events=_verified_events(),
            )

    def test_needs_info_and_blocked_are_honest_progress(self) -> None:
        needs = self.composer.compose(
            _case(
                state=CaseState.NEEDS_INFO,
                terminal_reason=NeedsInfoTerminalReason(
                    question_to_support="qual era o valor esperado do cupom?"
                ),
            ),
            ReplyOutcome(),
            events=[],
        )
        self.assertIn("andamento", needs.text.lower())
        self.assertIn("cupom", needs.text.lower())
        self.assertNotIn("corrigimos", needs.text.lower())

        blocked = self.composer.compose(
            _case(
                state=CaseState.BLOCKED,
                terminal_reason=BlockedTerminalReason(code=BlockedReason.LIMIT_EXCEEDED),
            ),
            ReplyOutcome(),
            events=[],
        )
        self.assertIn("andamento", blocked.text.lower())
        self.assertNotIn("corrigimos", blocked.text.lower())

    def test_infra_error_has_no_customer_message(self) -> None:
        with self.assertRaises(ReplyComposeError):
            self.composer.compose(
                _case(
                    state=CaseState.INFRA_ERROR,
                    terminal_reason=InfraErrorTerminalReason(detail="sandbox unavailable"),
                ),
                ReplyOutcome(),
            )


if __name__ == "__main__":
    unittest.main()
