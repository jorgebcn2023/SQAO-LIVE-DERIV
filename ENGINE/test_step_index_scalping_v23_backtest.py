import unittest, json, tempfile
from pathlib import Path
from ENGINE.step_index_scalping_v23_backtest import stats, wilson, r_multiple, replay, _monetary, statistical_gate, MAX_HOLD_M1_BARS, next_m1_entry, build_table17

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
        gate=statistical_gate({"n":200,"win_rate":.75,"wilson95":[.69,.80],"expectancy_r":.2,"profit_factor":1.5}, {"n":200,"win_rate":.75,"wilson95":[.69,.80],"expectancy_r":.2,"profit_factor":1.5}, costs_verified=True)
        self.assertFalse(gate["eligible"])
    def test_gate_eligible_only_with_all_criteria(self):
        good={"n":200,"win_rate":.80,"wilson95":[.74,.85],"expectancy_r":.2,"profit_factor":1.5}
        gate=statistical_gate(good,good,costs_verified=True)
        self.assertEqual(gate["decision"],"ELIGIBLE")
    def test_gross_only_never_passes_without_verified_costs(self):
        good={"n":250,"win_rate":.80,"wilson95":[.74,.85],"expectancy_r":.2,"profit_factor":1.5}
        self.assertFalse(statistical_gate(good,good,costs_verified=False)["eligible"])
        self.assertFalse(statistical_gate(good,None,costs_verified=True)["eligible"])

    def test_table17_no_trade_never_fabricates_levels(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"live.json"
            p.write_text(json.dumps({"setup":{"confirmed":False,"state":"BIAS_ONLY_WAIT_PULLBACK"}}))
            row=build_table17(str(p),{"n":100},None,"BLOCKED",{"decision":"NO_TRADE"})
            self.assertEqual(row["decision"],"NO_TRADE")
            self.assertIsNone(row["entry_price"])
            self.assertIsNone(row["stop_loss"])
            self.assertEqual(row["position_size_scenarios"],{})

    def test_table17_operational_levels_only_with_exact_confirmed_open(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"live.json"
            p.write_text(json.dumps({
                "symbol":{"symbol":"stpRNG"},
                "next_m1_open":{"epoch":120},
                "setup":{"confirmed":True,"execution_price_confirmed":True,
                    "status":"CONDITIONAL_SETUP_REQUIRES_LIVE_CONFIRMATION","direction":"LONG",
                    "decision_epoch":120,"atr14_m1":0.5,
                    "execution_levels":{"entry":100,"stop_loss":99.4,"take_profit":100.9,
                        "risk_price_units":0.6,"reward_price_units":0.9,"risk_reward":"1:1.5"}}
            }))
            row=build_table17(str(p),{"n":100},{"n":200},"VERIFIED",{"eligible":True,"decision":"ELIGIBLE"})
            self.assertEqual(row["decision"],"CONDITIONAL_SETUP_REQUIRES_LIVE_CONFIRMATION")
            self.assertEqual(row["entry_price"],100)
            self.assertAlmostEqual(row["stop_loss"],99.4)
            self.assertAlmostEqual(row["take_profit"],100.9)
            self.assertIn("0.10",row["position_size_scenarios"])
            self.assertFalse(row["commission_verified"])
            self.assertFalse(row["slippage_verified"])

    def test_table17_rejects_wrong_next_m1_epoch(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"live.json"
            p.write_text(json.dumps({
                "symbol":{"symbol":"stpRNG"},"next_m1_open":{"epoch":180},
                "setup":{"confirmed":True,"execution_price_confirmed":True,
                    "status":"CONDITIONAL_SETUP_REQUIRES_LIVE_CONFIRMATION","direction":"LONG",
                    "decision_epoch":120,
                    "execution_levels":{"entry":100,"stop_loss":99.4,"take_profit":100.9,
                        "risk_price_units":0.6,"reward_price_units":0.9,"risk_reward":"1:1.5"}}
            }))
            row=build_table17(str(p),{"n":200},{"n":200},"VERIFIED",{"eligible":True})
            self.assertEqual(row["decision"],"NO_TRADE")
            self.assertIsNone(row["entry_price"])
            self.assertEqual(row["no_trade_reason"],"LIVE_TRIGGER_LEVELS_OR_EXACT_NEXT_M1_EPOCH_INVALID")

    def test_table17_rejects_inconsistent_risk_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"live.json"
            p.write_text(json.dumps({
                "symbol":{"symbol":"stpRNG"},"next_m1_open":{"epoch":120},
                "setup":{"confirmed":True,"execution_price_confirmed":True,
                    "status":"CONDITIONAL_SETUP_REQUIRES_LIVE_CONFIRMATION","direction":"LONG",
                    "decision_epoch":120,
                    "execution_levels":{"entry":100,"stop_loss":99.0,"take_profit":100.9,
                        "risk_price_units":0.6,"reward_price_units":0.9,"risk_reward":"1:1.5"}}
            }))
            row=build_table17(str(p),{"n":200},{"n":200},"VERIFIED",{"eligible":True})
            self.assertEqual(row["decision"],"NO_TRADE")
            self.assertIsNone(row["stop_loss"])

    def test_table17_never_bypasses_missing_cost_eligibility(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"live.json"
            p.write_text(json.dumps({
                "symbol":{"symbol":"stpRNG"},"next_m1_open":{"epoch":120},
                "setup":{"confirmed":True,"execution_price_confirmed":True,
                    "status":"CONDITIONAL_SETUP_REQUIRES_LIVE_CONFIRMATION","direction":"LONG",
                    "decision_epoch":120,
                    "execution_levels":{"entry":100,"stop_loss":99.4,"take_profit":100.9,
                        "risk_price_units":0.6,"reward_price_units":0.9,"risk_reward":"1:1.5"}}
            }))
            row=build_table17(str(p),{"n":200},None,"BLOCKED",{"eligible":False,"decision":"NO_TRADE"})
            self.assertEqual(row["decision"],"NO_TRADE")
            self.assertIsNone(row["entry_price"])
            self.assertEqual(row["no_trade_reason"],"STATISTICAL_ELIGIBILITY_BLOCKED")

    def test_max_holding_bars_is_20(self):
        self.assertEqual(MAX_HOLD_M1_BARS,20)

    def test_backtest_requires_exact_next_m1_epoch(self):
        rows = [{"epoch": 60, "open": 10.0}, {"epoch": 120, "open": 11.0}]
        self.assertEqual(next_m1_entry(rows, 0, 120), 11.0)
        self.assertIsNone(next_m1_entry(rows, 0, 180))
        self.assertIsNone(next_m1_entry(rows, 1, 180))

if __name__=="__main__": unittest.main()
