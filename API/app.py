from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets
from fastapi import FastAPI, Header, HTTPException, Query

from ENGINE.live_pipeline import analyze_rows

DERIV_WS = os.getenv("DERIV_PUBLIC_WS", "wss://api.derivws.com/trading/v1/options/ws/public")
API_KEY = os.getenv("SQAO_ACTION_KEY", "").strip()
TIMEFRAMES = ("D1", "H1", "M15", "M5", "M1")
GRANULARITY = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "D1": 86400}
RUN_CONNECTOR = os.getenv("SQAO_RUN_CONNECTOR", "true").strip().lower() in {"1", "true", "yes", "on"}
DATA_DIR = Path(os.getenv("SQAO_DATA_DIR", "DATA"))

app = FastAPI(title="SQAO Live API", version="2.2.0", docs_url="/docs", redoc_url="/redoc")
_connector_task: asyncio.Task | None = None
_connector_started_at: str | None = None


async def _run_connector_background() -> None:
    """Keep the read-only tick/candle pipeline running alongside the API."""
    from CONNECTOR.deriv_live import run as run_live_connector

    await run_live_connector()


@app.on_event("startup")
async def start_background_connector() -> None:
    global _connector_task, _connector_started_at
    if RUN_CONNECTOR and _connector_task is None:
        _connector_started_at = datetime.now(timezone.utc).isoformat()
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


def _latest_data_status() -> dict[str, Any]:
    """Read only local connector data; never infer freshness from task state."""
    now = int(datetime.now(timezone.utc).timestamp())
    status: dict[str, Any] = {}
    max_age = int(os.getenv("SQAO_MAX_DATA_AGE_SECONDS", "180"))
    for timeframe, granularity in GRANULARITY.items():
        path = DATA_DIR / f"ohlc_{timeframe}.csv"
        latest_epoch = None
        rows = 0
        try:
            with path.open("r", encoding="utf-8") as handle:
                header = next(handle, "")
                for line in handle:
                    parts = line.strip().split(",")
                    if len(parts) >= 5:
                        try:
                            epoch = int(float(parts[0]))
                            float(parts[4])
                        except (ValueError, TypeError):
                            continue
                        latest_epoch = epoch if latest_epoch is None else max(latest_epoch, epoch)
                        rows += 1
        except (OSError, UnicodeError):
            pass

        age = max(0, now - latest_epoch) if latest_epoch is not None else None
        # CSV bars use their start timestamp; allow one full bar plus the
        # configured freshness window before calling the feed stale.
        fresh = age is not None and age <= max_age + granularity
        status[timeframe] = {
            "rows": rows,
            "latest_candle_epoch": latest_epoch,
            "age_seconds": age,
            "fresh": fresh,
        }
    return {
        "timeframes": status,
        "max_data_age_seconds": max_age,
        "all_timeframes_fresh": all(item["fresh"] for item in status.values()),
    }


@app.get("/health")
async def health():
    task_exists = _connector_task is not None
    task_running = task_exists and not _connector_task.done()
    task_error = None
    if task_exists and _connector_task.done():
        try:
            task_error = str(_connector_task.exception()) if not _connector_task.cancelled() else "cancelled"
        except Exception as exc:
            task_error = str(exc)

    freshness = _latest_data_status()
    connector_ok = (not RUN_CONNECTOR) or (task_running and freshness["all_timeframes_fresh"])
    return {
        "status": "ok" if connector_ok else "degraded",
        "service": "SQAO Live API",
        "version": "2.2.0",
        "read_only": True,
        "background_connector_enabled": RUN_CONNECTOR,
        "background_connector_running": bool(task_running),
        "background_connector_started_at_utc": _connector_started_at,
        "background_connector_error": task_error,
        "market_data": freshness,
    }


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
    if not candles:
        raise HTTPException(status_code=502, detail=f"No candles returned for {resolved} {timeframe}")
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
        if len(frames[tf]) < 20:
            raise HTTPException(
                status_code=502,
                detail=f"Insufficient candles for {tf}: received {len(frames[tf])}, expected at least 20",
            )
    analysis = analyze_rows({tf: [{k: str(v) for k, v in row.items()} for row in rows] for tf, rows in frames.items()})
    analysis["symbol"] = resolved
    analysis["symbol_resolution"] = mode
    analysis["source"] = "Deriv public market data"
    analysis["read_only"] = True
    analysis["candles"] = frames
    analysis["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    return analysis
