"""Compose the Track A pipeline with a shared LLM adapter (Issue #8 live wiring).

When ``RESOLVEQA_LIVE=1`` and ``~/.config/resolveqa/featherless.env`` holds a valid
``FEATHERLESS_API_KEY`` (mode 0600), ``LLMAdapter`` talks to Featherless with
``LLMResult.mock=False``. Otherwise the deterministic mock remains labeled
``mock=True`` (RFC-0001 §9 D3).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from resolveqa.fix import FixStage
from resolveqa.llm import LLMAdapter
from resolveqa.orchestrator import Orchestrator
from resolveqa.reproduction import Reproduction
from resolveqa.store import EventStore, EvidenceStore
from resolveqa.triage import Triage
from resolveqa.verification import VerificationStage

REPO_ROOT = Path(__file__).resolve().parents[2]


def live_enabled() -> bool:
    """True when the process explicitly opted into the real Featherless provider."""
    return os.environ.get("RESOLVEQA_LIVE") == "1"


def build_llm(*, case=None, use_real: Optional[bool] = None) -> LLMAdapter:
    """Build the shared LLM adapter honoring ``RESOLVEQA_LIVE`` unless overridden."""
    kwargs: dict = {}
    if use_real is not None:
        kwargs["use_real"] = use_real
    elif live_enabled():
        kwargs["use_real"] = True
    return LLMAdapter(case=case, **kwargs)


def build_orchestrator(
    *,
    runs_root: Path | str | None = None,
    base_root: Path | str | None = None,
    llm: Optional[LLMAdapter] = None,
    use_real: Optional[bool] = None,
) -> Orchestrator:
    """Wire Triage → Reproduction → Fix → Verification with one LLM and evidence store."""
    root = Path(base_root).resolve() if base_root is not None else REPO_ROOT
    runs = Path(runs_root) if runs_root is not None else root / "runs"
    shared_llm = llm if llm is not None else build_llm(use_real=use_real)
    evidence = EvidenceStore(runs_root=runs)
    events = EventStore(runs)
    triage = Triage(llm=shared_llm, store=evidence, base_root=root)
    reproduction = Reproduction(llm=shared_llm, store=evidence, runs_root=runs, base_root=root)
    fix = FixStage(base_root=root)
    verification = VerificationStage(base_root=root)
    return Orchestrator(
        triage=triage,
        reproduction=reproduction,
        fix=fix,
        verification=verification,
        store=events,
        llm_calls_getter=triage.get_llm_calls,
    )
