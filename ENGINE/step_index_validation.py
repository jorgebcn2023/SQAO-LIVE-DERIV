from __future__ import annotations
"""Step Index-only MTF walk-forward backtest. Research only; never places trades."""
import asyncio, json, math, os, urllib.request
from datetime import datetime, timezone
from pathlib import Path

WS = os.getenv("DERIV_PUBLIC_WS", "wss://api.derivws.com/trading/v1/options/ws/public")
COUNT = int(os.getenv("SQAO_STEP_CANDLES", "5000"))
MIN_TRADES = int(os.getenv("SQAO_STEP_MIN_TRADES", "100"))
TARGET_WIN_RATE = float(os.getenv("SQAO_STEP_TARGET_WIN_RATE", "0.70"))
RR = float(os.getenv("SQAO_STEP_RR", "1.0"))
ATR_MULT = float(os.getenv("SQAO_STEP_ATR_MULT", "1.2"))
HORIZON = int(os.getenv("SQAO_STEP_HORIZON", "5"))
# Net validation is disabled until the user supplies an empirically grounded round-trip cost in R.
COST_R_TEXT = os.getenv("SQAO_STEP_COST_R", "").strip()
COST_R = float(COST_R_TEXT) if COST_R_TEXT else None
OUT = Path(os.getenv("SQAO_STEP_OUT", "DATA/step_index_validation.json"))

def ema(xs, p):
    if len(xs) < p: return None
    v = sum(xs[:p]) / p; k = 2 / (p + 1)
    for x in xs[p:]: v = x*k + v*(1-k)
    return v

def rsi(xs, p=14):
    if len(xs) < p+1: return None
    diffs=[xs[i]-xs[i-1] for i in range(len(xs)-p,len(xs))]
    gains=sum(max(x,0) for x in diffs)/p
    losses=sum(max(-x,0) for x in diffs)/p
    return 100.0 if losses == 0 else 100 - 100/(1+gains/losses)

def atr(rows,p=14):
    if len(rows)<p+1:return None
    tr=[]
    for i in range(1,len(rows)):
        r,prev=rows[i],rows[i-1]
        tr.append(max(float(r["high"])-float(r["low"]),abs(float(r["high"])-float(prev["close"])),abs(float(r["low"])-float(prev["close"]))))
    return sum(tr[-p:])/p

async def request(ws,payload):
    import websockets
    await ws.send(json.dumps(payload))
    rid=payload["req_id"]
    while True:
        m=json.loads(await ws.recv())
        if m.get("error"): raise RuntimeError(m["error"].get("message","Deriv API error"))
        if m.get("req_id")==rid:return m

async def get_candles(symbol, granularity, count):
    import websockets
    async with websockets.connect(WS,ping_interval=20,ping_timeout=20,open_timeout=20) as ws:
        m=await request(ws,{"ticks_history":symbol,"end":"latest","count":count,"style":"candles","granularity":granularity,"adjust_start_time":1,"subscribe":0,"req_id":granularity})
    rows=m.get("candles",[])
    return sorted((r for r in rows if all(k in r for k in ("epoch","open","high","low","close"))),key=lambda r:int(r["epoch"]))

async def find_step_symbol():
    import websockets
    async with websockets.connect(WS,ping_interval=20,ping_timeout=20,open_timeout=20) as ws:
        m=await request(ws,{"active_symbols":"brief","req_id":1})
    matches=[]
    for x in m.get("active_symbols",[]):
        name=str(x.get("display_name","")); sym=str(x.get("symbol",""))
        if "step index" in name.lower() or "step index" in sym.lower(): matches.append({"symbol":sym,"name":name})
    if not matches: raise RuntimeError("No se encontró Step Index en active_symbols; no se ejecuta un sustituto.")
    # Prefer the exact display name, never silently substitute another synthetic.
    exact=[x for x in matches if x["name"].strip().lower()=="step index"]
    return (exact or matches)[0]

