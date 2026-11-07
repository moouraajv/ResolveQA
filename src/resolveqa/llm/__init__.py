"""ResolveQA LLM adapter package (Track A — RFC-0001 §3.3, §6.2, D3)."""

from .adapter import (
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
    "DeterministicMockLLM",
    "LLMAdapter",
    "LLMLimitExceededError",
    "LLMOutputError",
    "build_delimited_messages",
    "delimit_untrusted_data",
    "load_max_llm_calls",
    "validate_llm_output",
]
