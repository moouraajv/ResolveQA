"""Compose honest customer messages for the same intake channel (RF-09, #17, #25)."""

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
from resolveqa.playbook import Playbook, ReplyTone


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


def _apply_tone(base: str, *, tone: ReplyTone, state: CaseState) -> str:
    """Choose wording template; facts (behavior/state) stay untouched."""
    if state == CaseState.VERIFIED:
        if tone == ReplyTone.FRIENDLY:
            return base.replace("Corrigimos o problema.", "Pronto — já corrigimos isso.")
        if tone == ReplyTone.FORMAL:
            return base.replace(
                "Corrigimos o problema.",
                "Informamos que a correção foi concluída.",
            )
        return base
    if tone == ReplyTone.FRIENDLY:
        return base.replace("Andamento:", "Atualização:")
    if tone == ReplyTone.FORMAL:
        return base.replace("Andamento:", "Comunicado de andamento:")
    return base


def _clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


class ReplyComposer:
    """Implements ReplyStage.compose without sending until contract rules pass."""

    def __init__(self, playbook: Playbook | None = None) -> None:
        self.playbook = playbook

    def compose(
        self,
        case: RunState,
        outcome: ReplyOutcome | None = None,
        *,
        events: Iterable[Event] | None = None,
        sent_after_event_seq: int | None = None,
        playbook: Playbook | None = None,
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

        book = playbook if playbook is not None else self.playbook
        tone = book.reply_tone if book is not None else ReplyTone.NEUTRAL
        max_chars = book.reply_max_chars if book is not None else 500

        facts = outcome if outcome is not None else ReplyOutcome()
        event_list = list(events or ())

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
            # Facts stay in the same fields regardless of tone.
            base = f"Corrigimos o problema. Comportamento esperado agora: {behavior}."
            text = _clip(_apply_tone(base, tone=tone, state=case.state), max_chars)
            if behavior not in text and behavior[: max(1, max_chars // 2)] not in text:
                # max_chars clipped the fact — still require the fact to appear when possible
                raise ReplyComposeError(
                    "reply.max_chars is too small to include the corrected behavior fact."
                )
            return CustomerMessage(
                channel=case.channel,
                text=text,
                sent_after_event_seq=seq,
            )

        if case.state == CaseState.NEEDS_INFO:
            question = (facts.support_question or "").strip()
            if not question and case.terminal_reason is not None:
                question = str(
                    getattr(case.terminal_reason, "question_to_support", "") or ""
                ).strip()
            if not question:
                question = "precisamos de mais informações para continuar"
            base = f"Andamento: ainda não concluímos a correção — {question}."
            text = _clip(_apply_tone(base, tone=tone, state=case.state), max_chars)
            seq = 0 if sent_after_event_seq is None else sent_after_event_seq
            return CustomerMessage(
                channel=case.channel,
                text=text,
                sent_after_event_seq=seq,
            )

        if case.state == CaseState.BLOCKED:
            detail = (facts.blocked_detail or "").strip()
            if not detail and case.terminal_reason is not None:
                detail = str(getattr(case.terminal_reason, "detail", "") or "").strip()
                code = getattr(case.terminal_reason, "code", None)
                if code is not None and not detail:
                    detail = getattr(code, "value", str(code))
            if not detail:
                detail = "o caso ficou bloqueado e segue em análise interna"
            base = f"Andamento: ainda não há correção publicada — {detail}."
            text = _clip(_apply_tone(base, tone=tone, state=case.state), max_chars)
            seq = 0 if sent_after_event_seq is None else sent_after_event_seq
            return CustomerMessage(
                channel=case.channel,
                text=text,
                sent_after_event_seq=seq,
            )

        raise ReplyComposeError(f"Unhandled terminal state: {case.state.value}")
