import unittest
from ENGINE.step_index_validation import ema, rsi, atr, wilson, summarize, trend_at

class ValidationMetricsTests(unittest.TestCase):
    def test_ema(self):
        self.assertAlmostEqual(ema([1,2,3,4], 2), 3.5)

    def test_rsi_monotonic_up(self):
        self.assertEqual(rsi(list(range(20))), 100.0)

    def test_atr_constant_range(self):
        rows=[{"high":11,"low":9,"close":10} for _ in range(20)]
        self.assertAlmostEqual(atr(rows,14),2.0)

    def test_wilson_interval_is_bounded(self):
        low,high=wilson(70,100)
        self.assertLessEqual(low,0.70)
        self.assertGreaterEqual(high,0.70)

    def test_trend_ignores_higher_timeframe_candle_not_yet_closed(self):\n        rows=[{"epoch":i*900,"close":100+i,"high":101+i,"low":99+i} for i in range(30)]\n        # At the open time of the final candle, only 29 bars are closed/known.\n        self.assertIsNone(trend_at(rows, rows[-1]["epoch"], 900))\n        # One full timeframe later, all 30 bars are eligible.\n        self.assertEqual(trend_at(rows, rows[-1]["epoch"]+900, 900), "LONG")\n\n    def test_summary_reports_win_rate_and_drawdown(self):
        m=summarize([1.0,-1.0,1.0])
        self.assertEqual(m["trades"],3)
        self.assertAlmostEqual(m["win_rate"],2/3)
        self.assertAlmostEqual(m["max_drawdown_R"],1.0)

if __name__ == "__main__":
    unittest.main()
