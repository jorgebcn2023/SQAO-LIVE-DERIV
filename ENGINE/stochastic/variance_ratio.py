"""Lo-MacKinlay style variance ratio with heteroskedasticity-robust asymptotic variance."""
import math
def variance_ratio(returns, q=2):
    x=[float(v) for v in returns]; n=len(x)
    if q<2 or n<=q+1: raise ValueError("need q>=2 and n>q+1")
    mu=sum(x)/n; demean=[v-mu for v in x]; m2=sum(v*v for v in demean)/(n-1)
    if m2<=0: return {"q":q,"n":n,"vr":None,"z_homo":None,"z_hetero":None,"status":"ZERO_VARIANCE"}
    agg=[sum(demean[i-q+1:i+1]) for i in range(q-1,n)]; var_q=sum(v*v for v in agg)/(q*(n-q+1)); vr=var_q/m2
    phi=2*(2*q-1)*(q-1)/(3*q*n); z_homo=(vr-1)/math.sqrt(phi); delta=[]
    for j in range(1,q):
        cross=sum((demean[t]**2)*(demean[t-j]**2) for t in range(j,n)); denom=(sum(v*v for v in demean)**2)
        delta.append((n*cross/denom) if denom else 0.0)
    theta=(4.0/q**2)*sum(((1-j/q)**2)*delta[j-1] for j in range(1,q)); z_hetero=(vr-1)/math.sqrt(theta) if theta>0 else None
    return {"q":q,"n":n,"vr":vr,"z_homo":z_homo,"z_hetero":z_hetero,"robust_variance":theta,"status":"OK","interpretation":"VR>1 consistent with positive serial dependence; VR<1 consistent with mean reversion; not a standalone trading signal.","caveat":"Asymptotic statistic; overlapping-return construction and finite-sample behavior require bootstrap confirmation."}
