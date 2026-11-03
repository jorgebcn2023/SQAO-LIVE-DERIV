import unittest
from ENGINE.step_index_scalping_v23_backtest import stats, wilson
class BacktestV23Tests(unittest.TestCase):
 def test_wilson_bounds(self):
  lo,hi=wilson(7,10); self.assertLess(lo,.7); self.assertGreater(hi,.7)
 def test_stats(self):
  x=stats([1,-1,1]); self.assertEqual(x["n"],3); self.assertAlmostEqual(x["expectancy_r"],1/3)
if __name__=="__main__":unittest.main()
