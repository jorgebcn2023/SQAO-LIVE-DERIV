from .quant import atr, win_rate, profit_factor
from .predictive import build_hour_scenarios
assert atr([2,3,4,5],[1,2,3,4],[1.5,2.5,3.5,4.5],period=2) is not None
assert round(win_rate([1,-1,1]),6)==round(2/3,6)
assert profit_factor([1,-1,2])==3.0
sc=build_hour_scenarios(True,True,True)
assert len(sc)==3
assert abs(sum(x.score for x in sc)-100.0)<0.2
print("SQAO tests: OK")
