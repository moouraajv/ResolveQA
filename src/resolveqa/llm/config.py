"""Configuration loader for the ResolveQA LLM adapter and Featherless provider (Issue #8)."""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_LLM_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
ALLOWED_FEATHERLESS_HOST = "api.featherless.ai"


def validate_featherless_endpoint(url: str) -> str:
    """Validate that `url` uses scheme `https` and exact host `api.featherless.ai` with no port or userinfo."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Featherless endpoint must be a non-empty string.")
    cleaned = url.strip()
    if any(ch.isspace() or ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"Invalid control/whitespace characters in Featherless endpoint: {url!r}")

    parsed = urllib.parse.urlsplit(cleaned)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_FEATHERLESS_HOST
        or parsed.netloc != ALLOWED_FEATHERLESS_HOST
        or parsed.port is not None
        or ":" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or not parsed.path.startswith("/")
        or ".." in parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"Invalid Featherless endpoint {url!r}: scheme must be 'https' and host must be "
            f"exactly '{ALLOWED_FEATHERLESS_HOST}' without custom port, userinfo, query, or fragment."
        )
    return cleaned


@dataclass(frozen=True)
class LLMConfig:
    """Immutable configuration for Featherless and fallback mock LLM execution."""

    provider: str
    endpoint: str
    primary_model: str
    fallback_model: str
    mock_provider: str
    mock_model: str
    temperature: float
    max_tokens: int
    timeout_s: float
    max_retries: int
    retryable_status_codes: tuple[int, ...]
    env_file: str
    env_key_name: str

    def __post_init__(self) -> None:
        validated = validate_featherless_endpoint(self.endpoint)
        object.__setattr__(self, "endpoint", validated)


def load_llm_config(config_path: Path | str | None = None) -> LLMConfig:
    """Load and validate `LLMConfig` from `src/resolveqa/llm/config.json` (or a custom path)."""
    target = Path(config_path) if config_path is not None else DEFAULT_LLM_CONFIG_PATH
    if not target.is_file():
        raise FileNotFoundError(f"LLM configuration file not found: {target}")
    raw: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"LLM configuration must be a JSON object: {target}")

    endpoint = validate_featherless_endpoint(str(raw.get("endpoint", "")))
    return LLMConfig(
        provider=str(raw["provider"]),
        endpoint=endpoint,
        primary_model=str(raw["primary_model"]),
        fallback_model=str(raw["fallback_model"]),
        mock_provider=str(raw.get("mock_provider", "mock")),
        mock_model=str(raw.get("mock_model", "deterministic-mock-v1")),
        temperature=float(raw.get("temperature", 0)),
        max_tokens=int(raw.get("max_tokens", 1500)),
        timeout_s=float(raw.get("timeout_s", 60.0)),
        max_retries=int(raw.get("max_retries", 1)),
        retryable_status_codes=tuple(int(c) for c in raw.get("retryable_status_codes", [429, 503])),
        env_file=str(raw.get("env_file", "~/.config/resolveqa/featherless.env")),
        env_key_name=str(raw.get("env_key_name", "FEATHERLESS_API_KEY")),
    )
