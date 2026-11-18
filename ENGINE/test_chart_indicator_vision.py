"""Synthetic-image tests for SQAO indicator vision; no OCR binary required."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from ENGINE.chart_indicator_vision import analyze_indicator_panes, _trend, _attach_legend_identity, _semantic_observations


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


    def test_legend_hue_maps_to_line_identity(self):
        traces = [{"hue_center_hsv": 30, "points": [{"x_norm": 1.0, "y_norm": 0.4}],
                   "evolution": {"status": "TRACE_OBSERVED", "direction": "RISING"},
                   "coverage": 0.9}]
        legend = {"status": "MAPPED", "labels": {"EMA_9": {"hue_center_hsv": 32}}}
        _attach_legend_identity(traces, legend)
        self.assertEqual(traces[0]["legend_identity"]["line_id"], "EMA_9")
        self.assertEqual(traces[0]["legend_identity_status"], "MATCHED")

    def test_rsi_visual_zone_requires_axis_value(self):
        traces = [{"hue_center_hsv": 80, "coverage": 0.8,
                   "legend_identity": {"line_id": "RSI"},
                   "evolution": {"status": "TRACE_OBSERVED", "direction": "RISING"},
                   "points": [{"x_norm": 1.0, "y_norm": 0.1, "axis_value_estimate": 74.2}]}]
        result = _semantic_observations("RSI", traces, {"status": "CALIBRATED"})
        self.assertEqual(result["latest_zone_visual_estimate"], "OVERBOUGHT_ABOVE_70")
        self.assertTrue(result["numeric_readings_are_visual_estimates"])

    def test_missing_rois_does_not_guess_indicators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.png"
            cv2.imwrite(str(path), np.zeros((80, 120, 3), dtype=np.uint8))
            result = analyze_indicator_panes(path, "D1", None)
        self.assertEqual(result["status"], "PANE_ROIS_REQUIRED")
        self.assertEqual(result["panes"], {})


if __name__ == "__main__":
    unittest.main()
