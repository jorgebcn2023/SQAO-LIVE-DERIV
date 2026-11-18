"""Regression tests for the SQAO V3.2 visual evidence intake."""
from __future__ import annotations

import unittest

from ENGINE.chart_visual_intelligence_v32 import audit_image, audit_mtf


class VisualIntelligenceV32Tests(unittest.TestCase):
    def test_missing_file_fails_closed(self):
        result = audit_image("this-file-does-not-exist.png", "M1")
        self.assertEqual(result["status"], "FILE_NOT_FOUND")
        self.assertEqual(result["source_file"], "this-file-does-not-exist.png")

    def test_mtf_missing_timestamps_is_blocked(self):
        frames = {tf: {"capture_timestamp": None} for tf in ("D1", "H4", "H1", "M15", "M5", "M1")}
        result = audit_mtf(frames)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["timestamp_alignment"], "UNKNOWN")
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertFalse(result["execution_eligible"])

    def test_mtf_requires_all_six_frames(self):
        frames = {"M1": {"capture_timestamp": "2026-11-18T00:00:00Z"}}
        result = audit_mtf(frames)
        self.assertEqual(result["missing_timeframes"], ["D1", "H4", "H1", "M15", "M5"])
        self.assertEqual(result["status"], "BLOCKED")

    def test_six_frames_with_same_explicit_timestamp_pass_metadata_gate(self):
        stamp = "2026-11-18T00:00:00Z"
        frames = {tf: {"capture_timestamp": stamp} for tf in ("D1", "H4", "H1", "M15", "M5", "M1")}
        result = audit_mtf(frames)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["timestamp_alignment"], "PASS")
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertFalse(result["execution_eligible"])


if __name__ == "__main__":
    unittest.main()
