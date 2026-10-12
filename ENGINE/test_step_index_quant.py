"""Regression tests for Step Index quant research functions."""
import math
from ENGINE.step_index_quant import (
    acceptance_gate, analyze_backtest, equity_stats, log_compounding, log_returns, wilson_interval,
)
from ENGINE.step_index_research import backtest_m5, closed_candles, log_distribution, signal_m5


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


def test_closed_candles_drops_forming_bar():
    rows = [
        {"epoch": 100, "open": 10, "high": 11, "low": 9, "close": 10},
        {"epoch": 160, "open": 10, "high": 12, "low": 9, "close": 11},
    ]
    closed = closed_candles(rows, "M1", now_epoch=200)
    assert [x["epoch"] for x in closed] == [100, 160]


def test_log_distribution_is_finite():
    stats = log_distribution([100, 101, 99, 102])
    assert stats["n"] == 3
    assert math.isfinite(stats["mean"])
    assert math.isfinite(stats["sd"])


def test_signal_uses_prior_bars_only():
    rows = []
    for i in range(25):
        p = 100 + i * 0.1
        rows.append({"epoch": i * 300, "open": p, "high": p + 0.05, "low": p - 0.05, "close": p})
    rows.append({"epoch": 7500, "open": 103, "high": 104, "low": 102.9, "close": 103.5})
    assert signal_m5(rows) == "LONG"


def test_backtest_rejects_unvalidated_costs():
    def frame(n, seconds, start):
        result = []
        for i in range(n):
            p = start + 0.05 * math.sin(i / 4) + i * 0.002
            result.append({"epoch": i * seconds, "open": p, "high": p + 0.1,
                           "low": p - 0.1, "close": p})
        return result
    m5 = frame(300, 300, 100)
    m15 = frame(200, 900, 100)
    h1 = frame(100, 3600, 100)
    result = backtest_m5(m5, m15, h1, round_trip_cost_price=None)
    assert result["out_of_sample"]["gate"]["decision"] == "NO_TRADE"
    assert result["out_of_sample"]["gate"]["checks"]["round_trip_costs_provided"] is False


if __name__ == "__main__":
    test_log_returns()
    test_wilson_small_sample()
    test_equity_stats_negative_sample()
    test_compounding_guards_nonpositive_factor()
    test_gate_fails_small_sample_and_missing_costs()
    test_analyze_backtest_does_not_claim_success()
    test_closed_candles_drops_forming_bar()
    test_log_distribution_is_finite()
    test_signal_uses_prior_bars_only()
    test_backtest_rejects_unvalidated_costs()
    print("Step Index quant tests: OK")
