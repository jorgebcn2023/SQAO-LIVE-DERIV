import unittest
from ENGINE.step_index_validation import ema, rsi, atr, wilson, summarize, trend_at, parse_step_symbols

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

    def test_trend_ignores_higher_timeframe_candle_not_yet_closed(self):
        rows=[{"epoch":i*900,"close":100+i,"high":101+i,"low":99+i} for i in range(30)]
        # At the open time of the final candle, only 29 bars are closed/known.
        self.assertIsNone(trend_at(rows, rows[-1]["epoch"], 900))
        # One full timeframe later, all 30 bars are eligible.
        self.assertEqual(trend_at(rows, rows[-1]["epoch"]+900, 900), "LONG")

    def test_symbol_parser_supports_current_deriv_schema(self):
        payload={"active_symbols":[
            {"underlying_symbol_name":"Step Index","underlying_symbol":"stpRNG"},
            {"underlying_symbol_name":"Volatility 100 Index","underlying_symbol":"R_100"},
            {"display_name":"Step Index 200","symbol":"stpRNG2"},
        ]}
        self.assertEqual(parse_step_symbols(payload),[
            {"symbol":"stpRNG","name":"Step Index"},
            {"symbol":"stpRNG2","name":"Step Index 200"},
        ])

    def test_symbol_parser_supports_legacy_deriv_schema(self):
        payload={"active_symbols":[{"display_name":"Step Index","symbol":"stpRNG"}]}
        self.assertEqual(parse_step_symbols(payload),[{"symbol":"stpRNG","name":"Step Index"}])

    def test_summary_reports_win_rate_and_drawdown(self):
        m=summarize([1.0,-1.0,1.0])
        self.assertEqual(m["trades"],3)
        self.assertAlmostEqual(m["win_rate"],2/3)
        self.assertAlmostEqual(m["max_drawdown_R"],1.0)

if __name__ == "__main__":
    unittest.main()
