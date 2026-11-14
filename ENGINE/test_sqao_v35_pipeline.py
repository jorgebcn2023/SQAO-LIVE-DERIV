"""Tests for the isolated V3.5 orchestration adapter."""
from ENGINE.sqao_v35_pipeline import analyze_v35


def test_adapter_is_fail_closed_on_missing_frames():
    result=analyze_v35({},now_epoch=2_000_000_000)
    assert result["engine_version"]=="3.5.0"
    assert result["decision"]["decision"]=="NO_TRADE"
    assert result["execution_eligible"] is False
    assert result["decision"]["execution_eligible"] is False


def test_adapter_does_not_infer_direction_from_short_history():
    frames={tf:[{"epoch":1_900_000_000,"open":100,"high":101,"low":99,"close":100}]
            for tf in ("D1","H4","H1","M15","M5","M1")}
    result=analyze_v35(frames,now_epoch=2_000_000_000,
        costs_verified=True,oos_gate_pass=True,risk_gate_pass=True,
        technical_direction="SELL")
    assert result["decision"]["decision"]=="NO_TRADE"
    assert "DATA_INTEGRITY" in result["decision"]["blockers"] or "MTF_INCOMPLETE" in result["decision"]["blockers"]
