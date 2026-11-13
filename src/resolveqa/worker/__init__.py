"""Cloud / local worker that drains the case queue and runs the pipeline."""

from .loop import process_job, run_forever

__all__ = ["process_job", "run_forever"]
