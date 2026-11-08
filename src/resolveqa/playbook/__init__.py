"""Project playbook loader consumed by Trilha B (subset needed by #24/#25/#26/#27).

Track A owns the full schema in #22; this module loads the JSON fields Reply/Delivery
already need so B is not blocked. Unknown keys are ignored; invalid values fail loud.
"""

from .loader import (
    ApproverWarning,
    Playbook,
    PlaybookError,
    ReplyTone,
    load_playbook,
)

__all__ = [
    "ApproverWarning",
    "Playbook",
    "PlaybookError",
    "ReplyTone",
    "load_playbook",
]
