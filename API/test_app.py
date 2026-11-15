"""API contract tests for the read-only SQAO MTF endpoints."""
import json
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from API.app import GRANULARITY, TIMEFRAMES, _build_integrity_gate, _check_auth, _closed_candles, app
from CONNECTOR.deriv_live import Candle, CandleAggregator, receive_matching


class AuthenticationTests(unittest.TestCase):
    def test_missing_server_secret_fails_closed(self):
        with patch("API.app.API_KEY", ""):
            with self.assertRaises(HTTPException) as raised:
                _check_auth(None)
        self.assertEqual(raised.exception.status_code, 503)

    def test_missing_or_invalid_request_key_is_rejected(self):
        with patch("API.app.API_KEY", "test-only-secret"):
            for supplied in (None, "wrong-secret"):
                with self.subTest(supplied=supplied):
                    with self.assertRaises(HTTPException) as raised:
                        _check_auth(supplied)
                    self.assertEqual(raised.exception.status_code, 401)

    def test_matching_request_key_is_accepted(self):
        with patch("API.app.API_KEY", "test-only-secret"):
            self.assertIsNone(_check_auth("test-only-secret"))


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


class ConnectorRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_restored_forming_candle_is_continued_and_emitted_once(self):
        aggregator = CandleAggregator(timeframes=(1,))
        start = 1_800_000_000
        restored = Candle(start, 100.0, 103.0, 99.0, 102.0, "M1")
        aggregator.current[1] = restored

        emitted_same_bucket = aggregator.update(start + 30, 104.0)
        self.assertEqual(emitted_same_bucket, [])
        self.assertEqual(aggregator.current[1].open, 100.0)
        self.assertEqual(aggregator.current[1].high, 104.0)
        self.assertEqual(aggregator.current[1].low, 99.0)
        self.assertEqual(aggregator.current[1].close, 104.0)

        emitted_next_bucket = aggregator.update(start + 60, 105.0)
        self.assertEqual(len(emitted_next_bucket), 1)
        self.assertEqual(emitted_next_bucket[0].timestamp, start)
        self.assertEqual(emitted_next_bucket[0].close, 104.0)

    async def test_history_receiver_ignores_other_request_ids(self):
        class FakeWebSocket:
            def __init__(self):
                self.messages = [
                    json.dumps({"msg_type": "candles", "req_id": 200, "candles": []}),
                    json.dumps({"msg_type": "tick", "req_id": 1}),
                    json.dumps({"msg_type": "candles", "req_id": 1101, "candles": [{"epoch": 1}]}),
                ]

            async def recv(self):
                return self.messages.pop(0)

        result = await receive_matching(FakeWebSocket(), 1101)
        self.assertEqual(result["req_id"], 1101)
        self.assertEqual(result["candles"], [{"epoch": 1}])


if __name__ == "__main__":
    unittest.main()
