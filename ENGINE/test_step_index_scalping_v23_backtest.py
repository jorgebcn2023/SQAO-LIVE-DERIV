import unittest
from ENGINE.step_index_scalping_v23_backtest import stats, wilson, r_multiple, replay, _monetary, statistical_gate, MAX_HOLD_M1_BARS

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
    def test_small_oos_sample_is_no_trade(self):
        gate=statistical_gate({"n":5,"win_rate":.4,"wilson95":[.1176,.7693],"expectancy_r":0.0,"profit_factor":1.0})
        self.assertEqual(gate["decision"],"NO_TRADE")
        self.assertFalse(gate["eligible"])
    def test_gate_requires_lower_wilson_bound(self):
        gate=statistical_gate({"n":200,"win_rate":.75,"wilson95":[.69,.80],"expectancy_r":.2,"profit_factor":1.5})
        self.assertFalse(gate["eligible"])
    def test_gate_eligible_only_with_all_criteria(self):
        gate=statistical_gate({"n":200,"win_rate":.80,"wilson95":[.74,.85],"expectancy_r":.2,"profit_factor":1.5})
        self.assertEqual(gate["decision"],"ELIGIBLE")
    def test_max_holding_bars_is_20(self):
        self.assertEqual(MAX_HOLD_M1_BARS,20)

if __name__=="__main__": unittest.main()
