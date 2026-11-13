"""Tests for complete, non-double-counted MTF chart indicator audit."""
import math
from ENGINE.chart_indicator_audit import indicator_snapshot, build_mtf_audit


def frame(n, seconds, mode="up"):
    rows=[]
    for i in range(n):
        base=7300 + (i*0.08 if mode=="up" else -i*0.08) + 0.25*math.sin(i/3)
        rows.append({"epoch":1700000000+i*seconds,"open":base-0.03,
                     "high":base+0.12,"low":base-0.12,"close":base})
    return rows


def test_indicator_snapshot_reports_all_standard_indicators():
    snap=indicator_snapshot(frame(180,60))
    for key in ("ema9","ema20","ema50","rsi14","atr14","macd_line","macd_signal",
                "macd_histogram","bollinger20_lower","bollinger20_middle",
                "bollinger20_upper","adx14","plus_di14","minus_di14",
                "stochastic14_k","stochastic3_d"):
        assert snap[key] is not None, key
    assert snap["indicator_parameters"]["EMA"] == [9,20,50]
    assert "NOT_IDENTIFIABLE" in snap["unlabelled_chart_panes"]


def test_mtf_confluence_uses_weighted_groups_without_counting_correlated_indicators_twice():
    frames={"H4":frame(180,14400),"H1":frame(180,3600),"M15":frame(180,900),
            "M5":frame(180,300),"M1":frame(180,60)}
    audit=build_mtf_audit(frames)
    assert audit["score"]["max_per_side"] == 36
    assert audit["confluence"]["H4"]["weight"] == 3
    assert set(audit["confluence"]["M1"]["group_votes"]) >= {
        "trend","momentum_macd","oscillator_rsi_stoch","directional_strength_adx_di",
        "volatility_bollinger","atr14"}
    assert audit["score"]["decision"] in {"LONG_BIAS","SHORT_BIAS","NO_DIRECTIONAL_EDGE"}
    assert audit["limitations"]


def test_missing_data_is_not_fabricated():
    snap=indicator_snapshot([])
    assert snap["last_close"] is None
    assert snap["rsi14"] is None
    assert snap["macd_histogram"] is None
    assert snap["ema_stack"] == "MIXED/NA"


def test_v2_reports_invalid_rows_and_uses_coverage_adjusted_score():
    rows = frame(180, 60)
    rows.append({"epoch": 1700000000 + 181*60, "open": 1, "high": 0, "low": 2, "close": 1})
    snap = indicator_snapshot(rows)
    assert snap["version"] == "2.0.0"
    assert snap["data_quality"]["invalid_rows"] == 1
    assert snap["data_quality"]["valid_rows"] == 180
    sparse = build_mtf_audit({"H4": frame(10, 14400), "H1": [], "M15": [], "M5": [], "M1": []})
    assert sparse["score"]["coverage_pct"] < 60
    assert sparse["score"]["decision"] == "NO_DIRECTIONAL_EDGE"
    assert sparse["score"]["max_per_side"] < sparse["score"]["total_possible_weight"]


def test_v2_stochastic_slow_k_and_d_are_distinct_series_when_moving():
    snap = indicator_snapshot(frame(180, 60))
    assert snap["stochastic14_k"] is not None
    assert snap["stochastic3_k"] is not None
    assert snap["stochastic3_d"] is not None
    assert snap["indicator_parameters"]["RSI_WILDER"] == 14
