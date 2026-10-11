from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from typing import Any

import websockets
from fastapi import FastAPI, Header, HTTPException, Query

from ENGINE.live_pipeline import analyze_rows

DERIV_WS = os.getenv("DERIV_PUBLIC_WS", "wss://api.derivws.com/trading/v1/options/ws/public")
API_KEY = os.getenv("SQAO_ACTION_KEY", "").strip()
TIMEFRAMES = ("D1", "H1", "M15", "M5", "M1")
GRANULARITY = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "D1": 86400}
RUN_CONNECTOR = os.getenv("SQAO_RUN_CONNECTOR", "true").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(title="SQAO Live API", version="2.1.0", docs_url="/docs", redoc_url="/redoc")
_connector_task: asyncio.Task | None = None


async def _run_connector_background() -> None:
    """Keep the read-only tick/candle pipeline running alongside the API."""
    from CONNECTOR.deriv_live import run as run_live_connector

    await run_live_connector()


@app.on_event("startup")
async def start_background_connector() -> None:
    global _connector_task
    if RUN_CONNECTOR and _connector_task is None:
        _connector_task = asyncio.create_task(_run_connector_background(), name="sqao-deriv-live-connector")


@app.on_event("shutdown")
async def stop_background_connector() -> None:
    global _connector_task
    if _connector_task is not None:
        _connector_task.cancel()
        with suppress(asyncio.CancelledError):
            await _connector_task
        _connector_task = None


def _auth_ok(key: str | None) -> bool:
    return not API_KEY or key == API_KEY


def _check_auth(key: str | None) -> None:
    if not _auth_ok(key):
        raise HTTPException(status_code=401, detail="Invalid SQAO API key")


async def _deriv_request(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        async with websockets.connect(DERIV_WS, open_timeout=12, close_timeout=5, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps(payload))
            while True:
                data = json.loads(await ws.recv())
                if data.get("error"):
                    error = data["error"]
                    raise HTTPException(status_code=502, detail=error.get("message", "Deriv error"))
                if payload.get("req_id") is None or data.get("req_id") == payload.get("req_id") or data.get("msg_type") in {"active_symbols", "candles", "history"}:
                    return data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Deriv public API unavailable: {exc}") from exc


async def _active_step_symbols() -> list[dict[str, str]]:
    data = await _deriv_request({"active_symbols": "brief", "req_id": 9001})
    symbols: list[dict[str, str]] = []
    for item in data.get("active_symbols", []):
        name = str(item.get("display_name", item.get("underlying_symbol_name", "")))
        symbol = str(item.get("symbol", item.get("underlying_symbol", "")))
        if "step index" in f"{name} {symbol}".lower() and symbol:
            symbols.append({"symbol": symbol, "display_name": name})
    return symbols


async def _resolve_symbol(symbol: str) -> tuple[str, str]:
    requested = symbol.strip()
    if requested and requested.upper() != "AUTO":
        return requested, "EXPLICIT"
    candidates = await _active_step_symbols()
    if not candidates:
        raise HTTPException(status_code=502, detail="No active Step Index symbol found")
    preferred = os.getenv("DERIV_STEP_NAME", "").strip().lower()
    if preferred:
        for item in candidates:
            if preferred == item["symbol"].lower() or preferred in item["display_name"].lower():
                return item["symbol"], "AUTO_PREFERRED"
    return candidates[0]["symbol"], "AUTO"


async def _candles(symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
    data = await _deriv_request({
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "start": 1,
        "style": "candles",
        "granularity": GRANULARITY[timeframe],
        "subscribe": 1,
        "req_id": 10000 + GRANULARITY[timeframe],
    })
    return data.get("candles", [])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "SQAO Live API",
        "version": "2.1.0",
        "read_only": True,
        "background_connector_enabled": RUN_CONNECTOR,
        "background_connector_running": _connector_task is not None and not _connector_task.done(),
    }


@app.get("/market/active-symbols")
async def active_symbols(x_sqao_key: str | None = Header(default=None, alias="X-SQAO-Key")):
    _check_auth(x_sqao_key)
    symbols = await _active_step_symbols()
    return {"symbols": symbols, "count": len(symbols), "source": "Deriv public market data"}


@app.get("/market/ohlc")
async def ohlc(
    symbol: str = Query(default="AUTO", description="Deriv Step Index symbol; AUTO resolves an active Step Index"),
    timeframe: str = Query(default="M1", pattern="^(M1|M5|M15|H1|D1)$"),
    count: int = Query(default=120, ge=20, le=500),
    x_sqao_key: str | None = Header(default=None, alias="X-SQAO-Key"),
):
    _check_auth(x_sqao_key)
    resolved, mode = await _resolve_symbol(symbol)
    candles = await _candles(resolved, timeframe, count)
    return {
        "symbol": resolved,
        "symbol_resolution": mode,
        "timeframe": timeframe,
        "granularity_seconds": GRANULARITY[timeframe],
        "count": len(candles),
        "candles": candles,
        "source": "Deriv public market data",
        "read_only": True,
    }


@app.get("/analysis/snapshot")
async def analysis_snapshot(
    symbol: str = Query(default="AUTO", description="Deriv Step Index symbol; AUTO autodetects an active Step Index"),
    count: int = Query(default=120, ge=20, le=500),
    x_sqao_key: str | None = Header(default=None, alias="X-SQAO-Key"),
):
    _check_auth(x_sqao_key)
    resolved, mode = await _resolve_symbol(symbol)
    frames: dict[str, list[dict[str, Any]]] = {}
    for tf in TIMEFRAMES:
        frames[tf] = await _candles(resolved, tf, count)
    analysis = analyze_rows({tf: [{k: str(v) for k, v in row.items()} for row in rows] for tf, rows in frames.items()})
    analysis["symbol"] = resolved
    analysis["symbol_resolution"] = mode
    analysis["source"] = "Deriv public market data"
    analysis["read_only"] = True
    analysis["candles"] = frames
    return analysis
