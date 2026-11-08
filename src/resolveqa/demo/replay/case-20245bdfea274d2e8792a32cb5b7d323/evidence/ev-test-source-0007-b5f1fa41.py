"""Auto-generated defect reproduction test (Issue #10, RF-04)."""

import unittest
from checkout import calculate_total


class TestCheckoutDefectReproduction(unittest.TestCase):
    """Verify that applying a coupon produces the expected discounted total."""

    def test_coupon_discount_applied_to_total(self) -> None:
        subtotal = 200.0
        coupon_percent = 10.0
        expected_total = 180.0

        actual_total = calculate_total(subtotal, coupon_percent=coupon_percent)
        self.assertEqual(
            actual_total,
            expected_total,
            f"Expected total with {coupon_percent}% coupon to be {expected_total}, but got {actual_total}",
        )


if __name__ == "__main__":
    unittest.main()
