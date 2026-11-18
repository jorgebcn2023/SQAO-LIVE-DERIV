"""Conservative regime labels from independent diagnostics."""
def classify(vr, hurst_dfa, runs_p, min_n=500):
    if min_n < 1: raise ValueError("min_n must be positive")
    if not vr or vr.get("n",0)<min_n or vr.get("status")!="OK": return {"regime":"INSUFFICIENT_EVIDENCE","confidence":"LOW"}
    h=hurst_dfa.get("estimate") if hurst_dfa else None; z=vr.get("z_hetero")
    if h is None or z is None or runs_p is None: return {"regime":"INDETERMINATE","confidence":"LOW"}
    if abs(z)<1.96 or runs_p<0.05 and abs(z)<2.0: return {"regime":"INDETERMINATE","confidence":"LOW"}
    if z>1.96 and h>0.55: return {"regime":"PERSISTENCE_CANDIDATE","confidence":"MEDIUM"}
    if z<-1.96 and h<0.45: return {"regime":"MEAN_REVERSION_CANDIDATE","confidence":"MEDIUM"}
    return {"regime":"MIXED_OR_UNCONFIRMED","confidence":"LOW"}
