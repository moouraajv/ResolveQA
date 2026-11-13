"""Public environment label for UI banners and /health (not a secret)."""

from __future__ import annotations

import os


def environment_name() -> str:
    """Return RESOLVEQA_ENVIRONMENT (staging|demo|production|local). Default: local."""
    raw = (os.environ.get("RESOLVEQA_ENVIRONMENT") or "").strip().lower()
    if raw in {"staging", "demo", "production", "prod", "local", "hackathon"}:
        return "production" if raw == "prod" else raw
    return "local"


def environment_banner(*, storage: str | None = None) -> str:
    """Short Portuguese banner for intake/chat HTML."""
    env = environment_name()
    store = storage or os.environ.get("RESOLVEQA_CASE_STORE", "memory").strip().lower()
    if env == "staging":
        return (
            "Ambiente staging — protótipo público AKCIT; "
            f"armazenamento={store}; fila de agentes ativa; sem autenticação."
        )
    if env == "production":
        return f"Ambiente produção — armazenamento={store}."
    if env == "demo":
        return "Demo — armazenamento efêmero; sem autenticação, sem persistência."
    return "Ambiente local — armazenamento efêmero em memória; sem autenticação."
