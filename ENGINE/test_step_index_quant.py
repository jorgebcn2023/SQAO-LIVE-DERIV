"""Regression tests for Step Index quant research functions."""
import math
from ENGINE.step_index_quant import (
    acceptance_gate, analyze_backtest, equity_stats, log_compounding, log_returns, wilson_interval,
)


def test_log_returns():
    vals = log_returns([100, 110, 99])
    assert len(vals) == 2
    assert abs(vals[0] - math.log(1.1)) < 1e-12
    assert abs(vals[1] - math.log(0.9)) < 1e-12


def test_wilson_small_sample():
    low, high = wilson_interval(3, 8)
    assert 0.13 < low < 0.14
    assert 0.69 < high < 0.70


def test_equity_stats_negative_sample():
    s = equity_stats([1, -1, -1, -1], cost_r=0.0)
    assert s["n"] == 4
    assert s["wins"] == 1 and s["losses"] == 3
    assert s["expectancy_r"] < 0
    assert s["profit_factor"] < 1


def test_compounding_guards_nonpositive_factor():
    assert log_compounding([-100], 0.02)["valid"] is False


def test_gate_fails_small_sample_and_missing_costs():
    s = equity_stats([1, 1, 1, -1], cost_r=0)
    gate = acceptance_gate(s, min_trades=100, costs_supplied=False)
    assert gate["decision"] == "NO_TRADE"
    assert gate["eligible"] is False


def test_analyze_backtest_does_not_claim_success():
    report = analyze_backtest([1, -1, -1, 1], [100, 101, 99, 100, 102], cost_r=None)
    assert report["acceptance"]["decision"] == "NO_TRADE"
    assert report["log_return_stats"]["n"] == 4


if __name__ == "__main__":
    test_log_returns()
    test_wilson_small_sample()
    test_equity_stats_negative_sample()
    test_compounding_guards_nonpositive_factor()
    test_gate_fails_small_sample_and_missing_costs()
    test_analyze_backtest_does_not_claim_success()
    print("Step Index quant tests: OK")
