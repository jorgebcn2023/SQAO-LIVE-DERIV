"""SQAO Step Index MTF scalping v23. Research-only; never places orders."""
from __future__ import annotations
import asyncio, json, math, os
from datetime import datetime, timezone
from pathlib import Path
import websockets

WS = os.getenv("DERIV_PUBLIC_WS", "wss://api.derivws.com/trading/v1/options/ws/public")
TF = {"M1":60,"M5":300,"M15":900,"H1":3600,"H4":14400}

def ema(x, n):
    if len(x)<n: return None
    a=2/(n+1); v=sum(x[:n])/n
    for z in x[n:]: v=a*z+(1-a)*v
    return v

def atr(rows,n=14):
    if len(rows)<n+1:return None
    tr=[]
    for p,c in zip(rows,rows[1:]):
        tr.append(max(c["high"]-c["low"],abs(c["high"]-p["close"]),abs(c["low"]-p["close"])))
    return sum(tr[-n:])/n

def direction(rows):
    c=[r["close"] for r in rows]
    a,b=ema(c,10),ema(c,20)
    return "LONG" if a is not None and b is not None and a>b else "SHORT" if a is not None and b is not None and a<b else None

def validate(rows,tf,now):
    sec=TF[tf]; out={}
    for r in rows:
        try:
            x={k:float(r[k]) for k in ("open","high","low","close")}
            t=int(r["epoch"])
            if t+sec>now or not all(math.isfinite(v) for v in x.values()):continue
            if x["high"]<max(x["open"],x["close"],x["low"]) or x["low"]>min(x["open"],x["close"],x["high"]):continue
            out[t]={"epoch":t,**x}
        except (KeyError,TypeError,ValueError): continue
    return [out[t] for t in sorted(out)]

async def req(ws,p):
    await ws.send(json.dumps(p))
    while True:
        m=json.loads(await asyncio.wait_for(ws.recv(),timeout=25))
        if m.get("error"): raise RuntimeError(m["error"].get("message","Deriv API error"))
        if m.get("req_id")==p["req_id"]: return m

async def fetch_candles(ws, symbol, tf, count, req_id, page_size=1000):
    """Fetch closed OHLC history in backward pages; tolerate API page caps."""
    if count < 1 or page_size < 2:
        raise ValueError("count and page_size must be positive")
    sec = TF[tf]
    collected = {}
    end = "latest"
    last_earliest = None
    raw_count = 0
    while len(collected) < count + 2:
        ask = min(page_size, count + 2 - len(collected))
        data = await req(ws, {
            "ticks_history": symbol, "end": end, "count": ask,
            "style": "candles", "granularity": sec, "req_id": req_id,
        })
        req_id += 1
        page = data.get("candles", []) or []
        if not page:
            break
        before = len(collected)
        for row in page:
            try:
                epoch = int(row["epoch"])
                collected[epoch] = row
            except (KeyError, TypeError, ValueError):
                continue
        raw_count += len(page)
        earliest = min(collected) if collected else None
        if len(collected) == before or earliest is None or earliest == last_earliest:
            break
        last_earliest = earliest
        end = earliest - 1
        if len(page) < 1:
            break
        if raw_count > count * 4 + 100:
            raise RuntimeError(f"{tf}: pagination safety limit reached; collected={len(collected)}")
    now = int(datetime.now(timezone.utc).timestamp())
    rows = validate([collected[t] for t in sorted(collected)], tf, now)
    return rows[-count:]


