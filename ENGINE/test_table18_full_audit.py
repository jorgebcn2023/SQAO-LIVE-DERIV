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
    assert row["signal_h4_rsi14"] is None
    assert row["signal_m1_macd_histogram"] is None
    assert row["indicator_provenance"] == "MISSING_HISTORICAL_AT_SIGNAL"
    assert table["indicator_provenance_counts"]["MISSING_HISTORICAL_AT_SIGNAL"] == 1
    assert table["summary"]["out_of_sample"]["trades"] == 1


def test_missing_indicators_remain_null_and_invalid_geometry_rejected():
    report = sample_report()
    report["indicators"]["H4"] = {}
    table = build_table18(report)
    assert table["rows"][0]["signal_h4_rsi14"] is None
    report["backtest"]["trades"][0]["stop"] = 7305.0
    try:
        build_table18(report)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid SHORT geometry must be rejected")


def test_historical_indicator_values_are_attached_to_signal_timestamp():
    report = sample_report()
    hist = {"candles_used": 180, "last_closed_epoch": 1700000000, "last_close": 7306.0,
            "ema9": 7305.8, "ema20": 7306.2, "ema50": 7308.0, "rsi14": 42.0,
            "atr14": 1.1, "macd_line": -0.3, "macd_signal": -0.1,
            "macd_histogram": -0.2, "bollinger20_lower": 7300.0,
            "bollinger20_middle": 7306.0, "bollinger20_upper": 7312.0,
            "bollinger20_width": 0.0016, "bollinger20_percent_b": 0.5,
            "adx14": 24.0, "plus_di14": 12.0, "minus_di14": 28.0,
            "stochastic14_k": 30.0, "stochastic3_k": 32.0, "stochastic3_d": 35.0,
            "ema_stack": "BEARISH",
            "group_votes": {"trend":"SHORT","momentum_macd":"SHORT",
                            "oscillator_rsi_stoch":"SHORT","directional_strength_adx_di":"SHORT"}}
    seconds = {"D1":86400, "H4":14400, "H1":3600, "M15":900, "M5":300, "M1":60}
    report["backtest"]["trades"][0]["indicator_snapshots_at_signal"] = {
        tf: {**hist, "last_closed_epoch": 1700000000 - seconds[tf]}
        for tf in ("D1","H4","H1","M15","M5","M1")}
    result = build_table18(report)
    row = result["rows"][0]
    assert row["indicator_provenance"] == "HISTORICAL_AT_SIGNAL"
    assert row["signal_h4_ema9"] == 7305.8
    assert row["signal_m15_adx14"] == 24.0
    assert row["signal_m1_minus_di14"] == 28.0
    assert row["signal_h1_macd_vote"] == "SHORT"
    assert row["signal_d1_candle_close_epoch"] <= row["signal_epoch"]
    assert result["indicator_provenance_counts"]["HISTORICAL_AT_SIGNAL"] == 1


def test_future_indicator_snapshot_is_rejected():
    report = sample_report()
    future = {"candles_used": 50, "last_closed_epoch": 1700000000,
              "ema9": 7305.8, "ema20": 7306.2}
    report["backtest"]["trades"][0]["indicator_snapshots_at_signal"] = {"M1": future}
    try:
        build_table18(report)
    except ValueError as exc:
        assert "look-ahead contamination" in str(exc)
    else:
        raise AssertionError("Future M1 indicator candle must be rejected")


def test_partial_historical_snapshots_never_fall_back_to_latest_context():
    report = sample_report()
    report["backtest"]["trades"][0]["indicator_snapshots_at_signal"] = {
        "M1": {"last_closed_epoch": 1699999940, "rsi14": 48.0}
    }
    row = build_table18(report)["rows"][0]
    assert row["indicator_provenance"] == "PARTIAL_HISTORICAL_AT_SIGNAL"
    assert row["signal_m1_rsi14"] == 48.0
    assert row["signal_h4_rsi14"] is None


if __name__ == "__main__":
    test_table18_has_numeric_levels_and_complete_mtf_context()
    test_missing_indicators_remain_null_and_invalid_geometry_rejected()
    test_historical_indicator_values_are_attached_to_signal_timestamp()
    test_future_indicator_snapshot_is_rejected()
    test_partial_historical_snapshots_never_fall_back_to_latest_context()
    print("SQAO Table 18 complete audit tests: OK")
