"""LLM adapter package with deterministic mock (Issue #8, RFC-0001 §3.3, §6.2, §9 D3)."""

from .adapter import (
    ALLOWED_PURPOSES,
     DEFAULT_LIMITS_PATH,
    INERT_DATA_SYSTEM_NOTICE,
    DeterministicMockLLM,
    LLMAdapter,
    LLMLimitExceededError,
    LLMOutputError,
    build_delimited_messages,
    delimit_untrusted_data,
    load_max_llm_calls,
    validate_llm_output,
)

__all__ = [
    "ALLOWED_PURPOSES",
    "DEFAULT_LIMITS_PATH",
    "DeterministicMockLLM",
    "INERT_DATA_SYSTEM_NOTICE",
    "LLMAdapter",
    "LLMLimitExceededError",
    "LLMOutputError",
    "build_delimited_messages",
    "delimit_untrusted_data",
    "load_max_llm_calls",
    "validate_llm_output",
]
