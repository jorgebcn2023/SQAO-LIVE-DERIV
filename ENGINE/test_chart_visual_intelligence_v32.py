"""Regression tests for SQAO V3.2 visual evidence intake and fail-closed MTF gates."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ENGINE.chart_visual_intelligence_v32 import audit_image, audit_mtf, detect_panel_regions

STAMP = "2026-11-18T00:00:00Z"
FRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")


def frame_set(stamp=STAMP):
    return {tf: {"capture_timestamp": stamp} for tf in FRAMES}


class VisualIntelligenceV32Tests(unittest.TestCase):
    def test_missing_file_fails_closed(self):
        result = audit_image("this-file-does-not-exist.png", "M1")
        self.assertEqual(result["status"], "FILE_NOT_FOUND")
        self.assertEqual(result["source_file"], "this-file-does-not-exist.png")

    def test_corrupt_image_is_reported_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.png"
            path.write_bytes(b"not-an-image")
            result = audit_image(path, "M1")
        self.assertEqual(result["ocr_status"], "OCR_ENGINE_ERROR")
        self.assertIsNone(result["ohlc"])
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertFalse(result["execution_eligible"])

    def test_image_intake_preserves_hash_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.bin"
            path.write_bytes(b"evidence")
            result = audit_image(path, "1m", STAMP)
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(result["timeframe"], "M1")
        self.assertEqual(result["provenance"], "VISUAL_RAW")
        self.assertEqual(result["mode"], "READ_ONLY_RESEARCH_ONLY")
        self.assertIsNone(result["ohlc"])

    def test_mtf_missing_timestamps_is_blocked(self):
        frames = {tf: {"capture_timestamp": None} for tf in FRAMES}
        result = audit_mtf(frames)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["timestamp_alignment"], "BLOCKED")
        self.assertEqual(result["invalid_timestamps"], list(FRAMES))
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertFalse(result["execution_eligible"])

    def test_mtf_requires_all_six_frames(self):
        result = audit_mtf({"M1": {"capture_timestamp": STAMP}})
        self.assertEqual(result["missing_timeframes"], ["D1", "H4", "H1", "M15", "M5"])
        self.assertEqual(result["status"], "BLOCKED")

    def test_same_timestamp_passes_metadata_gate_only(self):
        result = audit_mtf(frame_set())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["timestamp_alignment"], "PASS")
        self.assertEqual(result["alignment_scope"], "CAPTURE_METADATA_ONLY_NOT_CANDLE_ALIGNMENT")
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertFalse(result["execution_eligible"])

    def test_timezone_equivalent_timestamps_align(self):
        frames = frame_set("2026-11-18T01:00:00+01:00")
        result = audit_mtf(frames)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["timestamp_skew_seconds"], 0.0)

    def test_small_capture_skew_within_tolerance_passes(self):
        frames = frame_set()
        frames["M1"] = {"capture_timestamp": "2026-11-18T00:00:45Z"}
        result = audit_mtf(frames, max_skew_seconds=60)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["timestamp_skew_seconds"], 45.0)

    def test_capture_skew_over_tolerance_is_blocked(self):
        frames = frame_set()
        frames["M1"] = {"capture_timestamp": "2026-11-18T00:02:00Z"}
        result = audit_mtf(frames, max_skew_seconds=60)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["timestamp_alignment"], "BLOCKED")
        self.assertEqual(result["timestamp_skew_seconds"], 120.0)

    def test_naive_and_malformed_timestamps_are_blocked(self):
        frames = frame_set()
        frames["M1"] = {"capture_timestamp": "2026-11-18 00:00:00"}
        result = audit_mtf(frames)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["invalid_timestamps"], ["M1"])


    def test_panel_geometry_detects_full_width_separator_without_classifying(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "panels.png"
            image = Image.new("RGB", (320, 200), "white")
            draw = ImageDraw.Draw(image)
            draw.line((0, 100, 319, 100), fill="black", width=2)
            image.save(path)
            result = detect_panel_regions(path)
        self.assertEqual(result["status"], "GEOMETRY_DETECTED")
        self.assertGreaterEqual(len(result["panels"]), 2)
        self.assertEqual(result["classification"], "UNCLASSIFIED")
        self.assertEqual(result["curve_attribution"], "NOT_PERFORMED")
        self.assertEqual(result["provenance"], "VISUAL_RAW")

    def test_panel_geometry_missing_file_fails_closed(self):
        result = detect_panel_regions("missing-panel-image.png")
        self.assertEqual(result["status"], "FILE_NOT_FOUND")
        self.assertEqual(result["panels"], [])

    def test_panel_geometry_rejects_invalid_threshold(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid.png"
            Image.new("RGB", (20, 20), "white").save(path)
            with self.assertRaises(ValueError):
                detect_panel_regions(path, row_coverage=1.5)

    def test_negative_skew_tolerance_rejected(self):
        with self.assertRaises(ValueError):
            audit_mtf(frame_set(), max_skew_seconds=-1)


if __name__ == "__main__":
    unittest.main()
