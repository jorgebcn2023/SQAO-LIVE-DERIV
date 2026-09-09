from __future__ import annotations
import asyncio, json, os, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import websockets
from .synthetic_scanner import family

PUBLIC_WS=os.getenv('DERIV_PUBLIC_WS','wss://api.derivws.com/trading/v1/options/ws/public')
G={'M1':60,'M5':300,'M15':900,'H1':3600,'D1':86400}

def ema(x,p):
    if len(x)<p:return None
    v=sum(x[:p])/p;k=2/(p+1)
    for a in x[p:]:v=a*k+v*(1-k)
    return v

def atr(rows,p=14):
    if len(rows)<p+1:return None
    tr=[]
    for i in range(1,len(rows)):
        h,l,c,pc=map(float,(rows[i]['high'],rows[i]['low'],rows[i]['close'],rows[i-1]['close']))
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(tr[-p:])/p

def signal(rows):
    c=[float(r['close']) for r in rows]
    if len(c)<30:return None
    e10,e20=ema(c,10),ema(c,20)
    if e10 is None or e20 is None:return None
    hi=max(c[-21:-1]);lo=min(c[-21:-1])
    if c[-1]>hi and e10>e20:return 'LONG'
    if c[-1]<lo and e10<e20:return 'SHORT'
    return None

def simulate(rows,horizon=5,rr=1.0,atr_mult=1.0):
    rs=[];i=30
    while i<len(rows)-horizon:
        hist=rows[:i+1];s=signal(hist);a=atr(hist)
        if not s or not a or a<=0:i+=1;continue
        entry=float(rows[i]['close']); stop=a*atr_mult; target=stop*rr; outcome=None
        for j in range(i+1,min(len(rows),i+horizon+1)):
            h,l=float(rows[j]['high']),float(rows[j]['low'])
            if s=='LONG': hit_stop=l<=entry-stop;hit_tp=h>=entry+target
            else: hit_stop=h>=entry+stop;hit_tp=l<=entry-target
            if hit_stop and hit_tp: outcome=-1.0
            elif hit_stop: outcome=-1.0
            elif hit_tp: outcome=rr
            if outcome is not None:break
        if outcome is None:
            final=float(rows[min(len(rows)-1,i+horizon)] ['close']);ret=(final-entry)/stop
            outcome=max(-1.0,min(rr,ret if s=='LONG' else -ret))
        rs.append(outcome);i+=1
    return rs

def metrics(rs):
    if not rs:return {'trades':0,'wins':0,'losses':0,'flats':0,'win_rate':None,'avg_r':None,'expectancy_r':None,'profit_factor':None,'max_drawdown_r':None,'sharpe':None,'sortino':None}
    wins=sum(x>0 for x in rs);losses=sum(x<0 for x in rs);flats=len(rs)-wins-losses
    gross_win=sum(x for x in rs if x>0);gross_loss=-sum(x for x in rs if x<0)
    eq=peak=dd=0
    for x in rs:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
    mean=sum(rs)/len(rs);sd=(sum((x-mean)**2 for x in rs)/max(1,len(rs)-1))**0.5
    neg=[x for x in rs if x<0];down=(sum(x*x for x in neg)/max(1,len(neg)))**0.5
    return {'trades':len(rs),'wins':wins,'losses':losses,'flats':flats,'win_rate':wins/max(1,wins+losses),'avg_r':mean,'expectancy_r':mean,'profit_factor':(gross_win/gross_loss if gross_loss else None),'max_drawdown_r':dd,'sharpe':(mean/sd*math.sqrt(len(rs)) if sd else None),'sortino':(mean/down*math.sqrt(len(rs)) if down else None)}

def walk_forward(rows,segments=5,**kwargs):
    n=len(rows);vals=[]
    for k in range(segments):
        a=int(n*k/segments);b=int(n*(k+1)/segments);seg=rows[a:b]
        if len(seg)<80:continue
        test=seg[int(len(seg)*0.7):]
        r=simulate(test,**kwargs);m=metrics(r)
        if m['trades']:vals.append(m['expectancy_r'])
    return sum(vals)/len(vals) if vals else None

