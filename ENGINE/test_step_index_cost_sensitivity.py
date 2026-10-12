"""Data-free tests for explicit Step Index cost sensitivity stress scenarios."""
import unittest

from ENGINE.step_index_cost_sensitivity import build_sensitivity


class CostSensitivityTests(unittest.TestCase):
    def test_cost_scenarios_reduce_expectancy_and_never_claim_verified_costs(self):
        lab = {
            "generated_at_utc": "test",
            "symbol": {"symbol": "stpRNG", "display_name": "Step Index 100"},
            "strategies": [{
                "strategy": "test_strategy",
                "trades": [
                    {"sample": "out_of_sample", "gross_r": 1.0},
                    {"sample": "out_of_sample", "gross_r": -1.0},
                    {"sample": "train", "gross_r": 1.0},
                ],
            }],
        }
        result = build_sensitivity(lab, costs_r=(0.0, 0.1, 0.2))
        self.assertFalse(result["costs_are_broker_verified"])
        self.assertEqual(result["decision"], "NO_TRADE_COSTS_UNVERIFIED")
        scenarios = result["strategies"][0]["scenarios"]
        self.assertEqual([s["hypothetical_round_trip_cost_R"] for s in scenarios], [0.0, 0.1, 0.2])
        expectancies = [s["expectancy_R"] for s in scenarios]
        self.assertAlmostEqual(expectancies[0], 0.0)
        self.assertAlmostEqual(expectancies[1], -0.1)
        self.assertAlmostEqual(expectancies[2], -0.2)
        self.assertEqual(result["strategies"][0]["n_oos"], 2)


if __name__ == "__main__":
    unittest.main()
