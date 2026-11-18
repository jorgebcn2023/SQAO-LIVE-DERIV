"""Rescaled-range Hurst estimate and DFA-1 estimate."""
import math, statistics
def hurst_rs(values, min_window=8):
    x=[float(v) for v in values]; n=len(x)
    sizes=sorted(set([min(n//k, n) for k in (16,8,4,2) if n//k>=min_window]))
    points=[]
    for w in sizes:
        rs=[]
        for start in range(0,n-w+1,w):
            seg=x[start:start+w]; m=statistics.mean(seg); dev=[]; acc=0.0
            for v in seg: acc += v-m; dev.append(acc)
            sd=statistics.stdev(seg)
            if sd>0: rs.append((max(dev)-min(dev))/sd)
        if rs and statistics.mean(rs)>0: points.append((math.log(w),math.log(statistics.mean(rs))))
    if len(points)<2: return {"estimate":None,"method":"R/S","status":"INSUFFICIENT_SCALES","scales":len(points)}
    mx=statistics.mean(a for a,b in points); my=statistics.mean(b for a,b in points)
    slope=sum((a-mx)*(b-my) for a,b in points)/sum((a-mx)**2 for a,b in points)
    return {"estimate":slope,"method":"R/S","status":"OK","scales":len(points),"caveat":"R/S can be biased by short-memory dependence, heavy tails and nonstationarity."}
def hurst_dfa(values, min_window=8):
    x=[float(v) for v in values]; n=len(x)
    if n<min_window*4: return {"estimate":None,"method":"DFA1","status":"INSUFFICIENT_DATA","scales":0}
    mu=statistics.mean(x); profile=[]; acc=0.0
    for v in x: acc += v-mu; profile.append(acc)
    sizes=sorted(set(int(2**p) for p in range(3,int(math.log2(n))+1) if 2**p<=n//2)); pts=[]
    for w in sizes:
        rms=[]
        for start in range(0,n-w+1,w):
            seg=profile[start:start+w]; sx=sum(range(w)); sy=sum(seg); sxx=sum(i*i for i in range(w)); sxy=sum(i*y for i,y in enumerate(seg))
            den=w*sxx-sx*sx
            if den==0: continue
            b=(w*sxy-sx*sy)/den; a=(sy-b*sx)/w
            err=sum((y-(a+b*i))**2 for i,y in enumerate(seg))/w
            rms.append(math.sqrt(err))
        if rms and statistics.mean(rms)>0: pts.append((math.log(w),math.log(statistics.mean(rms))))
    if len(pts)<2: return {"estimate":None,"method":"DFA1","status":"INSUFFICIENT_SCALES","scales":len(pts)}
    mx=statistics.mean(a for a,b in pts); my=statistics.mean(b for a,b in pts)
    slope=sum((a-mx)*(b-my) for a,b in pts)/sum((a-mx)**2 for a,b in pts)
    return {"estimate":slope,"method":"DFA1","status":"OK","scales":len(pts),"caveat":"DFA1 is a scaling diagnostic, not proof of long memory; choose scales before inspecting results."}
