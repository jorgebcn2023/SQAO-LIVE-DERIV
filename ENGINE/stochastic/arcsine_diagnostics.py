"""Arcsine-law descriptive diagnostic for occupation time of a centered walk."""
def occupation_fraction(returns):
    x=[float(v) for v in returns]
    if len(x)<2: return {"fraction":None,"n":len(x),"status":"INSUFFICIENT_DATA"}
    mean=sum(x)/len(x); walk=0.0; positive=0
    for v in x:
        walk += v-mean
        positive += walk>0
    return {"fraction":positive/len(x),"n":len(x),"status":"OK",
            "reference":"For an ideal symmetric random walk, occupation fraction has an arcsine-type limit; compare via simulation, not a hard threshold.",
            "caveat":"Finite-sample, drift, volatility clustering and dependence alter the reference distribution."}
