import unittest
from ENGINE.step_index_scalping_v23_backtest import stats, wilson, r_multiple, replay, _monetary

class BacktestV23Tests(unittest.TestCase):
    def test_wilson_bounds(self):
        lo,hi=wilson(7,10); self.assertLess(lo,.7); self.assertGreater(hi,.7)
    def test_stats(self):
        r=stats([1,-1,1]); self.assertEqual(r["n"],3); self.assertAlmostEqual(r["expectancy_r"],1/3)
    def test_r_multiple(self):
        self.assertAlmostEqual(r_multiple(100,103,2,"LONG"),1.5)
        self.assertAlmostEqual(r_multiple(100,97,2,"LONG"),-1.5)
    def test_invalid_risk(self):
        with self.assertRaises(ValueError): r_multiple(100,101,0,"LONG")
    def test_missing_cost_blocks_net(self):
        r=replay({"M1":[],"M5":[],"M15":[],"H1":[],"H4":[]})
        self.assertIsNone(r["net"]["oos"]); self.assertIsNone(r["cost_model"]["round_trip_cost_price_units"])
        self.assertEqual(r["target_r"],1.5)
    def test_provisional_monetary_conversion(self):
        self.assertAlmostEqual(_monetary(1,.1),1); self.assertAlmostEqual(_monetary(1,.2),2)

if __name__=="__main__": unittest.main()
