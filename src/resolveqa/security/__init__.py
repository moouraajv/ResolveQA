"""Black-box security helpers for Trilha B (RNF-01, RNF-02, RFC §6)."""

from .scan import SecretFinding, find_secrets_in_text, scan_paths_for_secrets

__all__ = [
    "SecretFinding",
    "find_secrets_in_text",
    "scan_paths_for_secrets",
]
