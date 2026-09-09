"""READ-ONLY Deriv market-data connector for SQAO v2.3.

Uses Deriv's current public WebSocket endpoint. No trading calls are present.
"""
from __future__ import annotations
import asyncio, json, os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import websockets

PUBLIC_WS = "wss://api.derivws.com/trading/v1/options/ws/public"

@dataclass
class Candle:
    timestamp:int; open:float; high:float; low:float; close:float; timeframe:str
    def to_dict(self): return asdict(self)

class CandleAggregator:
    def __init__(self, timeframes=(1,5,15)):
        self.timeframes=tuple(timeframes); self.current={}
    @staticmethod
    def bucket(epoch, minutes):
        size=minutes*60; return epoch-(epoch%size)
    def update(self, epoch, price):
        emitted=[]
        for tf in self.timeframes:
            start=self.bucket(epoch,tf); c=self.current.get(tf)
            if c is None or c.timestamp != start:
                if c is not None: emitted.append(c)
                c=Candle(start,price,price,price,price,f"M{tf}"); self.current[tf]=c
            else:
                c.high=max(c.high,price); c.low=min(c.low,price); c.close=price
        return emitted

async def receive_matching(ws, req_id):
    while True:
        msg=json.loads(await ws.recv())
        if msg.get("error"):
            raise RuntimeError(msg["error"].get("message", str(msg["error"])))
        if msg.get("req_id") == req_id or msg.get("msg_type") in {"active_symbols","candles","history"}:
            return msg

async def autodetect_symbol(ws):
    req_id=1001
    await ws.send(json.dumps({"active_symbols":"brief","req_id":req_id}))
    msg=await receive_matching(ws,req_id)
    candidates=[]
    for item in msg.get("active_symbols",[]):
        name=str(item.get("underlying_symbol_name",item.get("display_name","")))
        symbol=str(item.get("underlying_symbol",item.get("symbol","")))
        if "step index" in f"{name} {symbol}".lower(): candidates.append((name,symbol))
    if not candidates: raise RuntimeError("No active Step Index symbol found")
    preferred=os.getenv("DERIV_STEP_NAME","").strip().lower()
    if preferred:
        for name,symbol in candidates:
            if preferred==symbol.lower() or preferred in name.lower(): return symbol
    return candidates[0][1]

async def seed_history(ws, symbol, output, count=500):
    for tf,granularity,label in ((1,60,"M1"),(5,300,"M5"),(15,900,"M15"),(60,3600,"H1"),(1440,86400,"D1")):
        req_id=1100+tf
        payload={"ticks_history":symbol,"end":"latest","count":count,"style":"candles","granularity":granularity,"adjust_start_time":1,"subscribe":0,"req_id":req_id}
        await ws.send(json.dumps(payload)); msg=await receive_matching(ws,req_id)
        candles=msg.get("candles",[])
        path=output/f"ohlc_{label}.csv"
        with path.open("w",encoding="utf-8") as f:
            f.write("timestamp,open,high,low,close,timeframe\n")
            for c in candles:
                f.write(f"{int(c['epoch'])},{float(c['open'])},{float(c['high'])},{float(c['low'])},{float(c['close'])},{label}\n")
    print(f"HISTORY_SEEDED symbol={symbol} count={count}")

async def run():
    symbol=os.getenv("DERIV_SYMBOL","AUTO"); output=Path(os.getenv("SQAO_DATA_DIR","DATA")); output.mkdir(parents=True,exist_ok=True)
    history_count=int(os.getenv("SQAO_HISTORY_CANDLES","500")); delay=1
    aggregator=CandleAggregator()
    while True:
        try:
            async with websockets.connect(PUBLIC_WS,ping_interval=20,ping_timeout=20) as ws:
                if symbol.upper()=="AUTO": symbol=await autodetect_symbol(ws); print(f"AUTO_SYMBOL={symbol}")
                await seed_history(ws,symbol,output,history_count)
                await ws.send(json.dumps({"ticks":symbol,"subscribe":1,"req_id":1}))
                print(f"CONNECTED symbol={symbol}"); delay=1
                async for raw in ws:
                    msg=json.loads(raw)
                    if msg.get("error"): raise RuntimeError(msg["error"].get("message",str(msg["error"])))
                    if msg.get("msg_type")!="tick": continue
                    tick=msg["tick"]; epoch=int(tick["epoch"]); price=float(tick["quote"])
                    with (output/"ticks.ndjson").open("a",encoding="utf-8") as f:
                        f.write(json.dumps({"timestamp":epoch,"price":price,"symbol":symbol})+"\n")
                    for candle in aggregator.update(epoch,price):
                        path=output/f"ohlc_{candle.timeframe}.csv"; new=not path.exists()
                        with path.open("a",encoding="utf-8") as f:
                            if new: f.write("timestamp,open,high,low,close,timeframe\n")
                            f.write(f"{candle.timestamp},{candle.open},{candle.high},{candle.low},{candle.close},{candle.timeframe}\n")
                    print(datetime.fromtimestamp(epoch,tz=timezone.utc).isoformat(),price,flush=True)
        except KeyboardInterrupt: return
        except Exception as exc:
            print(f"CONNECTOR_ERROR: {exc}; reconnecting in {delay}s",flush=True)
            await asyncio.sleep(delay); delay=min(delay*2,30)

if __name__=="__main__": asyncio.run(run())
