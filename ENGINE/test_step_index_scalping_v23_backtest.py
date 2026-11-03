import unittest
from ENGINE.step_index_scalping_v23_backtest import stats, wilson, r_multiple


class BacktestV23Tests(unittest.TestCase):
    def test_wilson_bounds(self):
        lo, hi = wilson(7, 10)
        self.assertLess(lo, 0.7)
        self.assertGreater(hi, 0.7)

    def test_stats(self):
        result = stats([1, -1, 1])
        self.assertEqual(result["n"], 3)
        self.assertAlmostEqual(result["expectancy_r"], 1 / 3)

    def test_r_multiple_does_not_clip_gap_or_time_exit(self):
        self.assertAlmostEqual(r_multiple(100, 103, 2, "LONG"), 1.5)
        self.assertAlmostEqual(r_multiple(100, 97, 2, "LONG"), -1.5)

    def test_r_multiple_rejects_invalid_risk(self):
        with self.assertRaises(ValueError):
            r_multiple(100, 101, 0, "LONG")


if __name__ == "__main__":
    unittest.main()
