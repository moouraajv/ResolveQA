"""Canal simulado (Trilha B, RF-02 / RNF-07): UI de conversa rotulada, sem WhatsApp real."""

from .simulated import (
    SIMULATED_CHANNEL_LABEL,
    build_chat_html,
    submit_simulated_chat_report,
)

__all__ = [
    "SIMULATED_CHANNEL_LABEL",
    "build_chat_html",
    "submit_simulated_chat_report",
]
