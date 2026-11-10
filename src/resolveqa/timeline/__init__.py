"""Case timeline from append-only events.jsonl (RFC-0001 §3.2, RF-10)."""

from .reader import TimelineError, load_timeline
from .view import build_timeline_html, timeline_to_dict

__all__ = [
    "TimelineError",
    "build_timeline_html",
    "load_timeline",
    "timeline_to_dict",
]
