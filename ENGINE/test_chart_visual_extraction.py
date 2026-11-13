"""Unit tests for SQAO chart visual extraction; no OCR binary required."""
from __future__ import annotations

import unittest

from ENGINE.chart_visual_extraction import (
    _axis_calibration, _extract_indicator_readings, _num, table18_template,
)


class ChartVisualExtractionTests(unittest.TestCase):
    def test_macd_visible_pair(self):
        result = _extract_indicator_readings("Step Index MACD(12,26,9) -2.18 1.73")
        self.assertEqual(result["macd_12_26_9_visible_pair"], [-2.18, 1.73])

    def test_axis_calibration(self):
        tokens = [
            {"text": "7400.0", "x": 950, "y": 100, "height": 10, "confidence": 90},
            {"text": "7300.0", "x": 950, "y": 200, "height": 10, "confidence": 90},
            {"text": "7200.0", "x": 950, "y": 300, "height": 10, "confidence": 90},
        ]
        result = _axis_calibration(tokens, 1000)
        self.assertEqual(result["status"], "CALIBRATED")
        self.assertAlmostEqual(result["price_per_pixel"], -1.0, places=6)

    def test_locale_price_parsing(self):
        self.assertEqual(_num("7,306.3"), 7306.3)
        self.assertEqual(_num("7.306,3"), 7306.3)
        self.assertEqual(_num("7306,3"), 7306.3)

    def test_table18_keeps_unknowns_null(self):
        table = table18_template(7306.3)
        self.assertEqual(table["LONG"]["reference_price"], 7306.3)
        self.assertIsNone(table["LONG"]["entry_price"])
        self.assertIsNone(table["SHORT"]["stop_loss"])
        self.assertEqual(table["LONG"]["decision"], "NO_TRADE")


if __name__ == "__main__":
    unittest.main()
