"""Wald-Wolfowitz runs test for signs, excluding exact zeros."""
import math
def runs_test(values):
    x=[float(v) for v in values if float(v)!=0.0]; n1=sum(v>0 for v in x); n2=sum(v<0 for v in x); n=n1+n2
    if n<2 or n1==0 or n2==0: return {"n":n,"positive":n1,"negative":n2,"runs":None,"z":None,"p_two_sided":None,"status":"INSUFFICIENT_SIGN_MIX"}
    runs=1+sum((x[i]>0)!=(x[i-1]>0) for i in range(1,n)); mu=1+2*n1*n2/n
    var=(2*n1*n2*(2*n1*n2-n))/(n*n*(n-1))
    if var<=0: return {"n":n,"positive":n1,"negative":n2,"runs":runs,"z":None,"p_two_sided":None,"status":"DEGENERATE"}
    z=(abs(runs-mu)-0.5)/math.sqrt(var); p=math.erfc(max(0.0,z)/math.sqrt(2))
    return {"n":n,"positive":n1,"negative":n2,"runs":runs,"expected_runs":mu,"z":z,"p_two_sided":p,"status":"OK","caveat":"Asymptotic normal approximation; dependent returns invalidate iid interpretation."}
