"""Tests for SQAO image intelligence helpers."""
import unittest
from ENGINE.image_intelligence import (
    linear_price_calibration, pixel_y_to_price, monetary_scenario,
)


class ImageIntelligenceTests(unittest.TestCase):
    def test_calibration(self):
        c = linear_price_calibration(100, 8000, 500, 7000)
        self.assertAlmostEqual(pixel_y_to_price(300, c), 7500)

    def test_monetary_conversion(self):
        self.assertAlmostEqual(monetary_scenario(1.0, 0.10), 1.0)
        self.assertAlmostEqual(monetary_scenario(1.0, 0.20), 2.0)

    def test_invalid_calibration(self):
        with self.assertRaises(ValueError):
            linear_price_calibration(100, 1, 100, 2)


if __name__ == "__main__":
    unittest.main()
