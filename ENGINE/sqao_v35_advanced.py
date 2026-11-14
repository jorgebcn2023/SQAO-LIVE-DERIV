"""Advanced diagnostics and explicit market-structure primitives for SQAO V3.5.
READ-ONLY / RESEARCH-ONLY. These are descriptive research features, not signals.
"""
from __future__ import annotations
import math
from typing import Any, Callable, Iterable


def _gammaincc(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a,x), Numerical Recipes approximation."""
    if a <= 0 or x < 0 or not math.isfinite(a+x):
        raise ValueError("invalid gamma arguments")
    if x == 0: return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        ap = a; term = total = 1.0/a
        for _ in range(10000):
            ap += 1.0; term *= x/ap; total += term
            if abs(term) < abs(total)*1e-14: break
        p = total * math.exp(-x + a*math.log(x) - gln)
        return min(1.0, max(0.0, 1.0-p))
    b = x + 1.0 - a; c = 1e300; d = 1.0/b; h = d
    for i in range(1,10000):
        an = -i*(i-a); b += 2.0; d = an*d+b
        if abs(d)<1e-300: d=1e-300
        c=b+an/c
        if abs(c)<1e-300: c=1e-300
        d=1.0/d; delta=d*c; h*=delta
        if abs(delta-1.0)<1e-14: break
    return min(1.0,max(0.0,math.exp(-x+a*math.log(x)-gln)*h))


def ljung_box(values: Iterable[float], max_lag: int = 10) -> dict[str, Any]:
    xs=[float(v) for v in values]
    n=len(xs)
    if n < 20 or max_lag < 1 or max_lag >= n:
        return {"n":n,"lag":max_lag,"q_stat":None,"p_value":None,"status":"INSUFFICIENT_SAMPLE"}
    if not all(math.isfinite(x) for x in xs):
        return {"n":n,"lag":max_lag,"q_stat":None,"p_value":None,"status":"INVALID_VALUES"}
    mean=sum(xs)/n; den=sum((x-mean)**2 for x in xs)
    if den == 0:
        return {"n":n,"lag":max_lag,"q_stat":0.0,"p_value":1.0,"status":"ZERO_VARIANCE"}
    acf=[]
    for lag in range(1,max_lag+1):
        acf.append(sum((xs[t]-mean)*(xs[t-lag]-mean) for t in range(lag,n))/den)
    q=n*(n+2)*sum(r*r/(n-k) for k,r in enumerate(acf,1))
    p=_gammaincc(max_lag/2.0,q/2.0)
    return {"n":n,"lag":max_lag,"q_stat":q,"p_value":p,
            "reject_white_noise_at_5pct":p<0.05,"status":"OK",
            "caveat":"Residual diagnostic; not a standalone trading edge test."}


def adx_di(rows: Iterable[dict[str, Any]], period: int = 14) -> dict[str, Any]:
    data=list(rows)
    if period<2 or len(data)<2*period+1:
        return {"adx":None,"plus_di":None,"minus_di":None,"status":"INSUFFICIENT_SAMPLE"}
    tr=[]; plus=[]; minus=[]
    for prev,cur in zip(data,data[1:]):
        h,l,cprev=float(cur["high"]),float(cur["low"]),float(prev["close"])
        up=h-float(prev["high"]); down=float(prev["low"])-l
        plus.append(up if up>down and up>0 else 0.0)
        minus.append(down if down>up and down>0 else 0.0)
        tr.append(max(h-l,abs(h-cprev),abs(l-cprev)))
    dx=[]
    for i in range(period-1,len(tr)):
        atr=sum(tr[i-period+1:i+1])/period
        if atr<=0: continue
        pdi=100*(sum(plus[i-period+1:i+1])/period)/atr
        mdi=100*(sum(minus[i-period+1:i+1])/period)/atr
        dx.append(100*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi else 0.0)
    if len(dx)<period:
        return {"adx":None,"plus_di":None,"minus_di":None,"status":"INSUFFICIENT_SAMPLE"}
    adx=sum(dx[-period:])/period
    i=len(tr)-1; atr=sum(tr[-period:])/period
    pdi=100*(sum(plus[-period:])/period)/atr if atr else 0.0
    mdi=100*(sum(minus[-period:])/period)/atr if atr else 0.0
    return {"adx":adx,"plus_di":pdi,"minus_di":mdi,"status":"OK"}


def atr_value(rows: Iterable[dict[str, Any]], period: int = 14) -> float | None:
    data=list(rows)
    if period<1 or len(data)<period+1: return None
    trs=[]
    for prev,cur in zip(data,data[1:]):
        h,l,pc=float(cur["high"]),float(cur["low"]),float(prev["close"])
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs[-period:])/period


def _pivots(rows: list[dict[str,Any]], left: int, right: int) -> tuple[list[tuple[int,float]],list[tuple[int,float]]]:
    highs=[]; lows=[]
    for i in range(left,len(rows)-right):
        h=float(rows[i]["high"]); l=float(rows[i]["low"])
        if all(h>float(rows[j]["high"]) for j in range(i-left,i)) and all(h>=float(rows[j]["high"]) for j in range(i+1,i+right+1)):
            highs.append((i,h))
        if all(l<float(rows[j]["low"]) for j in range(i-left,i)) and all(l<=float(rows[j]["low"]) for j in range(i+1,i+right+1)):
            lows.append((i,l))
    return highs,lows


def market_structure(rows: Iterable[dict[str,Any]], left: int=2, right: int=2) -> dict[str,Any]:
    """Confirmed swing breaks. Latest right bars are excluded from pivot confirmation."""
    data=list(rows)
    if left<1 or right<1 or len(data)<left+right+5:
        return {"status":"INSUFFICIENT_SAMPLE","bos":None,"choch":None,"pivots_high":[],"pivots_low":[]}
    ph,pl=_pivots(data,left,right)
    if not ph or not pl:
        return {"status":"NO_CONFIRMED_SWINGS","bos":None,"choch":None,"pivots_high":ph,"pivots_low":pl}
    last_close=float(data[-1]["close"])
    last_high=ph[-1][1]; last_low=pl[-1][1]
    prior_high=ph[-2][1] if len(ph)>1 else None
    prior_low=pl[-2][1] if len(pl)>1 else None
    trend="UP" if prior_high is not None and prior_low is not None and last_high>prior_high and last_low>prior_low else "DOWN" if prior_high is not None and prior_low is not None and last_high<prior_high and last_low<prior_low else "RANGE"
    bos="BULLISH" if last_close>last_high else "BEARISH" if last_close<last_low else None
    choch=("BEARISH" if bos=="BEARISH" and trend=="UP" else "BULLISH" if bos=="BULLISH" and trend=="DOWN" else None)
    return {"status":"OK","trend_before_break":trend,"bos":bos,"choch":choch,
            "last_confirmed_swing_high":last_high,"last_confirmed_swing_low":last_low,
            "pivots_high":ph,"pivots_low":pl,
            "caveat":"Mechanical pivot definition only; no discretionary SMC interpretation."}


def fair_value_gaps(rows: Iterable[dict[str,Any]]) -> list[dict[str,Any]]:
    data=list(rows); zones=[]
    for i in range(2,len(data)):
        old_high=float(data[i-2]["high"]); old_low=float(data[i-2]["low"])
        new_high=float(data[i]["high"]); new_low=float(data[i]["low"])
        if new_low>old_high:
            zones.append({"type":"BULLISH_FVG","lower":old_high,"upper":new_low,"formed_index":i})
        elif new_high<old_low:
            zones.append({"type":"BEARISH_FVG","lower":new_high,"upper":old_low,"formed_index":i})
    return zones


def order_block_candidates(rows: Iterable[dict[str,Any]], lookback: int=20) -> list[dict[str,Any]]:
    """Last opposite candle before a close breaking the preceding range; candidate only."""
    data=list(rows); out=[]
    if lookback<2: return out
    for i in range(lookback+1,len(data)):
        prior_high=max(float(x["high"]) for x in data[i-lookback-1:i-1])
        prior_low=min(float(x["low"]) for x in data[i-lookback-1:i-1])
        close=float(data[i]["close"])
        direction="BULLISH" if close>prior_high else "BEARISH" if close<prior_low else None
        if not direction: continue
        for j in range(i-1,max(-1,i-5),-1):
            o,c=float(data[j]["open"]),float(data[j]["close"])
            opposite=(direction=="BULLISH" and c<o) or (direction=="BEARISH" and c>o)
            if opposite:
                out.append({"direction":direction,"lower":float(data[j]["low"]),
                            "upper":float(data[j]["high"]),"source_index":j,
                            "break_index":i,"status":"CANDIDATE_NOT_VALIDATED"})
                break
    return out


def walk_forward_splits(n: int, train_fraction: float=0.60,
                         validation_fraction: float=0.20, folds: int=3) -> list[dict[str,int]]:
    """Expanding chronological splits; final holdout is never mixed into train."""
    if n<10 or folds<1 or not 0<train_fraction<1 or not 0<validation_fraction<1 or train_fraction+validation_fraction>=1:
        raise ValueError("invalid walk-forward configuration")
    first_train=max(5,int(n*train_fraction))
    remaining=n-first_train
    test_size=max(1,remaining//(folds+1))
    result=[]
    for k in range(folds):
        train_end=first_train+k*test_size
        val_end=min(n,train_end+max(1,int(n*validation_fraction/folds)))
        test_end=min(n,val_end+test_size)
        if test_end<=val_end: break
        result.append({"train_start":0,"train_end":train_end,
                       "validation_start":train_end,"validation_end":val_end,
                       "test_start":val_end,"test_end":test_end})
    return result


def evaluate_walk_forward(items: Iterable[Any], evaluator: Callable[[list[Any],list[Any],list[Any]],dict[str,Any]],
                          train_fraction: float=0.60, validation_fraction: float=0.20, folds: int=3) -> dict[str,Any]:
    data=list(items); splits=walk_forward_splits(len(data),train_fraction,validation_fraction,folds)
    results=[]
    for split in splits:
        result=evaluator(data[split["train_start"]:split["train_end"]],
                         data[split["validation_start"]:split["validation_end"]],
                         data[split["test_start"]:split["test_end"]])
        results.append({"split":split,"metrics":result})
    return {"method":"EXPANDING_CHRONOLOGICAL_WALK_FORWARD","folds":results,
            "leakage_control":"Each fold trains only on prior observations; test slice follows validation.",
            "status":"OK" if results else "NO_VALID_FOLDS"}