def final_score(s):
    e=s['expectancy_r'] or -1; pf=s['profit_factor'] or 0; dd=s['max_drawdown_r'] or 99; wf=s['walk_forward_expectancy_r']
    base=50+min(30,max(-30,e*60))+min(15,max(-15,(pf-1)*12))-min(20,dd*1.5)+min(15,max(-15,(wf or -0.5)*45))
    return max(0,min(100,base))

async def req(ws,payload):
    await ws.send(json.dumps(payload));rid=payload.get('req_id')
    while True:
        m=json.loads(await ws.recv())
        if m.get('error'):raise RuntimeError(m['error'].get('message','Deriv API error'))
        if m.get('req_id')==rid:return m

async def active_symbols():
    async with websockets.connect(PUBLIC_WS,ping_interval=20,ping_timeout=20,open_timeout=15) as ws:
        m=await req(ws,{'active_symbols':'brief','product_type':'basic','req_id':1})
    out=[]
    for x in m.get('active_symbols',[]):
        sym=str(x.get('symbol',x.get('underlying_symbol','')));name=str(x.get('display_name',x.get('underlying_symbol_name','')))
        f=family(name+' '+sym)
        if sym and f!='OTHER_SYNTHETIC':out.append({'symbol':sym,'display_name':name,'family':f})
    return out

async def history(symbol,tf,count):
    async with websockets.connect(PUBLIC_WS,ping_interval=20,ping_timeout=20,open_timeout=15) as ws:
        m=await req(ws,{'ticks_history':symbol,'end':'latest','count':count,'style':'candles','granularity':G[tf],'adjust_start_time':1,'subscribe':0,'req_id':2})
    return m.get('candles',[])

async def research_symbol(item,count=2500,timeframe='M5',horizon=5,rr=1.0,atr_mult=1.0):
    rows=await history(item['symbol'],timeframe,count);rs=simulate(rows,horizon=horizon,rr=rr,atr_mult=atr_mult);m=metrics(rs);wf=walk_forward(rows,horizon=horizon,rr=rr,atr_mult=atr_mult);m.update({'walk_forward_expectancy_r':wf,'symbol':item['symbol'],'family':item['family'],'timeframe':timeframe,'confidence':min(100,20+5*math.log1p(m['trades']) if m['trades'] else 0)});m['score']=final_score(m);return m

async def run(limit=None,count=2500,timeframe='M5'):
    syms=await active_symbols()
    if limit:syms=syms[:limit]
    sem=asyncio.Semaphore(int(os.getenv('SQAO_RESEARCH_CONCURRENCY','4')))
    async def one(x):
        async with sem:
            try:return await research_symbol(x,count=count,timeframe=timeframe)
            except Exception as e:return {'symbol':x['symbol'],'family':x['family'],'error':str(e),'score':0}
    out=await asyncio.gather(*(one(x) for x in syms));out=sorted(out,key=lambda x:x.get('score',0),reverse=True)
    for i,x in enumerate(out,1):x['rank']=i
    return {'generated_at_utc':datetime.now(timezone.utc).isoformat(),'model':'walk_forward_risk_adjusted','count_scanned':len(syms),'results':out,'warning':'Historical diagnostic only; no guarantee of future performance. Conservative same-candle stop/target handling.'}

if __name__=='__main__':
    data=asyncio.run(run(limit=int(os.getenv('SQAO_RESEARCH_LIMIT','0')) or None,count=int(os.getenv('SQAO_RESEARCH_CANDLES','2500')),timeframe=os.getenv('SQAO_RESEARCH_TF','M5')))
    out=Path(os.getenv('SQAO_DATA_DIR','DATA'));out.mkdir(parents=True,exist_ok=True);(out/'synthetic_research.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(data,ensure_ascii=False,indent=2))
