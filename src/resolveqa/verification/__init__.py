"""ResolveQA verification package (Track A — Issue #12, RF-06, RFC-0001 §3.3)."""

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
    "Verification",
    "Verifier",
    "apply_unified_diff",
    "compute_tree_revision",
    "inspect_test_oracle",
]
