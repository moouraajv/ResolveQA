"""Compose honest customer messages for the same intake channel (RF-09)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from resolveqa.contracts import (
    CaseState,
    CustomerMessage,
    Event,
    EventType,
    RunState,
    TERMINAL_STATES,
)


class ReplyComposeError(ValueError):
    """Raised when a customer message would violate RF-09 / RFC §3.3 / §4."""


@dataclass(frozen=True)
class ReplyOutcome:
    """Facts available after a terminal transition — never invented progress."""

    corrected_behavior: str | None = None
    support_question: str | None = None
    blocked_detail: str | None = None


def _verified_event_seq(events: Sequence[Event]) -> int | None:
    for event in events:
        if (
            event.type == EventType.STATE_CHANGED
            and event.to_state == CaseState.VERIFIED
        ):
            return event.seq
    return None


class ReplyComposer:
    """Implements ReplyStage.compose without sending until contract rules pass."""

    def compose(
        self,
        case: RunState,
        outcome: ReplyOutcome | None = None,
        *,
        events: Iterable[Event] | None = None,
        sent_after_event_seq: int | None = None,
    ) -> CustomerMessage:
        if not isinstance(case, RunState):
            raise ReplyComposeError(
                f"Reply.compose expects RunState, got {type(case).__name__}."
            )
        if case.state not in TERMINAL_STATES:
            raise ReplyComposeError(
                f"Customer message requires a terminal case state, got {case.state.value}."
            )
        if case.state == CaseState.INFRA_ERROR:
            raise ReplyComposeError(
                "infra_error must not produce a customer bug/progress message (RFC §4)."
            )

        facts = outcome if outcome is not None else ReplyOutcome()
        event_list = list(events or ())
        if any(event.case_id != case.case_id for event in event_list):
            raise ReplyComposeError("Reply events must belong to the requested case.")

        if case.state == CaseState.VERIFIED:
            verified_seq = _verified_event_seq(event_list)
            if verified_seq is None:
                raise ReplyComposeError(
                    "Success message requires a StateChanged(to_state=verified) event."
                )
            seq = (
                verified_seq + 1
                if sent_after_event_seq is None
                else sent_after_event_seq
            )
            if not (verified_seq < seq):
                raise ReplyComposeError(
                    "Success message must have sent_after_event_seq greater than "
                    "the verified StateChanged seq (RFC §3.3)."
                )
            behavior = (facts.corrected_behavior or "").strip()
            if not behavior:
                raise ReplyComposeError(
                    "verified replies must cite the corrected behavior."
                )
            text = (
                f"Corrigimos o problema. Comportamento esperado agora: {behavior}."
            )
            return CustomerMessage(
                channel=case.channel,
                text=text,
                sent_after_event_seq=seq,
            )

        if case.state == CaseState.NEEDS_INFO:
            question = (facts.support_question or "").strip()
            if not question and case.terminal_reason is not None:
                question = str(getattr(case.terminal_reason, "question_to_support", "") or "").strip()
            if not question:
                question = "precisamos de mais informações para continuar"
            text = (
                "Andamento: ainda não concluímos a correção — "
                f"{question}."
            )
            seq = 0 if sent_after_event_seq is None else sent_after_event_seq
            return CustomerMessage(
                channel=case.channel,
                text=text,
                sent_after_event_seq=seq,
            )

        if case.state == CaseState.BLOCKED:
            detail = (facts.blocked_detail or "").strip()
            if not detail:
                code = getattr(getattr(case.terminal_reason, "code", None), "value", None)
                detail = {
                    "limit_exceeded": "atingimos o limite de tentativas automáticas e o caso segue com a nossa equipe",
                    "not_reproduced": "ainda não conseguimos reproduzir o problema relatado",
                    "patch_rejected": "a correção proposta não passou nas nossas verificações",
                }.get(code, "o caso ficou bloqueado e segue em análise interna")
            text = f"Andamento: ainda não há correção publicada — {detail}."
            seq = 0 if sent_after_event_seq is None else sent_after_event_seq
            return CustomerMessage(
                channel=case.channel,
                text=text,
                sent_after_event_seq=seq,
            )

        raise ReplyComposeError(f"Unhandled terminal state: {case.state.value}")


