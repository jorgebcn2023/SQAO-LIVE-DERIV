"""Conservative out-of-sample scalping evaluation for Step Index OHLC CSV.

CSV columns: timestamp,open,high,low,close (ascending, UTC).
No live order placement. Decisions are NO_TRADE unless test evidence qualifies.
"""
import argparse
import csv
import json
import math
from statistics import mean

def ema(values, period):
    out = []
    v = None
    a = 2 / (period + 1)
    for x in values:
        v = x if v is None else a * x + (1-a) * v
        out.append(v)
    return out

def wilson_lower(wins, n, z=1.96):
    if not n:
        return 0.0
    p = wins / n
    return (p + z*z/(2*n) - z*math.sqrt((p*(1-p)+z*z/(4*n))/n))/(1+z*z/n)

def backtest(rows, start, stop, rr=1.5, cost_r=0.05):
    closes = [r['close'] for r in rows]
    fast, slow = ema(closes, 10), ema(closes, 30)
    trades = []
    i = max(31, start)
    while i < min(stop, len(rows)-6):
        direction = 1 if fast[i-1] > slow[i-1] and closes[i-1] > max(closes[i-21:i-1]) else (-1 if fast[i-1] < slow[i-1] and closes[i-1] < min(closes[i-21:i-1]) else 0)
        if not direction:
            i += 1
            continue
        # Signals use only bars completed before the entry bar.
        atr = mean([max(rows[j]['high']-rows[j]['low'], abs(rows[j]['high']-closes[j-1]), abs(rows[j]['low']-closes[j-1])) for j in range(i-14,i)])
        if atr <= 0:
            i += 1
            continue
        entry = rows[i]['open']
        stop = entry-direction*atr
        target = entry+direction*atr*rr
        outcome = None
        last = min(i+5, stop-1) if False else min(i+5, len(rows)-1, stop_index_placeholder(stop, rows))
        for j in range(i,last+1):
            lo,hi = rows[j]['low'],rows[j]['high']
            hit_stop = lo <= stop if direction == 1 else hi >= stop
            hit_target = hi >= target if direction == 1 else lo <= target
            if hit_stop:
                outcome = -1.0
                break
            if hit_target:
                outcome = rr
                break
        if outcome is None:
            outcome = direction*(rows[last]['close']-entry)/atr
            j = last
        trades.append(outcome-cost_r)
        i = j+1
    return trades

def stop_index_placeholder(stop, rows):
    return len(rows)-1

def metrics(trades):
    n=len(trades)
    wins=sum(t>0 for t in trades)
    gross_profit=sum(max(0,t) for t in trades)
    gross_loss=-sum(min(0,t) for t in trades)
    equity=peak=drawdown=0.0
    for t in trades:
        equity+=t
        peak=max(peak,equity)
        drawdown=max(drawdown,peak-equity)
    return dict(trades=n, wins=wins, win_rate=wins/n if n else None,
                wilson_lower_95=wilson_lower(wins,n), expectancy_r=mean(trades) if n else None,
                profit_factor=gross_profit/gross_loss if gross_loss else None,
                max_drawdown_r=drawdown)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('csv_path')
    p.add_argument('--min-trades',type=int,default=100)
    p.add_argument('--cost-r',type=float,default=0.05)
    a=p.parse_args()
    with open(a.csv_path,newline='') as f:
        rows=[{k:float(v) if k!='timestamp' else v for k,v in row.items()} for row in csv.DictReader(f)]
    if len(rows)<300:
        raise SystemExit('At least 300 chronological OHLC bars required')
    split=int(len(rows)*0.7)
    train=metrics(backtest(rows,31,split,cost_r=a.cost_r))
    test=metrics(backtest(rows,split,len(rows),cost_r=a.cost_r))
    qualified=(test['trades']>=a.min_trades and test['wilson_lower_95']>=0.70
               and test['expectancy_r'] is not None and test['expectancy_r']>0
               and test['profit_factor'] is not None and test['profit_factor']>1)
    print(json.dumps(dict(symbol='Step Index (verify CSV provenance)',train=train,
                          out_of_sample=test,decision='RESEARCH_PASS' if qualified else 'NO_TRADE',
                          note='Historical results are not future probabilities. No live signal.'),indent=2))

if __name__=='__main__':
    main()
