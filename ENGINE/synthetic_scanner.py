from __future__ import annotations
import math,re
from typing import Any
from statistics import mean,pstdev

FAMILY_PROFILES={
 'STEP': {'safety':92,'modelability':92,'tail':8},
 'MULTI_STEP': {'safety':84,'modelability':88,'tail':18},
 'SKEW_STEP': {'safety':78,'modelability':91,'tail':25},
 'RANGE_BREAK': {'safety':86,'modelability':93,'tail':20},
 'DRIFT_SWITCHING': {'safety':85,'modelability':95,'tail':18},
 'TREK': {'safety':80,'modelability':90,'tail':25},
 'VOLATILITY': {'safety':72,'modelability':82,'tail':30},
 'CRASH_BOOM': {'safety':48,'modelability':78,'tail':65},
 'JUMP': {'safety':28,'modelability':72,'tail':90},
 'DEX': {'safety':42,'modelability':74,'tail':78},
 'DAILY_RESET': {'safety':72,'modelability':84,'tail':35},
 'HYBRID': {'safety':58,'modelability':80,'tail':55},
 'VOLATILITY_SWITCH': {'safety':58,'modelability':84,'tail':45},
 'OTHER_SYNTHETIC': {'safety':55,'modelability':70,'tail':50},
}

def family(name:str)->str:
 s=name.upper().replace('_',' ')
 if 'DRIFT' in s and 'SWITCH' in s:return 'DRIFT_SWITCHING'
 if 'RANGE BREAK' in s:return 'RANGE_BREAK'
 if 'MULTI STEP' in s:return 'MULTI_STEP'
 if 'SKEW STEP' in s:return 'SKEW_STEP'
 if re.search(r'\bSTEP\b',s) and 'MULTI' not in s and 'SKEW' not in s:return 'STEP'
 if 'CRASH' in s or 'BOOM' in s:return 'CRASH_BOOM'
 if 'JUMP' in s:return 'JUMP'
 if re.search(r'\bDEX\b',s):return 'DEX'
 if 'DAILY RESET' in s:return 'DAILY_RESET'
 if 'HYBRID' in s:return 'HYBRID'
 if 'VOLATILITY SWITCH' in s:return 'VOLATILITY_SWITCH'
 if 'TREK' in s:return 'TREK'
 if 'VOLATILITY' in s or re.search(r'\bVOL\s*\d',s):return 'VOLATILITY'
 return 'OTHER_SYNTHETIC'

def _f(x):
 try:return float(x)
 except:return None

def empirical(rows:list[dict[str,Any]])->dict[str,float|None]:
 c=[_f(r.get('close')) for r in rows];c=[x for x in c if x is not None]
 if len(c)<30:return {'trend':None,'vol':None,'momentum':None,'drawdown':None,'breakout':None}
 rets=[(c[i]/c[i-1]-1) for i in range(1,len(c)) if c[i-1]]
 vol=pstdev(rets)*100 if len(rets)>2 else 0
 trend=(c[-1]/c[max(0,len(c)-21)]-1)*100
 momentum=(c[-1]/c[max(0,len(c)-6)]-1)*100
 peak=c[0];dd=0
 for x in c:
  peak=max(peak,x);dd=max(dd,(peak-x)/peak*100 if peak else 0)
 look=c[-21:-1]
 breakout=0
 if look:
  hi=max(look);lo=min(look)
  breakout=100 if c[-1]>hi or c[-1]<lo else 0
 return {'trend':trend,'vol':vol,'momentum':momentum,'drawdown':dd,'breakout':breakout}

def score_symbol(name:str,frames:dict[str,list[dict[str,Any]]])->dict[str,Any]:
 fam=family(name);p=FAMILY_PROFILES[fam]
 stats={tf:empirical(rows) for tf,rows in frames.items()}
 dirs=[]
 for tf in ('D1','H1','M15','M5','M1'):
  t=stats.get(tf,{}).get('trend')
  dirs.append(1 if t is not None and t>0 else -1 if t is not None and t<0 else 0)
 aligned=max(sum(x==1 for x in dirs),sum(x==-1 for x in dirs))/max(1,len([x for x in dirs if x]))
 mtf=aligned*100
 m5=stats.get('M5',{});m15=stats.get('M15',{})
 setup=45 + 25*(m5.get('breakout') or 0)/100 + 20*(m15.get('breakout') or 0)/100
 if m5.get('trend') is not None and m15.get('trend') is not None and m5['trend']*m15['trend']>0: setup+=10
 setup=min(100,setup)
 observed_vol=mean([x['vol'] for x in stats.values() if x.get('vol') is not None]) if stats else None
 tail_penalty=min(25,(observed_vol or 0)*2)
 safety=max(0,min(100,p['safety']-tail_penalty*0.35))
 modelability=p['modelability']
 expectancy_proxy=max(0,min(100,45+0.35*(setup-50)+0.25*(mtf-50)+0.2*(modelability-50)-0.2*(p['tail'])))
 composite=0.30*safety+0.25*modelability+0.25*mtf+0.20*expectancy_proxy
 direction='LONG' if sum(dirs)>0 else 'SHORT' if sum(dirs)<0 else 'NEUTRAL'
 return {'family':fam,'direction':direction,'safety_score':round(safety,2),'modelability_score':modelability,'mtf_alignment_score':round(mtf,2),'setup_score':round(setup,2),'expectancy_proxy_score':round(expectancy_proxy,2),'composite_score':round(composite,2),'observed_volatility':round(observed_vol,6) if observed_vol is not None else None,'tail_risk_score':p['tail'],'timeframes':stats}

def rank(symbol_frames:dict[str,dict[str,list[dict[str,Any]]]],min_score:float=0)->list[dict[str,Any]]:
 out=[]
 for symbol,frames in symbol_frames.items():
  x=score_symbol(symbol,frames);x['symbol']=symbol
  if x['composite_score']>=min_score:out.append(x)
 out.sort(key=lambda x:x['composite_score'],reverse=True)
 for i,x in enumerate(out,1):x['rank']=i
 return out
