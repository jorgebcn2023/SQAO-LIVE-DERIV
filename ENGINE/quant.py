from __future__ import annotations
import math
import random
from statistics import mean

def true_range(high, low, prev_close):
    return max(high-low, abs(high-prev_close), abs(low-prev_close))

def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1: return None
    trs = [true_range(highs[i], lows[i], closes[i-1]) for i in range(1, len(closes))]
    return mean(trs[-period:])

def max_drawdown(r_multiples):
    equity = peak = 0.0
    dd = 0.0
    for r in r_multiples:
        equity += r; peak = max(peak, equity); dd = min(dd, equity-peak)
    return abs(dd)

def monte_carlo_bootstrap(r_multiples, iterations=5000, seed=42):
    if not r_multiples: return None
    rng = random.Random(seed); n = len(r_multiples); outcomes=[]
    for _ in range(iterations): outcomes.append(sum(rng.choice(r_multiples) for _ in range(n)))
    outcomes.sort(); return {"p05": outcomes[int(.05*len(outcomes))], "median": outcomes[int(.50*len(outcomes))], "p95": outcomes[int(.95*len(outcomes))-1]}

def win_rate(r_multiples):
    return None if not r_multiples else sum(x > 0 for x in r_multiples)/len(r_multiples)

def profit_factor(r_multiples):
    gains=sum(x for x in r_multiples if x>0); losses=-sum(x for x in r_multiples if x<0)
    return math.inf if losses==0 and gains>0 else (gains/losses if losses else None)
