"""API contract tests for the read-only SQAO MTF endpoints."""
import time
import unittest

from API.app import GRANULARITY, TIMEFRAMES, _closed_candles, app


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
        self.assertEqual(app.version, "2.5.0")
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


if __name__ == "__main__":
    unittest.main()
