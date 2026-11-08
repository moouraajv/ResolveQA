"""ResolveQA demo executor; missing stages never become fabricated successes."""
from .runner import COUPON_REPORT, VAGUE_REPORT, DemoResult, MissingComponents, run_demo

__all__ = ['COUPON_REPORT', 'VAGUE_REPORT', 'DemoResult', 'MissingComponents', 'run_demo']
