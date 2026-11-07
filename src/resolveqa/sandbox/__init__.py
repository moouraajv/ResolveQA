"""ResolveQA sandbox package (Track A — RFC-0001 §3.3, §6.1, D2)."""

from .executor import LocalSandbox, Sandbox, redact_secrets

__all__ = ["LocalSandbox", "Sandbox", "redact_secrets"]
