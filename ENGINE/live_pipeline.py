from __future__ import annotations
import csv, json
from pathlib import Path
from .predictive import build_hour_scenarios

def load_recent(path, limit=200):
    p=Path(path)
    if not p.exists(): return []
    with p.open(newline="",encoding="utf-8") as f: return list(csv.DictReader(f))[-limit:]

def closes(rows): return [float(r["close"]) for r in rows if r.get("close") not in (None,"")]
def bearish(rows, lookback=20):
    c=closes(rows); return len(c)>=lookback and c[-1]<c[-lookback]
def support_holds(rows, lookback=20, tolerance=0.0005):
    c=closes(rows)
    if len(c)<lookback:return False
    lo=min(c[-lookback:]); return c[-1] <= lo*(1+tolerance)
def breakout_confirmed(rows, lookback=20):
    c=closes(rows)
    return len(c)>=lookback+1 and c[-1] < min(c[-lookback-1:-1])
def recovery_confirmed(rows, lookback=20):
    c=closes(rows)
    return len(c)>=lookback+1 and c[-1] > max(c[-lookback-1:-1])

def summarize(data_dir="DATA"):
    d=Path(data_dir); m1=load_recent(d/"ohlc_M1.csv"); m5=load_recent(d/"ohlc_M5.csv"); m15=load_recent(d/"ohlc_M15.csv"); h1=load_recent(d/"ohlc_H1.csv"); d1=load_recent(d/"ohlc_D1.csv")
    br=build_hour_scenarios(
        d1_bearish=bearish(d1) if d1 else bearish(h1) if h1 else bearish(m15),
        m15_bearish=bearish(m15), m5_bearish=bearish(m5),
        support_holds=support_holds(m1), breakout_confirmed=breakout_confirmed(m5),
        recovery_confirmed=recovery_confirmed(m5), extended_impulse=bearish(m1,10))
    return {"data_quality":{"M1":len(m1),"M5":len(m5),"M15":len(m15),"H1":len(h1),"D1":len(d1)},"latest":{"M1":m1[-1] if m1 else None,"M5":m5[-1] if m5 else None,"M15":m15[-1] if m15 else None},"scenarios":[s.to_dict() for s in br],"decision":"WAIT" if not m1 or not m5 else max(br,key=lambda x:x.score).direction}

if __name__=="__main__": print(json.dumps(summarize(),indent=2,ensure_ascii=False))
