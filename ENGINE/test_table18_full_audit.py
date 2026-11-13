"""Tests for complete numeric Table 18 output."""
from ENGINE.table18_full_audit import build_table18


def sample_report():
    snap = {"candles": 250, "last_closed_epoch": 1700000000, "last_close": 7306.2,
            "ema10": 7306.1, "ema20": 7307.0, "rsi14": 44.2, "atr14": 1.3,
            "macd_line": -0.4, "macd_signal": -0.2, "macd_histogram": -0.2,
            "bollinger20_lower": 7300.0, "bollinger20_middle": 7306.0,
            "bollinger20_upper": 7312.0, "stochastic9_k": 31.0,
            "stochastic9_d": 35.0, "direction": "SHORT"}
    return {"generated_at_utc": "2026-11-13T20:00:00Z", "symbol": {"symbol": "stpRNG"},
            "source": "Deriv closed OHLC", "indicators": {tf: snap for tf in ("D1","H4","H1","M15","M5","M1")},
            "backtest": {"rule": "test", "parameters": {"round_trip_cost_price": 0.2},
                         "trades": [
                             {"sample":"out_of_sample","direction":"SHORT","signal_epoch":1700000000,
                              "entry_epoch":1700000300,"entry":7306.0,"stop":7307.0,"target":7304.5,
                              "exit":7304.5,"gross_r":1.5,"cost_r":0.2,"net_r":1.3,
                              "exit_reason":"TARGET","holding_bars":3}
                         ]}}


def test_table18_has_numeric_levels_and_complete_mtf_context():
    table = build_table18(sample_report())
    assert table["row_count"] == 1
    row = table["rows"][0]
    assert row["entry"] == 7306.0
    assert row["stop_loss"] == 7307.0
    assert row["take_profit"] == 7304.5
    assert row["risk_reward"] == 1.5
    assert row["latest_h4_rsi14"] == 44.2
    assert row["latest_m1_macd_histogram"] == -0.2
    assert row["indicator_provenance"] == "LATEST_REPORT_CONTEXT_NOT_HISTORICAL_AT_ENTRY"
    assert table["summary"]["out_of_sample"]["trades"] == 1


def test_missing_indicators_remain_null_and_invalid_geometry_rejected():
    report = sample_report()
    report["indicators"]["H4"] = {}
    table = build_table18(report)
    assert table["rows"][0]["latest_h4_rsi14"] is None
    report["backtest"]["trades"][0]["stop"] = 7305.0
    try:
        build_table18(report)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid SHORT geometry must be rejected")


if __name__ == "__main__":
    test_table18_has_numeric_levels_and_complete_mtf_context()
    test_missing_indicators_remain_null_and_invalid_geometry_rejected()
    print("SQAO Table 18 complete audit tests: OK")
