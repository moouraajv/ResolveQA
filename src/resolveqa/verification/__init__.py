"""ResolveQA verification package (Track A — Issues #12, #23, RF-06, RFC-0001 §3.3)."""

from .playbook_gate import (
    PlaybookGate,
    PlaybookGateResult,
    PolicyRuleResult,
    evaluate_playbook_gate,
    extract_diff_target_paths,
)
from .verifier import (
    OracleAnalysis,
    Verification,
    Verifier,
    apply_unified_diff,
    compute_tree_revision,
    inspect_test_oracle,
)

__all__ = [
    "OracleAnalysis",
    "PlaybookGate",
    "PlaybookGateResult",
    "PolicyRuleResult",
    "Verification",
    "Verifier",
    "apply_unified_diff",
    "compute_tree_revision",
    "evaluate_playbook_gate",
    "extract_diff_target_paths",
    "inspect_test_oracle",
]
