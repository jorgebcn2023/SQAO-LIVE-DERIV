"""API contract tests for the read-only SQAO MTF endpoints."""
import time
import unittest

from API.app import GRANULARITY, TIMEFRAMES, _build_integrity_gate, _closed_candles, app


class IntegrityGateTests(unittest.TestCase):
    def test_candidate_requires_all_integrity_conditions(self):
        setup = {"confirmed": True, "state": "TRIGGER_CONFIRMED"}
        passed = _build_integrity_gate({"status": "PASS"}, True, setup)
        self.assertEqual(passed["status"], "PASS")
        self.assertTrue(passed["candidate_review_allowed"])

    def test_mtf_block_forces_integrity_block(self):
        result = _build_integrity_gate({"status": "BLOCKED", "blockers": ["M1:STALE"]}, True,
                                       {"confirmed": True})
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["candidate_review_allowed"])
        self.assertIn("M1:STALE", result["blockers"])

    def test_incomplete_sample_and_gap_are_reported(self):
        result = _build_integrity_gate({"status": "PASS"}, False,
                                       {"confirmed": False, "state": "DATA_GAP_BLOCK"})
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("INSUFFICIENT_ALIGNED_CLOSED_CANDLES", result["blockers"])
        self.assertIn("NON_CONTIGUOUS_SIGNAL_WINDOW", result["blockers"])


class ClosedCandleTests(unittest.TestCase):
    def test_h4_is_part_of_api_timeframes(self):
        self.assertIn("H4", TIMEFRAMES)
        self.assertEqual(GRANULARITY["H4"], 14400)

    def test_only_valid_closed_unique_candles_are_returned(self):
        now = int(time.time())
        closed_epoch = now - 3600
        candles = [
            {"epoch": closed_epoch, "open": 10, "high": 12, "low": 9, "close": 11},
            {"epoch": closed_epoch, "open": 10, "high": 13, "low": 9, "close": 12},
            {"epoch": now, "open": 12, "high": 14, "low": 11, "close": 13},
            {"epoch": now - 1800, "open": 10, "high": 8, "low": 9, "close": 11},
            {"epoch": now - 1200, "open": float("nan"), "high": 12, "low": 9, "close": 11},
        ]
        result = _closed_candles(candles, "M1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["epoch"], closed_epoch)
        self.assertEqual(result[0]["close"], 12.0)

    def test_api_is_versioned_and_read_only_routes_have_no_trade_methods(self):
        self.assertEqual(app.version, "2.6.0")
        methods = {
            method.lower()
            for route in app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn("get", methods)
        self.assertNotIn("post", methods)
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/health", paths)
        self.assertIn("/market/active-symbols", paths)
        self.assertIn("/market/ohlc", paths)
        self.assertIn("/analysis/snapshot", paths)
        self.assertFalse(any(getattr(route, "path", "") in {"/proposal", "/buy", "/sell"} for route in app.routes))


if __name__ == "__main__":
    unittest.main()
