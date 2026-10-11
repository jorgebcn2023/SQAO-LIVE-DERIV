import unittest
from ENGINE.step_index_validation import ema, rsi, atr, wilson, summarize

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

    def test_summary_reports_win_rate_and_drawdown(self):
        m=summarize([1.0,-1.0,1.0])
        self.assertEqual(m["trades"],3)
        self.assertAlmostEqual(m["win_rate"],2/3)
        self.assertAlmostEqual(m["max_drawdown_R"],1.0)

if __name__ == "__main__":
    unittest.main()
