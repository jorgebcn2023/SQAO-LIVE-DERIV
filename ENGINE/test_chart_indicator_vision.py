"""Synthetic-image tests for SQAO indicator vision; no OCR binary required."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from ENGINE.chart_indicator_vision import analyze_indicator_panes, _trend


class IndicatorVisionTests(unittest.TestCase):
    def test_pixel_evolution_direction(self):
        rising = [{"x_norm": i / 9, "y_norm": 0.8 - i * 0.05} for i in range(10)]
        self.assertEqual(_trend(rising)["direction"], "RISING")
        falling = [{"x_norm": i / 9, "y_norm": 0.2 + i * 0.05} for i in range(10)]
        self.assertEqual(_trend(falling)["direction"], "FALLING")

    def test_configured_rsi_pane_detects_colored_trace(self):
        image = np.zeros((160, 320, 3), dtype=np.uint8)
        # BGR orange continuous trace, rising in screen coordinates.
        pts = np.array([[x, 120 - x // 3] for x in range(20, 300, 4)], dtype=np.int32)
        cv2.polylines(image, [pts], False, (0, 165, 255), 3)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chart.png"
            cv2.imwrite(str(path), image)
            result = analyze_indicator_panes(path, "M5", {"RSI": [0, 0, 320, 160]})
        self.assertEqual(result["status"], "ANALYZED")
        self.assertEqual(result["panes"]["RSI"]["status"], "TRACES_FOUND")
        self.assertGreaterEqual(result["panes"]["RSI"]["trace_count"], 1)
        self.assertEqual(result["panes"]["RSI"]["association"], "OPERATOR_CONFIGURED_PANE; indicator identity is not inferred from color")

    def test_missing_rois_does_not_guess_indicators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.png"
            cv2.imwrite(str(path), np.zeros((80, 120, 3), dtype=np.uint8))
            result = analyze_indicator_panes(path, "D1", None)
        self.assertEqual(result["status"], "PANE_ROIS_REQUIRED")
        self.assertEqual(result["panes"], {})


if __name__ == "__main__":
    unittest.main()
