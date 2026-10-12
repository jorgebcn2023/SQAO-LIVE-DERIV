"""Regression tests for Step Index quant research functions."""
import math
from ENGINE.step_index_quant import (
    acceptance_gate, analyze_backtest, equity_stats, log_compounding, log_returns, wilson_interval,
)
from ENGINE.step_index_research import (
    aggregate_weekly_from_daily, backtest_m5, closed_candles, log_distribution, signal_m5,
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


def test_closed_candles_drops_forming_bar():
    rows = [
        {"epoch": 100, "open": 10, "high": 11, "low": 9, "close": 10},
        {"epoch": 160, "open": 10, "high": 12, "low": 9, "close": 11},
    ]
    closed = closed_candles(rows, "M1", now_epoch=230)
    assert [x["epoch"] for x in closed] == [100, 160]


def test_log_distribution_is_finite():
    stats = log_distribution([100, 101, 99, 102])
    assert stats["n"] == 3
    assert math.isfinite(stats["mean"])
    assert math.isfinite(stats["sd"])


def test_signal_uses_prior_bars_only():
    rows = []
    for i in range(40):
        p = 100 + i * 0.1
        rows.append({"epoch": i * 300, "open": p, "high": p + 0.05, "low": p - 0.05, "close": p})
    rows.append({"epoch": 12000, "open": 104, "high": 105, "low": 103.9, "close": 104.5})
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



def test_executive_pdf_generation():
    import tempfile
    from pathlib import Path
    from ENGINE.step_index_research import indicator_snapshot, log_distribution, write_pdf
    rows = []
    for i in range(120):
        close = 7350.0 + i * 0.15 + 0.3 * math.sin(i / 4)
        rows.append({"epoch": 1_700_000_000 + i * 300, "open": close - 0.05,
                     "high": close + 0.2, "low": close - 0.2, "close": close})
    stats = equity_stats([1.5, -1.0, 1.5, -1.0, 0.3])
    report = {
        "generated_at_utc": "2026-10-12T00:00:00+00:00",
        "decision": "NO_TRADE",
        "symbol": {"symbol": "TEST", "display_name": "Synthetic Step Index"},
        "current_setup": {"confirmed": False, "state": "NO_CURRENT_TRIGGER"},
        "indicators": {"M5": indicator_snapshot(rows)},
        "log_distribution_m5": log_distribution([x["close"] for x in rows]),
        "backtest": {
            "rule": "Test rule",
            "parameters": {"round_trip_cost_price": None},
            "out_of_sample": {"n_trades": stats["n"], "stats_gross": stats,
                              "stats_net": stats, "gate": acceptance_gate(stats, costs_supplied=False),
                              "subperiods": []},
            "trades": [],
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "step-index-test.pdf"
        write_pdf(report, path)
        assert path.is_file()
        assert path.stat().st_size > 3000



def test_aggregate_weekly_from_daily_uses_only_completed_weeks():
    # Monday 2024-01-01 UTC; full week closes Monday 2024-01-08 00:00 UTC.
    start = 1704067200
    rows = []
    for i in range(7):
        p = 100 + i
        rows.append({"epoch": start + i * 86400, "open": p, "high": p + 2,
                     "low": p - 1, "close": p + 1})
    rows.append({"epoch": start + 7 * 86400, "open": 108, "high": 110, "low": 107, "close": 109})
    weekly = aggregate_weekly_from_daily(rows, now_epoch=start + 8 * 86400)
    assert len(weekly) == 1
    assert weekly[0]["epoch"] == start
    assert weekly[0]["open"] == 100
    assert weekly[0]["high"] == 108
    assert weekly[0]["low"] == 99
    assert weekly[0]["close"] == 107


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
    test_executive_pdf_generation()
    test_aggregate_weekly_from_daily_uses_only_completed_weeks()
    print("Step Index quant tests: OK")