def trend_at(rows, decision_epoch, granularity):
    # Deriv candle epoch is its OPEN time; only use bars whose close was known at decision time.
    eligible=[r for r in rows if int(r["epoch"]) + granularity <= decision_epoch]
    if len(eligible)<30:return None
    closes=[float(r["close"]) for r in eligible]
    a,b=ema(closes,10),ema(closes,20)
    if a is None or b is None:return None
    return "LONG" if a>b else "SHORT" if a<b else None

def wilson(w,n,z=1.96):
    if n==0:return None,None
    p=w/n; d=1+z*z/n
    center=(p+z*z/(2*n))/d
    half=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/d
    return max(0,center-half),min(1,center+half)

def backtest(m1,m5,m15,h1):
    # Signal on a closed M5 candle; confirm direction with M15 and H1 values known at that time.
    bytime={int(r["epoch"]):r for r in m5}
    times=sorted(bytime)
    results=[]; trades=[]; next_allowed=-1
    for ix,t in enumerate(times):
        if ix<40 or ix>=len(times)-HORIZON:continue
        if ix<next_allowed:continue
        r=bytime[t]
        hist=[x for x in m5[:ix+1]]
        closes=[float(x["close"]) for x in hist]
        e10,e20=ema(closes,10),ema(closes,20); a=atr(hist)
        if not a or not e10 or not e20:continue
        prev=closes[-21:-1]
        if len(prev)<20:continue
        direction="LONG" if closes[-1]>max(prev) and e10>e20 else "SHORT" if closes[-1]<min(prev) and e10<e20 else None
        if not direction:continue
        decision_epoch=t+300  # M5 signal candle has just closed at this instant.
        if trend_at(m15,decision_epoch,900)!=direction or trend_at(h1,decision_epoch,3600)!=direction:continue
        # RSI on M1 is a timing guard, using only candles closed by signal time.
        m1hist=[x for x in m1 if int(x["epoch"])+60<=decision_epoch]
        c1=[float(x["close"]) for x in m1hist]
        rv=rsi(c1)
        if rv is None or (direction=="LONG" and rv>72) or (direction=="SHORT" and rv<28):continue
        entry=float(r["close"]); risk=a*ATR_MULT
        stop=entry-risk if direction=="LONG" else entry+risk
        target=entry+risk*RR if direction=="LONG" else entry-risk*RR
        outcome=None; exit_price=None; exit_epoch=None
        for j in range(ix+1,min(len(times),ix+HORIZON+1)):
            q=bytime[times[j]]; hi=float(q["high"]); lo=float(q["low"])
            sl=(lo<=stop) if direction=="LONG" else (hi>=stop)
            tp=(hi>=target) if direction=="LONG" else (lo<=target)
            # Conservative resolution when both barriers are inside one candle.
            if sl and tp: outcome=-1.0;exit_price=stop;exit_epoch=times[j];break
            if sl: outcome=-1.0;exit_price=stop;exit_epoch=times[j];break
            if tp: outcome=RR;exit_price=target;exit_epoch=times[j];break
        if outcome is None:
            q=bytime[times[min(len(times)-1,ix+HORIZON)]]
            exit_price=float(q["close"]);exit_epoch=int(q["epoch"])
            raw=(exit_price-entry)/risk
            outcome=max(-1.0,min(RR,raw if direction=="LONG" else -raw))
        results.append(outcome);next_allowed=next((j for j,x in enumerate(times) if x>exit_epoch),len(times))
        trades.append({"epoch":t,"direction":direction,"entry":entry,"stop":stop,"target":target,"exit":exit_price,"exit_epoch":exit_epoch,"r_multiple":outcome})
    return results,trades

def summarize(rs):
    n=len(rs);wins=sum(x>0 for x in rs);losses=sum(x<0 for x in rs)
    gw=sum(x for x in rs if x>0);gl=-sum(x for x in rs if x<0)
    eq=peak=dd=0
    for x in rs:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
    lo,hi=wilson(wins,n)
    return {"trades":n,"wins":wins,"losses":losses,"win_rate":wins/n if n else None,
      "win_rate_wilson_95_low":lo,"win_rate_wilson_95_high":hi,
      "expectancy_R":sum(rs)/n if n else None,"profit_factor":gw/gl if gl else (None if gw==0 else "infinite"),
      "max_drawdown_R":dd}

