"""Seeded moving-block bootstrap of the empirical increment mean; not a price forecast."""
import random, statistics
def block_bootstrap(values, paths=2000, block=8, seed=20261118):
    x=[float(v) for v in values]
    if len(x)<block*3: raise ValueError("at least 3 blocks of observations are required")
    if paths<100 or block<1: raise ValueError("paths>=100 and block>=1 required")
    rng=random.Random(seed); n=len(x); out=[]
    for _ in range(paths):
        sample=[]
        while len(sample)<n:
            start=rng.randrange(0,n-block+1); sample.extend(x[start:start+block])
        sample=sample[:n]; out.append(sum(sample)/len(sample))
    ordered=sorted(out)
    def q(p): return ordered[min(len(ordered)-1,max(0,int(p*(len(ordered)-1))))]
    return {"paths":paths,"block":block,"seed":seed,"mean_distribution":{"p05":q(.05),"p50":q(.5),"p95":q(.95)},"sample_mean":statistics.mean(out),"status":"OK","caveat":"Moving-block bootstrap preserves only local dependence approximately; it is not a forecast of price."}
