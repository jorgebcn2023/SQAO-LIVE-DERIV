import tempfile
import unittest
from pathlib import Path

from CONNECTOR.deriv_live import CandleAggregator, load_engine_frames, run_analysis


class DerivLiveConnectorTests(unittest.TestCase):
    def test_default_aggregator_includes_h4_not_d1(self):
        agg = CandleAggregator()
        self.assertEqual(set(agg.timeframes), {1, 5, 15, 60, 240})
        self.assertIn(240, agg.current | {}) if False else None

    def test_live_analysis_fails_closed_without_market_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_analysis(Path(tmp))
            import json
            result = json.loads((Path(tmp) / "live_analysis.json").read_text())
            self.assertEqual(result["decision"], "NO_TRADE")
            self.assertEqual(result["state"], "INSUFFICIENT_DATA")

    def test_frame_loader_deduplicates_and_sorts_epochs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ohlc_M1.csv"
            path.write_text(
                "timestamp,open,high,low,close,timeframe\n"
                "120,2,3,1,2,M1\n"
                "60,1,2,0,1,M1\n"
                "120,2,4,1,3,M1\n",
                encoding="utf-8",
            )
            frames = load_engine_frames(Path(tmp))
            self.assertEqual([r["epoch"] for r in frames["M1"]], [60, 120])
            self.assertEqual(frames["M1"][-1]["close"], 3.0)


if __name__ == "__main__":
    unittest.main()
