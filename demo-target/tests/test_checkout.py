"""Unit tests for the checkout pricing module."""

from __future__ import annotations

import unittest

from checkout import calculate_total, format_brl


class TestCheckoutBase(unittest.TestCase):
    """Standard checkout validation and formatting tests."""

    def test_subtotal_without_coupon(self) -> None:
        self.assertEqual(calculate_total(200.0), 200.0)
        self.assertEqual(format_brl(calculate_total(200.0)), "R$ 200,00")

    def test_zero_subtotal(self) -> None:
        self.assertEqual(calculate_total(0.0), 0.0)

    def test_negative_subtotal_raises(self) -> None:
        with self.assertRaises(ValueError):
            calculate_total(-10.0)

    def test_invalid_coupon_percent_raises(self) -> None:
        with self.assertRaises(ValueError):
            calculate_total(100.0, coupon_percent=150.0)


if __name__ == "__main__":
    unittest.main()
