"""Tests for SQAO V3.5 pure research engine."""
import math
from ENGINE.sqao_v35_engine import (
    validate_ohlc, log_returns, autocorrelation, runs_test, ema, rsi,
    macd, classify_regime, mtf_confluence, size_position, final_decision,
)


def test_ohlc_validation_excludes_open_and_detects_gap():
    rows=[{"epoch":0,"open":1,"high":2,"low":0.5,"close":1.5},
          {"epoch":60,"open":1.5,"high":2,"low":1,"close":1.7},
          {"epoch":240,"open":1.7,"high":2,"low":1,"close":1.8},
          {"epoch":300,"open":1.8,"high":2,"low":1,"close":1.9}]
    out=validate_ohlc(rows,60,350)
    assert out["count"] == 3
    assert out["forming_rows_excluded"] == 1
    assert out["gaps"][0]["missing_intervals"] == 2
    assert not out["integrity_pass"]


def test_ohlc_invalid_and_duplicate():
    rows=[{"epoch":0,"open":1,"high":2,"low":0,"close":1},
          {"epoch":0,"open":1,"high":3,"low":0,"close":2},
          {"epoch":60,"open":1,"high":0,"low":2,"close":1}]
    out=validate_ohlc(rows,60,200)
    assert out["duplicates_removed"] == 1
    assert out["invalid_rows"] == 1


def test_returns_and_acf():
    assert len(log_returns([100,101,100])) == 2
    assert autocorrelation([1,2,1,2,1,2],2)["status"] == "OK"


def test_runs_test_reports_sample_limits():
    assert runs_test([1,2,3])["status"] == "INSUFFICIENT_SAMPLE"
    assert runs_test([1,2,1,2,1,2,1,2,1,2,1,2])["status"] == "OK"


def test_indicators_guard_short_samples():
    assert ema([1,2],20) is None
    assert rsi([1,2,3],14) is None
    assert macd([1,2,3])["line"] is None


def test_regime_and_mtf_missing_data():
    assert classify_regime({"close":100,"ema20":101,"ema50":100}) == "TREND_UP"
    result=mtf_confluence({"D1":{"close":100,"ema20":101,"ema50":100}})
    assert result["status"] == "INCOMPLETE"
    assert result["scores_are_probabilities"] is False


def test_minimum_volume_risk_gate():
    result=size_position(100,0.01,37.5,0.1,0.1,0.1,0.1)
    assert result["decision"] == "NO_TRADE"
    assert result["minimum_volume_loss"] > result["risk_budget"]


def test_valid_size_and_fail_closed_decision():
    result=size_position(1000,0.01,10,0.1,0.1,0.1,0.1)
    assert result["eligible"]
    decision=final_decision(data_integrity_pass=True,mtf_complete=True,
        costs_verified=False,oos_gate_pass=True,technical_direction="SELL",risk_gate_pass=True)
    assert decision["decision"] == "NO_TRADE"
    assert decision["execution_eligible"] is False
