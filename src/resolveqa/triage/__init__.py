"""ResolveQA triage package (Track A - RFC-0001 section 3.3, RF-03, Issue #9)."""

from .service import (
    DEFAULT_TRIAGE_SYSTEM_INSTRUCTION,
    TRIAGE_OUTPUT_SCHEMA,
    Triage,
    run_triage,
)

__all__ = [
    "DEFAULT_TRIAGE_SYSTEM_INSTRUCTION",
    "TRIAGE_OUTPUT_SCHEMA",
    "Triage",
    "run_triage",
]
