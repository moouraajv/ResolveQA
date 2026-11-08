"""Intake package (Trilha B): case creation from ReportInput (RF-01)."""

from .service import Intake, new_case_id, utc_now_iso
from .store import EphemeralCaseStore

__all__ = [
    "EphemeralCaseStore",
    "Intake",
    "new_case_id",
    "utc_now_iso",
]
