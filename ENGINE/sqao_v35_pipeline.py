"""V3.5 orchestration adapter for caller-supplied verified OHLC.
No network or broker operations. Does not call existing production decision APIs.
"""
from __future__ import annotations
from typing import Any
from .sqao_v35_engine import validate_ohlc, indicator_snapshot, mtf_confluence, log_returns, final_decision
from .sqao_v35_advanced import ljung_box, adx_di, atr_value, market_structure, fair_value_gaps, order_block_candidates

SECONDS={"D1":86400,"H4":14400,"H1":3600,"M15":900,"M5":300,"M1":60}


def analyze_v35(frames: dict[str,list[dict[str,Any]]], now_epoch: int,
                *, costs_verified: bool=False, oos_gate_pass: bool=False,
                risk_gate_pass: bool=False, technical_direction: str|None=None) -> dict[str,Any]:
    validated={}
    snapshots={}
    diagnostics={}
    for tf,seconds in SECONDS.items():
        result=validate_ohlc(frames.get(tf,[]),seconds,now_epoch)
        validated[tf]=result["candles"]
        diagnostics[tf]={k:v for k,v in result.items() if k!="candles"}
        snapshots[tf]=indicator_snapshot(validated[tf])
        closes=[x["close"] for x in validated[tf]]
        returns=log_returns(closes)
        diagnostics[tf]["return_diagnostics"]=ljung_box(returns,min(10,max(1,len(returns)//5))) if len(returns)>=20 else {"status":"INSUFFICIENT_SAMPLE"}
        diagnostics[tf]["adx_di14"]=adx_di(validated[tf])
        diagnostics[tf]["atr14"]=atr_value(validated[tf])
        diagnostics[tf]["market_structure"]=market_structure(validated[tf])
        diagnostics[tf]["fvg_candidates"]=fair_value_gaps(validated[tf])[-10:]
        diagnostics[tf]["order_block_candidates"]=order_block_candidates(validated[tf])[-10:]
    confluence=mtf_confluence(snapshots)
    integrity=all(diagnostics[tf]["integrity_pass"] for tf in SECONDS)
    complete=confluence["status"]=="COMPLETE" and all(len(validated[tf])>=200 for tf in SECONDS)
    decision=final_decision(data_integrity_pass=integrity,mtf_complete=complete,
        costs_verified=costs_verified,oos_gate_pass=oos_gate_pass,
        technical_direction=technical_direction,risk_gate_pass=risk_gate_pass)
    return {"engine_version":"3.5.0","mode":"READ_ONLY_RESEARCH_ONLY",
        "decision":decision,"mtf_confluence":confluence,"data_quality":diagnostics,
        "timeframes":{tf:{"count":len(rows),"latest_closed_epoch":rows[-1]["epoch"] if rows else None,
                           "indicators":snapshots[tf]} for tf,rows in validated.items()},
        "execution_eligible":False,
        "note":"Descriptive diagnostics only. Structural candidates are not trade signals; all gates must pass for analytical direction classification."}
