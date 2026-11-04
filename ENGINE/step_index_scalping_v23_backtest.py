"""Chronological OOS replay of exact v23 M5 pullback / M1 trigger. Research-only."""
import json, math, os, asyncio
from pathlib import Path
from datetime import datetime, timezone
from ENGINE.step_index_scalping_v23 import TF, detect, market

USD_PER_PRICE_UNIT_AT_010 = 1.0  # provisional user-declared conversion
TARGET_R = 1.5
MAX_HOLD_M1_BARS = 20
MIN_OOS_TRADES = 100
TARGET_WIN_RATE = 0.70


def wilson(w, n, z=1.96):
    if not n: return [None, None]
    p=w/n; d=1+z*z/n; c=(p+z*z/(2*n))/d
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [c-h,c+h]


def stats(rs):
    n=len(rs); wins=sum(x>0 for x in rs); gp=sum(x for x in rs if x>0); gl=-sum(x for x in rs if x<0)
    eq=peak=dd=0.0
    for x in rs:
        eq+=x; peak=max(peak,eq); dd=max(dd,peak-eq)
    return {"n":n,"wins":wins,"losses":n-wins,"win_rate":wins/n if n else None,
            "wilson95":wilson(wins,n),"expectancy_r":sum(rs)/n if n else None,
            "profit_factor":gp/gl if gl else None,"max_drawdown_r":dd,"total_r":sum(rs)}


def statistical_gate(metrics, min_trades=MIN_OOS_TRADES, target=TARGET_WIN_RATE):
    n=metrics.get("n") or 0
    wr=metrics.get("win_rate")
    ci=metrics.get("wilson95") or [None,None]
    exp=metrics.get("expectancy_r")
    pf=metrics.get("profit_factor")
    passed = bool(n >= min_trades and wr is not None and wr >= target
                  and ci[0] is not None and ci[0] >= target
                  and exp is not None and exp > 0 and pf is not None and pf > 1)
    return {"eligible":passed,"decision":"ELIGIBLE" if passed else "NO_TRADE",
            "minimum_oos_trades":min_trades,"target_win_rate":target,
            "checks":{"minimum_sample":n >= min_trades,"observed_win_rate":wr is not None and wr >= target,
                      "wilson_lower_bound":ci[0] is not None and ci[0] >= target,
                      "positive_expectancy":exp is not None and exp > 0,
                      "profit_factor_above_one":pf is not None and pf > 1}}


def r_multiple(entry, exit_price, risk, side):
    if risk<=0: raise ValueError("risk must be positive")
    return (exit_price-entry)*(1 if side=="LONG" else -1)/risk


def _monetary(distance,lots):
    return abs(distance)*USD_PER_PRICE_UNIT_AT_010*(lots/0.10)