async def main():
    symbol=await find_step_symbol()
    # fetch each timeframe separately; use only candles returned by the API
    m1,m5,m15,h1=await asyncio.gather(get_candles(symbol["symbol"],60,COUNT),get_candles(symbol["symbol"],300,COUNT),get_candles(symbol["symbol"],900,COUNT),get_candles(symbol["symbol"],3600,COUNT))
    if min(map(len,(m1,m5,m15,h1)))<200: raise RuntimeError("Histórico insuficiente en al menos un timeframe.")
    # Strict chronological holdout: last 30% of M5; indicators retain prior context, but trades only counted in holdout.
    cut=int(len(m5)*0.70)
    warm_start=max(0,cut-200)
    test_m5=m5[warm_start:]
    cutoff=int(m5[cut]["epoch"])
    test_m5=[r for r in test_m5 if int(r["epoch"])>=cutoff]
    test_m1=[r for r in m1 if int(r["epoch"])>=cutoff-200*60]
    test_m15=[r for r in m15 if int(r["epoch"])>=cutoff-200*900]
    test_h1=[r for r in h1 if int(r["epoch"])>=cutoff-200*3600]
    # prepend warm-up history to permit indicator calculation; only score trades after cutoff.
    test_m5=[r for r in m5 if int(r["epoch"])<cutoff][-200:]+test_m5
    test_m1=[r for r in m1 if int(r["epoch"])<cutoff][-200:]+test_m1
    test_m15=[r for r in m15 if int(r["epoch"])<cutoff][-200:]+test_m15
    test_h1=[r for r in h1 if int(r["epoch"])<cutoff][-200:]+test_h1
    rs,trades=backtest(test_m1,test_m5,test_m15,test_h1)
    # Discard any trades before holdout cutoff.
    pairs=[(x,tr) for x,tr in zip(rs,trades) if int(tr["epoch"])>=cutoff]
    rs=[p[0] for p in pairs];trades=[p[1] for p in pairs]
    gross_metrics=summarize(rs)
    net_rs=[x-COST_R for x in rs] if COST_R is not None else None
    m=summarize(net_rs) if net_rs is not None else gross_metrics
    passed=(COST_R is not None and m["trades"]>=MIN_TRADES and m["win_rate"] is not None and m["win_rate"]>=TARGET_WIN_RATE and m["win_rate_wilson_95_low"]>=TARGET_WIN_RATE and isinstance(m["profit_factor"],(int,float)) and m["profit_factor"]>1 and (m["expectancy_R"] or -1)>0)
    report={"generated_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"strategy":"M5 EMA10/20 + 20-close breakout; M15/H1 EMA trend confirmation; M1 RSI guard","timeframes":{"M1":len(m1),"M5":len(m5),"M15":len(m15),"H1":len(h1)},"holdout_start_utc":datetime.fromtimestamp(cutoff,timezone.utc).isoformat(),"parameters":{"target_win_rate":TARGET_WIN_RATE,"min_trades":MIN_TRADES,"rr":RR,"atr_multiplier":ATR_MULT,"horizon_M5_candles":HORIZON,"round_trip_cost_R":COST_R,"costs_status":"NET COST ADJUSTMENT APPLIED" if COST_R is not None else "NOT MODELED: set SQAO_STEP_COST_R to an evidence-based round-trip cost expressed in R","candle_timestamp_policy":"Higher-timeframe and M1 filters only use candles fully closed by the M5 signal close"},"metrics":{"gross":gross_metrics,"net":m if net_rs is not None else None},"decision":"CANDIDATE_FOR_DEMO_ONLY" if passed else ("NO_TRADE_COSTS_UNCONFIGURED" if COST_R is None else "NO_TRADE"),"trades":trades}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="trades"},indent=2))
    print("Trade log:",OUT)
if __name__=="__main__": asyncio.run(main())
