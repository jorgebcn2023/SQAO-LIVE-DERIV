"""Chronological M1 replay for the v23 MTF pullback detector. No orders."""
import json, math, os
from pathlib import Path
from datetime import datetime, timezone
from ENGINE.step_index_scalping_v23 import TF, detect, market

def wilson(w,n,z=1.96):
    if not n:return [None,None]
    p=w/n; d=1+z*z/n; c=(p+z*z/(2*n))/d
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [c-h,c+h]

def stats(rs):
    n=len(rs); wins=sum(x>0 for x in rs); gp=sum(x for x in rs if x>0); gl=-sum(x for x in rs if x<0)
    eq=peak=dd=0
    for x in rs:
        eq+=x; peak=max(peak,eq); dd=max(dd,peak-eq)
    return {"n":n,"win_rate":wins/n if n else None,"wilson95":wilson(wins,n),"expectancy_r":sum(rs)/n if n else None,"profit_factor":gp/gl if gl else None,"max_drawdown_r":dd,"total_r":sum(rs)}

def replay(frames,cost):
    m1=frames["M1"]; trades=[]; next_i=0
    for i in range(80,len(m1)-2):
        if i<next_i:continue
        decision=m1[i]["epoch"]+60
        hist={}
        for tf,rows in frames.items():
            sec=TF[tf]
            hist[tf]=[r for r in rows if r["epoch"]+sec<=decision]
        s=detect(hist)
        if not s.get("confirmed"):continue
        entry=float(m1[i+1]["open"]); stop=float(s["stop_reference"])
        risk=abs(entry-stop)
        if risk<=0:continue
        side=s["direction"]; target=entry+(risk if side=="LONG" else -risk)
        exitp=None; reason="TIME_EXIT"; end=min(len(m1)-1,i+21)
        for j in range(i+1,end+1):
            h,l=m1[j]["high"],m1[j]["low"]
            sh=l<=stop if side=="LONG" else h>=stop
            th=h>=target if side=="LONG" else l<=target
            if sh: exitp=stop;reason="STOP_FIRST" if th else "STOP";break
            if th: exitp=target;reason="TARGET";break
        if exitp is None:exitp=m1[end]["close"]
        gross=(exitp-entry)*(1 if side=="LONG" else -1)/risk
        gross=max(-1,min(1,gross)); cost_r=cost/risk; net=gross-cost_r
        trades.append({"signal_epoch":decision,"direction":side,"entry":entry,"exit":exitp,"stop":stop,"gross_r":gross,"cost_r":cost_r,"net_r":net,"exit_reason":reason})
        next_i=end+1
    rs=[x["net_r"] for x in trades]
    split=int(len(trades)*.6); valid=int(len(trades)*.8)
    return {"method":"closed-candle MTF replay; next M1 open; stop-first; one position at a time; max hold 20 M1 bars","round_trip_cost_price":cost,"all":stats(rs),"train":stats(rs[:split]),"validation":stats(rs[split:valid]),"oos":stats(rs[valid:]),"trades":trades}

def main():
    raw=os.getenv("SQAO_SCALP_ROUND_TRIP_COST_PRICE","").strip()
    if not raw:
        raise SystemExit("BLOCKED_MISSING_ROUND_TRIP_COST_PRICE: configure the realistic spread+slippage+commission in quoted price units")
    cost=float(raw)
    if not math.isfinite(cost) or cost<0:raise SystemExit("Invalid round-trip cost")
    sym,frames=__import__("asyncio").run(market())
    result={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":sym,"data_counts":{k:len(v) for k,v in frames.items()},"read_only":True,"backtest":replay(frames,cost)}
    Path("DATA").mkdir(exist_ok=True);Path("DATA/step_index_scalping_v23_backtest.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"symbol":sym,"counts":result["data_counts"],"oos":result["backtest"]["oos"]},indent=2,allow_nan=False))
if __name__=="__main__":main()
