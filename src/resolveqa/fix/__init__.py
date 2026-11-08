"""Real, bounded repair of the controlled checkout coupon defect (RF-05)."""

from .engine import FixStage, PatchRejected

__all__ = ["FixStage", "PatchRejected"]
