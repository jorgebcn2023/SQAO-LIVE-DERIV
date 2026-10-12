"""Unit tests for advanced Step Index diagnostics; deterministic and data-free."""
import math
import unittest

import numpy as np

from ENGINE.step_index_advanced import (
    bayesian_probability, calculate_hurst, condition_key, fft_cycle,
    fisher_transform, hurst_regime, monte_carlo_trade_bootstrap, squeeze_state,
)


class AdvancedStepIndexTests(unittest.TestCase):
    def test_hurst_short_series_is_unknown(self):
        self.assertIsNone(calculate_hurst([100.0 + i * 0.1 for i in range(30)]))

    def test_hurst_regime_thresholds(self):
        self.assertEqual(hurst_regime(0.61), "TREND")
        self.assertEqual(hurst_regime(0.39), "MEAN_REVERSION")
        self.assertEqual(hurst_regime(0.50), "RANDOM_OR_AMBIGUOUS")
        self.assertEqual(hurst_regime(None), "UNKNOWN")

    def test_fft_detects_synthetic_period(self):
        n = 256
        x = 100 + np.sin(2 * np.pi * np.arange(n) / 32)
        result = fft_cycle(x, min_period=8, max_period=80)
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["dominant_period_bars"], 32, delta=3)

    def test_fisher_is_finite_and_aligned(self):
        high = [100 + math.sin(i / 3) + 1 for i in range(60)]
        low = [100 + math.sin(i / 3) - 1 for i in range(60)]
        values = fisher_transform(high, low, length=9)
        self.assertEqual(len(values), 60)
        self.assertTrue(all(v is None or math.isfinite(v) for v in values))
        self.assertTrue(all(v is None for v in values[:8]))

    def test_bayesian_requires_matching_sample_size_and_wilson_lower_bound(self):
        features = {"hurst": 0.62, "fisher": 2.3, "squeeze_release": True, "direction": "SHORT"}
        samples = [{"features": features, "net_r": 1.0} for _ in range(35)]
        result = bayesian_probability(samples, features, min_samples=30)
        self.assertEqual(result["matches"], 35)
        self.assertTrue(result["sufficient_sample"])
        self.assertTrue(result["threshold_pass"])
        self.assertGreater(result["estimated_probability"], 0.9)

    def test_bayesian_does_not_match_different_state(self):
        a = {"hurst": 0.62, "fisher": 2.3, "squeeze_release": True, "direction": "SHORT"}
        b = {"hurst": 0.40, "fisher": -2.3, "squeeze_release": False, "direction": "LONG"}
        samples = [{"features": a, "net_r": 1.0} for _ in range(40)]
        result = bayesian_probability(samples, b)
        self.assertEqual(result["matches"], 0)
        self.assertFalse(result["threshold_pass"])

    def test_monte_carlo_bootstrap_reproducible(self):
        a = monte_carlo_trade_bootstrap([1.0, -1.0, 1.5, -1.0], paths=500, seed=42)
        b = monte_carlo_trade_bootstrap([1.0, -1.0, 1.5, -1.0], paths=500, seed=42)
        self.assertEqual(a, b)
        self.assertEqual(a["paths"], 500)
        self.assertLessEqual(a["win_rate_p05"], a["win_rate_p95"])

    def test_squeeze_handles_insufficient_history(self):
        rows = [{"high": 2, "low": 1, "close": 1.5} for _ in range(10)]
        result = squeeze_state(rows)
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