def replay(frames,cost=None):
    """cost is an all-in round-trip price-unit estimate; None disables net metrics."""
    if cost is not None and (not math.isfinite(float(cost)) or float(cost)<0):
        raise ValueError("round-trip cost must be finite and non-negative")
    m1=frames["M1"]; trades=[]; next_i=0
    for i in range(80,len(m1)-MAX_HOLD_M1_BARS-1):
        if i<next_i: continue
        decision=int(m1[i]["epoch"])+TF["M1"]
        hist={tf:[r for r in rows if int(r["epoch"])+TF[tf]<=decision] for tf,rows in frames.items()}
        sig=detect(hist)
        if not sig.get("confirmed") or sig.get("direction") not in {"LONG","SHORT"}: continue
        entry=float(m1[i+1]["open"]); side=sig["direction"]
        levels=sig.get("reference_levels") or {}; stop=levels.get("stop_loss")
        if stop is None: continue
        stop=float(stop)
        if not math.isfinite(entry) or not math.isfinite(stop) or entry<=0: continue
        if (side=="LONG" and stop>=entry) or (side=="SHORT" and stop<=entry): continue
        risk=abs(entry-stop)
        if risk<=0: continue
        target=entry+(risk*TARGET_R if side=="LONG" else -risk*TARGET_R)
        exit_price=None; reason="TIME_EXIT"
        # Entry is i+1. Evaluate exactly 20 bars: i+1 through i+20 inclusive.
        end=min(len(m1)-1,i+MAX_HOLD_M1_BARS)
        for j in range(i+1,end+1):
            high,low=float(m1[j]["high"]),float(m1[j]["low"])
            stop_hit=low<=stop if side=="LONG" else high>=stop
            target_hit=high>=target if side=="LONG" else low<=target
            if stop_hit:
                exit_price=stop; reason="STOP_FIRST" if target_hit else "STOP"; break
            if target_hit: exit_price=target; reason="TARGET"; break
        if exit_price is None: exit_price=float(m1[end]["close"])
        gross_r=r_multiple(entry,exit_price,risk,side)
        cost_r=float(cost)/risk if cost is not None else None
        net_r=gross_r-cost_r if cost_r is not None else None
        signed=(exit_price-entry)*(1 if side=="LONG" else -1)
        scenarios={}
        for lots in (0.10,0.20):
            scenarios[str(lots)]={"lots":lots,"risk_usd_provisional":round(_monetary(risk,lots),4),
                "target_profit_usd_gross_provisional":round(_monetary(risk*TARGET_R,lots),4),
                "realized_pnl_usd_gross_provisional":round(signed*USD_PER_PRICE_UNIT_AT_010*(lots/0.10),4),
                "round_trip_cost_usd_provisional":round(_monetary(cost,lots),4) if cost is not None else None,
                "realized_pnl_usd_net_provisional":round((signed-float(cost))*USD_PER_PRICE_UNIT_AT_010*(lots/0.10),4) if cost is not None else None}
        trades.append({"signal_epoch":decision,"entry_epoch":int(m1[i+1]["epoch"]),"direction":side,
            "entry":entry,"exit":exit_price,"stop":stop,"target":target,"risk_price_units":risk,
            "gross_r":gross_r,"round_trip_cost_price_units":cost,"cost_r":cost_r,"net_r":net_r,
            "exit_reason":reason,"holding_bars_m1":j-i if 'j' in locals() else end-i,
            "monetary_scenarios":scenarios})
        next_i=end+1
    n=len(trades); split=int(n*.60); valid=int(n*.80)
    def split_stats(vals):
        if vals is None: return {"all":None,"train":None,"validation":None,"oos":None}
        return {"all":stats(vals),"train":stats(vals[:split]),"validation":stats(vals[split:valid]),"oos":stats(vals[valid:])}
    gross=[x["gross_r"] for x in trades]
    net=[x["net_r"] for x in trades] if cost is not None else None
    return {"method":"Closed OHLC; exact v23 detector; next M1 open; detector ATR stop; 1.5R target; stop-first; one position; max 20 M1 bars",
        "rule_id":"m5_pullback_ema10_20_rejection_mtf_h1_m15_h4_then_m1_break_previous_high_low_ema9_rsi14",
        "target_r":TARGET_R,"max_hold_m1_bars":MAX_HOLD_M1_BARS,
        "split_method":"Chronological 60% train / 20% validation / 20% OOS by trade sequence",
        "cost_model":{"round_trip_cost_price_units":cost,"net_enabled":cost is not None,
          "status":"CONFIGURED_ALL_IN_ESTIMATE_NOT_BROKER_COMPONENT_VERIFIED" if cost is not None else "BLOCKED_MISSING_VERIFIABLE_ALL_IN_COST",
          "monetary_conversion":"USER_DECLARED_PROVISIONAL: USD 0.10 per 0.1 price units at 0.10 lots; not broker tick-value verified",
          "commission_and_slippage_separately_verified":False},
        "gross":split_stats(gross),"net":split_stats(net),
        "split_trade_indices":{"train_end_exclusive":split,"validation_end_exclusive":valid,"oos_start":valid},
        "trades":trades}


def main():
    raw=os.getenv("SQAO_SCALP_ROUND_TRIP_COST_PRICE","").strip(); cost=float(raw) if raw else None
    if cost is not None and (not math.isfinite(cost) or cost<0): raise SystemExit("Invalid round-trip cost")
    sym,frames,diagnostics=asyncio.run(market()); bt=replay(frames,cost)
    gate=statistical_gate(bt["gross"]["oos"])
    result={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":sym,
        "source":"Deriv public timestamped OHLC; closed candles only","data_counts":{k:len(v) for k,v in frames.items()},
        "data_diagnostics":diagnostics,"read_only":True,"backtest":bt,
        "decision":gate["decision"],"eligibility":gate,
        "table17":{"exact_rule_id":bt["rule_id"],"gross_oos":bt["gross"]["oos"],"net_oos":bt["net"]["oos"],
            "monetary_scenarios":"Per-trade USD risk/reward/P&L for 0.10 and 0.20 lots in trades[]",
            "cost_status":bt["cost_model"]["status"],"eligibility":gate}}
    Path("DATA").mkdir(exist_ok=True)
    Path("DATA/step_index_scalping_v23_backtest.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"symbol":sym,"counts":result["data_counts"],"gross_oos":bt["gross"]["oos"],
        "net_oos":bt["net"]["oos"],"decision":gate["decision"],"eligibility":gate,
        "cost_status":bt["cost_model"]["status"]},indent=2,allow_nan=False))


if __name__=="__main__": main()
