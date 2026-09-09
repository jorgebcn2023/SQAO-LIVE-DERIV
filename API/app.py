import json
import os
from typing import Any

import websockets
from fastapi import FastAPI, Header, HTTPException, Query

DERIV_WS = os.getenv("DERIV_PUBLIC_WS", "wss://api.derivws.com/trading/v1/options/ws/public")
API_KEY = os.getenv("SQAO_ACTION_KEY", "")

app = FastAPI(title="SQAO Live API", version="1.0.0")


def _auth_ok(key: str | None) -> bool:
    return not API_KEY or key == API_KEY


async def _deriv_request(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        async with websockets.connect(DERIV_WS, open_timeout=10, close_timeout=5) as ws:
            await ws.send(json.dumps(payload))
            return json.loads(await ws.recv())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Deriv public API unavailable: {exc}") from exc


@app.get("/health")
async def health():
    return {"status": "ok", "service": "SQAO Live API", "version": "1.0.0"}


@app.get("/market/active-symbols")
async def active_symbols(x_sqao_key: str | None = Header(default=None, alias="X-SQAO-Key")):
    if not _auth_ok(x_sqao_key):
        raise HTTPException(status_code=401, detail="Invalid SQAO API key")
    data = await _deriv_request({"active_symbols": "brief", "product_type": "basic"})
    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"].get("message", "Deriv error"))
    symbols = []
    for item in data.get("active_symbols", []):
        name = str(item.get("display_name", ""))
        if "Step Index" in name:
            symbols.append({"symbol": item.get("symbol"), "display_name": name})
    return {"symbols": symbols}


@app.get("/market/ohlc")
async def ohlc(
    symbol: str = Query(default="stpRNG", description="Deriv Step Index symbol"),
    timeframe: str = Query(default="M1", pattern="^(M1|M5|M15|H1|D1)$"),
    count: int = Query(default=120, ge=10, le=500),
    x_sqao_key: str | None = Header(default=None, alias="X-SQAO-Key"),
):
    if not _auth_ok(x_sqao_key):
        raise HTTPException(status_code=401, detail="Invalid SQAO API key")
    granularity = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "D1": 86400}[timeframe]
    data = await _deriv_request({
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "start": 1,
        "style": "candles",
        "granularity": granularity,
    })
    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"].get("message", "Deriv error"))
    candles = data.get("candles", [])
    return {"symbol": symbol, "timeframe": timeframe, "granularity_seconds": granularity, "count": len(candles), "candles": candles, "source": "Deriv public market data"}


@app.get("/analysis/snapshot")
async def analysis_snapshot(
    symbol: str = Query(default="stpRNG"),
    x_sqao_key: str | None = Header(default=None, alias="X-SQAO-Key"),
):
    if not _auth_ok(x_sqao_key):
        raise HTTPException(status_code=401, detail="Invalid SQAO API key")
    result: dict[str, Any] = {"symbol": symbol, "source": "Deriv public market data", "timeframes": {}}
    for tf in ("D1", "H1", "M15", "M5", "M1"):
        data = await ohlc(symbol=symbol, timeframe=tf, count=120, x_sqao_key=x_sqao_key)
        candles = data["candles"]
        closes = [float(c["close"]) for c in candles if "close" in c]
        if len(closes) >= 20:
            fast = sum(closes[-10:]) / 10
            slow = sum(closes[-20:]) / 20
            direction = "BULLISH" if fast > slow else "BEARISH" if fast < slow else "NEUTRAL"
        else:
            direction = "UNKNOWN"
        result["timeframes"][tf] = {"direction_proxy": direction, "latest_close": closes[-1] if closes else None, "candles": candles}
    result["decision_note"] = "direction_proxy is a quantitative proxy, not a trading signal or historical win rate"
    return result
