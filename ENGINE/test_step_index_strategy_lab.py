"""Regression tests for the fixed-candidate strategy lab."""
import math
from ENGINE.step_index_strategy_lab import evaluate_strategy, build_report


def frame(n, seconds, start=100.0):
    rows = []
    for i in range(n):
        p = start + i * 0.03 + 0.25 * math.sin(i / 5)
        rows.append({"epoch": i * seconds, "open": p, "high": p + 0.12,
                     "low": p - 0.12, "close": p})
    return rows


def test_strategy_lab_returns_oos_and_cost_gate():
    result = evaluate_strategy("breakout20_mtf", frame(400, 300), frame(250, 900),
                               frame(180, 3600), round_trip_cost_price=None)
    assert result["oos_n"] >= 0
    assert result["gate"]["decision"] == "NO_TRADE"
    assert result["gate"]["checks"]["round_trip_costs_provided"] is False


def test_candidate_report_is_conservative():
    report = build_report({"M5": frame(400, 300), "M15": frame(250, 900),
                           "H1": frame(180, 3600)}, {"symbol": "TEST", "display_name": "Test"})
    assert report["decision"] in {"NO_TRADE", "CANDIDATE_FOR_REVIEW"}
    assert len(report["strategies"]) == 3
    mechanics = report["market_mechanics"]
    assert mechanics["price_step_per_tick"] == 0.1
    assert mechanics["direction_probability_up"] == 0.5
    assert mechanics["direction_probability_down"] == 0.5
    assert mechanics["published_drift"] == 0.0
    assert mechanics["use_in_ohlc_calculations"] is False
    assert mechanics["mt5_tick_value_verified"] is False
    assert mechanics["monetary_conversion_enabled"] is False
    assert all(x["strategy"] in {"breakout20_mtf", "ema_pullback_mtf", "rsi_reversal"}
               for x in report["strategies"])


def test_report_always_surfaces_best_observed_and_conditional_execution_sheet():
    report = build_report({"M5": frame(400, 300), "M15": frame(250, 900),
                           "H1": frame(180, 3600)}, {"symbol": "TEST", "display_name": "Test"})
    assert report["best_observed_candidate"] in {x["strategy"] for x in report["strategies"]}
    assert report["best_observed_candidate_metrics"] is not None
    sheet = report["execution_sheet"]
    assert sheet["status"] == "CONDITIONAL_ONLY_NO_LIVE_ENTRY_PRICE"
    assert sheet["volume_scenarios_lots"] == [0.10, 0.20]
    assert sheet["live_entry_sl_tp"] is None
    assert "70%" in " ".join(report["limitations"]) or report["decision"] == "NO_TRADE"
