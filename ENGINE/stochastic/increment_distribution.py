"""Empirical return/increment distribution diagnostics."""
from __future__ import annotations
import math, statistics
def increments(prices, log=False):
    x=[float(v) for v in prices]
    if any(not math.isfinite(v) for v in x): raise ValueError("prices must be finite")
    if log and any(v <= 0 for v in x): raise ValueError("log returns require positive prices")
    if log: return [math.log(b/a) for a,b in zip(x,x[1:])]
    return [b-a for a,b in zip(x,x[1:])]
def describe(x):
    x=[float(v) for v in x]
    if len(x)<2: return {"n":len(x),"mean":None,"std":None,"skew":None,"excess_kurtosis":None,"zero_fraction":None}
    m=statistics.mean(x); s=statistics.stdev(x)
    if s == 0: skew=kurt=0.0
    else:
        z=[(v-m)/s for v in x]; n=len(z)
        skew=(n/((n-1)*(n-2)))*sum(v**3 for v in z) if n>2 else None
        kurt=(n*(n+1)/((n-1)*(n-2)*(n-3))*sum(v**4 for v in z)-3*(n-1)**2/((n-2)*(n-3))) if n>3 else None
    return {"n":len(x),"mean":m,"std":s,"skew":skew,"excess_kurtosis":kurt,"zero_fraction":sum(v==0 for v in x)/len(x)}