async def market():
    async with websockets.connect(WS,open_timeout=20,ping_interval=20) as ws:
        d=await req(ws,{"active_symbols":"brief","req_id":1})
    # Deriv current schema uses underlying_symbol/name; retain legacy fallbacks.
    raw_symbols=d.get("active_symbols",[])
    symbols=[]
    for item in raw_symbols:
        code=str(item.get("underlying_symbol") or item.get("symbol") or "").strip()
        name=str(item.get("underlying_symbol_name") or item.get("display_name") or "").strip()
        if code and "step index" in (name+" "+code).lower():
            symbols.append({"symbol":code,"name":name or code})
    if not symbols:
        sample=[{"code":str(x.get("underlying_symbol") or x.get("symbol") or ""),
                 "name":str(x.get("underlying_symbol_name") or x.get("display_name") or "")}
                for x in raw_symbols[:12]]
        raise RuntimeError(f"Deriv active_symbols returned {len(raw_symbols)} symbols but no Step Index match; sample={sample}")
    sym=next((x for x in symbols if x["name"].lower()=="step index"),symbols[0])
    requested={"M1":int(os.getenv("SQAO_SCALP_CANDLES_M1","20000")),"M5":int(os.getenv("SQAO_SCALP_CANDLES_M5","20000")),"M15":int(os.getenv("SQAO_SCALP_CANDLES_M15","7000")),"H1":int(os.getenv("SQAO_SCALP_CANDLES_H1","2500")),"H4":int(os.getenv("SQAO_SCALP_CANDLES_H4","1000"))}
    frames={}
    async with websockets.connect(WS,open_timeout=20,ping_interval=20) as ws:
        for i,(tf,count) in enumerate(requested.items(),10):
            frames[tf]=await fetch_candles(ws,sym["symbol"],tf,count,i*1000)
    diagnostics={}
    for tf,rows in frames.items():
        epochs=[r["epoch"] for r in rows]
        gaps=[(b-a)//TF[tf] for a,b in zip(epochs,epochs[1:]) if b-a>TF[tf]]
        diagnostics[tf]={
            "requested_closed":requested[tf],
            "received_closed":len(rows),
            "shortfall":max(0,requested[tf]-len(rows)),
            "duplicate_epochs_removed":True,
            "gap_count":len(gaps),
            "max_gap_bars":max(gaps,default=1),
            "first_epoch":epochs[0] if epochs else None,
            "last_epoch":epochs[-1] if epochs else None,
        }
    return sym,frames,diagnostics

async def fetch_current_m1_open(symbol):
    """Read the forming M1 candle's open only; never use its high/low/close for signals."""
    async with websockets.connect(WS,open_timeout=20,ping_interval=20) as ws:
        data=await req(ws,{"ticks_history":symbol,"end":"latest","count":1,
                           "style":"candles","granularity":TF["M1"],"req_id":99001})
    rows=data.get("candles",[]) or []
    if not rows:
        return None
    try:
        row=rows[-1]; epoch=int(row["epoch"]); price=float(row["open"])
        now=int(datetime.now(timezone.utc).timestamp())
        if not math.isfinite(price) or price<=0 or not (epoch<=now<epoch+TF["M1"]):
            return None
        return {"epoch":epoch,"open":price,"source":"Deriv current M1 candle open"}
    except (KeyError,TypeError,ValueError):
        return None

def match_next_m1_open(next_open, expected_epoch):
    """Accept only a finite positive open for the exact expected M1 epoch."""
    if not isinstance(next_open, dict):
        return None
    try:
        epoch = int(next_open["epoch"])
        price = float(next_open["open"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if epoch != int(expected_epoch) or not math.isfinite(price) or price <= 0:
        return None
    return {"epoch": epoch, "open": price}


def execution_levels(direction_value, entry, atr_value, stop_atr=1.2, target_r=1.5):
    """Return price levels in quoted price units; no monetary conversion."""
    if direction_value not in {"LONG","SHORT"} or entry is None or atr_value is None:
        return None
    if not all(math.isfinite(float(x)) for x in (entry,atr_value,stop_atr,target_r)):
        return None
    if float(entry)<=0 or float(atr_value)<=0 or float(stop_atr)<=0 or float(target_r)<=0:
        return None
    risk=float(atr_value)*float(stop_atr)
    sign=1 if direction_value=="LONG" else -1
    stop=float(entry)-sign*risk
    target=float(entry)+sign*risk*float(target_r)
    return {"entry":float(entry),"stop_loss":stop,"take_profit":target,
            "risk_price_units":risk,"reward_price_units":risk*float(target_r),
            "risk_reward":f"1:{float(target_r):g}"}


def synchronize_frames(frames, decision_epoch):
    """Keep only fully closed candles whose close time is <= the M1 decision epoch."""
    cutoff = int(decision_epoch)
    aligned = {}
    for tf, rows in frames.items():
        sec = TF[tf]
        aligned[tf] = [r for r in rows if int(r["epoch"]) + sec <= cutoff]
    return aligned


def detect(f, next_open=None):
    need={"M1":40,"M5":40,"M15":30,"H1":30}
    if any(len(f.get(k,[]))<n for k,n in need.items()):return {"state":"INSUFFICIENT_DATA","confirmed":False}
    m1,m5=f["M1"],f["M5"]; bias=direction(f["H1"][-100:]); mid=direction(f["M15"][-100:])
    h4=direction(f["H4"][-100:]) if len(f.get("H4",[]))>=30 else None
    if not bias or bias!=mid or (h4 and h4!=bias):return {"state":"MTF_CONFLICT","confirmed":False}
    c=[r["close"] for r in m5[-100:]]
    e10,e20=ema(c,10),ema(c,20); last=m5[-1]
    if e10 is None or e20 is None:return {"state":"INSUFFICIENT_DATA","confirmed":False}
    # Pullback touches EMA10-20 area and closes back in trend direction.
    lo=min(e10,e20); hi=max(e10,e20)
    touched=last["low"]<=hi and last["high"]>=lo
    rejected=(last["close"]>hi and bias=="LONG") or (last["close"]<lo and bias=="SHORT")
    if not (touched and rejected):return {"state":"BIAS_ONLY_WAIT_PULLBACK","confirmed":False,"direction":bias}
    prev=m1[-2]; cur=m1[-1]; rsi_closes=[x["close"] for x in m1[-15:]]
    delta=[rsi_closes[i]-rsi_closes[i-1] for i in range(1,len(rsi_closes))]
    gains=sum(max(x,0) for x in delta)/14; losses=sum(max(-x,0) for x in delta)/14
    rsi=100 if losses==0 and gains else 50 if losses==0 else 100-100/(1+gains/losses)
    trig=(cur["close"]>prev["high"] and cur["close"]>ema([x["close"] for x in m1[-30:]],9) and rsi>=50) if bias=="LONG" else (cur["close"]<prev["low"] and cur["close"]<ema([x["close"] for x in m1[-30:]],9) and rsi<=50)
    if not trig:return {"state":"M5_SETUP_WAIT_M1_TRIGGER","confirmed":False,"direction":bias,"rsi14":rsi}
    vol=atr(m1[-100:],14)
    if not vol or vol<=0:return {"state":"ATR_UNAVAILABLE","confirmed":False}
    decision_epoch=cur["epoch"]+TF["M1"]
    reference=execution_levels(bias,cur["close"],vol)
    matched_open = match_next_m1_open(next_open, decision_epoch)
    executable=execution_levels(bias,matched_open["open"],vol) if matched_open else None
    return {"state":"TRIGGER_CONFIRMED_NEXT_M1_OPEN" if executable else "TRIGGER_CONFIRMED_WAIT_NEXT_M1_OPEN",
            "confirmed":True,"direction":bias,"reference_close":cur["close"],
            "reference_levels":reference,"execution_levels":executable,
            "entry_price":executable["entry"] if executable else None,
            "stop_loss":executable["stop_loss"] if executable else None,
            "take_profit":executable["take_profit"] if executable else None,
            "execution_price_confirmed":bool(executable),"atr14_m1":vol,
            "decision_epoch":decision_epoch,"entry_rule":"open of next M1 candle; exact epoch match required",
            "status":"CONDITIONAL_SETUP_REQUIRES_LIVE_CONFIRMATION" if executable else "NO_TRADE"}

def main():
    sym,frames,diagnostics=asyncio.run(market())
    # Anchor every timeframe to the latest fully closed M1 decision boundary.
    decision_epoch = int(frames["M1"][-1]["epoch"]) + TF["M1"] if frames.get("M1") else 0
    aligned_frames = synchronize_frames(frames, decision_epoch)
    next_open=asyncio.run(fetch_current_m1_open(sym["symbol"]))
    setup=detect(aligned_frames,next_open)
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":sym,"source":"Deriv public OHLC, closed candles only","read_only":True,"data_counts":{k:len(v) for k,v in frames.items()},"data_diagnostics":diagnostics,"last_closed":{k:v[-1] if v else None for k,v in frames.items()},"next_m1_open":next_open,"setup":setup,"warning":"A trigger is a research signal, not a profitability estimate. Validate execution costs and OOS statistics before use."}
    Path("DATA").mkdir(exist_ok=True); Path("DATA/step_index_scalping_v23.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"symbol":sym,"counts":report["data_counts"],"setup":setup},indent=2))
if __name__=="__main__": main()
