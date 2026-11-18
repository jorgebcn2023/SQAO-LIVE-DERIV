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


    def test_auto_detects_labelled_indicator_pane(self):
        image = np.zeros((180, 420, 3), dtype=np.uint8)
        cv2.putText(image, "RSI (14)", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (255, 255, 255), 2, cv2.LINE_AA)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labelled.png"
            cv2.imwrite(str(path), image)
            from ENGINE.chart_indicator_vision import auto_detect_indicator_panes
            result = auto_detect_indicator_panes(path)
        self.assertIn(result["status"], ("LABEL_GUIDED", "OCR_UNAVAILABLE", "OCR_ENGINE_UNAVAILABLE"))
        if result["status"] == "LABEL_GUIDED":
            self.assertIn("RSI", result["pane_rois"])
            self.assertEqual(len(result["pane_rois"]["RSI"]), 4)

    def test_missing_rois_does_not_guess_indicators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.png"
            cv2.imwrite(str(path), np.zeros((80, 120, 3), dtype=np.uint8))
            result = analyze_indicator_panes(path, "D1", None)
        self.assertEqual(result["status"], "PANE_ROIS_REQUIRED")
        self.assertEqual(result["panes"], {})


    def test_low_confidence_axis_never_emits_numeric_zone(self):
        traces = [{"hue_center_hsv": 80, "coverage": 0.8,
                   "legend_identity": {"line_id": "RSI"},
                   "evolution": {"status": "TRACE_OBSERVED", "direction": "RISING"},
                   "points": [{"x_norm": 1.0, "y_norm": 0.1,
                               "axis_value_estimate": 74.2}]}]
        result = _semantic_observations("RSI", traces, {"status": "LOW_CONFIDENCE"})
        self.assertNotIn("latest_zone_visual_estimate", result)
        self.assertEqual(result["scale_status"], "LOW_CONFIDENCE")

    def test_low_confidence_axis_never_emits_ema_stack(self):
        traces = []
        for name, value in (("EMA_9", 105.0), ("EMA_20", 103.0), ("EMA_50", 100.0)):
            traces.append({"hue_center_hsv": 30, "coverage": 0.8,
                           "legend_identity": {"line_id": name},
                           "evolution": {"status": "TRACE_OBSERVED", "direction": "RISING"},
                           "points": [{"x_norm": 1.0, "y_norm": 0.2,
                                       "axis_value_estimate": value}]})
        result = _semantic_observations("EMA", traces, {"status": "LOW_CONFIDENCE"})
        self.assertEqual(result["ema_stack_order"], "NOT_ASSESSED")


if __name__ == "__main__":
    unittest.main()
