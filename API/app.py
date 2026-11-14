from __future__ import annotations

import asyncio
import json
import math
import os
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets
from fastapi import FastAPI, Header, HTTPException, Query

from ENGINE.live_pipeline import timeframe_snapshot

DERIV_WS = os.getenv("DERIV_PUBLIC_WS", "wss://api.derivws.com/trading/v1/options/ws/public")
API_KEY = os.getenv("SQAO_ACTION_KEY", "").strip()
TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")
GRANULARITY = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
RUN_CONNECTOR = os.getenv("SQAO_RUN_CONNECTOR", "true").strip().lower() in {"1", "true", "yes", "on"}
DATA_DIR = Path(os.getenv("SQAO_DATA_DIR", "DATA"))

app = FastAPI(title="SQAO Live API", version="2.4.4-rc1", docs_url="/docs", redoc_url="/redoc")
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
    timeframe: str = Query(default="M1", pattern="^(M1|M5|M15|H1|H4|D1)$"),
    count: int = Query(default=500, ge=20, le=500),
    x_sqao_key: str | None = Header(default=None, alias="X-SQAO-Key"),
):
    _check_auth(x_sqao_key)
    resolved, mode = await _resolve_symbol(symbol)
    raw_candles = await _candles(resolved, timeframe, count)
    candles = _closed_candles(raw_candles, timeframe)
    if not candles:
        raise HTTPException(status_code=502, detail=f"No completed valid candles returned for {resolved} {timeframe}")
    return {
        "symbol": resolved,
        "symbol_resolution": mode,
        "timeframe": timeframe,
        "granularity_seconds": GRANULARITY[timeframe],
        "count": len(candles),
        "latest_closed_epoch": candles[-1]["epoch"],
        "latest_closed_utc": datetime.fromtimestamp(candles[-1]["epoch"], timezone.utc).isoformat(),
        "candles": candles,
        "source": "Deriv public market data",
        "read_only": True,
    }


def _closed_candles(candles: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    """Normalize, deduplicate and retain only valid fully closed Deriv candles."""
    now = int(datetime.now(timezone.utc).timestamp())
    granularity = GRANULARITY[timeframe]
    unique: dict[int, dict[str, Any]] = {}
    for candle in candles:
        try:
            epoch = int(candle["epoch"])
            values = {key: float(candle[key]) for key in ("open", "high", "low", "close")}
            if epoch + granularity > now:
                continue
            if not all(math.isfinite(value) for value in values.values()):
                continue
            if values["high"] < max(values["open"], values["close"], values["low"]):
                continue
            if values["low"] > min(values["open"], values["close"], values["high"]):
                continue
            unique[epoch] = {"epoch": epoch, **values}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [unique[epoch] for epoch in sorted(unique)]


async def _current_m1_open(symbol: str) -> dict[str, Any] | None:
    """Read only the forming M1 candle open for exact next-bar matching."""
    data = await _deriv_request({
        "ticks_history": symbol,
        "end": "latest",
        "count": 1,
        "style": "candles",
        "granularity": GRANULARITY["M1"],
        "req_id": 19001,
    })
    rows = data.get("candles", []) or []
    if not rows:
        return None
    try:
        row = rows[-1]
        epoch = int(row["epoch"])
        price = float(row["open"])
        now = int(datetime.now(timezone.utc).timestamp())
        if not __import__("math").isfinite(price) or price <= 0 or not (epoch <= now < epoch + 60):
            return None
        return {"epoch": epoch, "open": price, "source": "Deriv current M1 candle open"}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _frame_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [{key: str(value) for key, value in row.items()} for row in rows]
    return timeframe_snapshot(normalized)


@app.get("/analysis/snapshot")
async def analysis_snapshot(
    symbol: str = Query(default="AUTO", description="Deriv Step Index symbol; AUTO autodetects an active Step Index"),
    count: int = Query(default=500, ge=20, le=500),
    x_sqao_key: str | None = Header(default=None, alias="X-SQAO-Key"),
):
    _check_auth(x_sqao_key)
    from ENGINE.step_index_scalping_v23 import TF, detect, synchronize_frames

    resolved, mode = await _resolve_symbol(symbol)
    frames: dict[str, list[dict[str, Any]]] = {}
    for tf in TIMEFRAMES:
        raw = await _candles(resolved, tf, count)
        frames[tf] = _closed_candles(raw, tf)

    detector_frames = {tf: frames[tf] for tf in ("M1", "M5", "M15", "H1", "H4")}
    if frames["M1"]:
        decision_epoch = int(frames["M1"][-1]["epoch"]) + TF["M1"]
        aligned = synchronize_frames(detector_frames, decision_epoch)
        next_open = await _current_m1_open(resolved)
        setup = detect(aligned, next_open=next_open)
    else:
        decision_epoch = None
        aligned = {tf: [] for tf in detector_frames}
        next_open = None
        setup = {"state": "INSUFFICIENT_DATA", "confirmed": False}

    context = {tf: _frame_context(rows) for tf, rows in frames.items()}
    data_quality = {}
    for tf, rows in frames.items():
        epochs = [int(row["epoch"]) for row in rows]
        gaps = [(b - a) // GRANULARITY[tf] for a, b in zip(epochs, epochs[1:])
                if b - a > GRANULARITY[tf]]
        latest = epochs[-1] if epochs else None
        data_quality[tf] = {
            "requested": count,
            "received_closed": len(rows),
            "shortfall": max(0, count - len(rows)),
            "duplicate_epochs_removed": True,
            "gap_count": len(gaps),
            "max_gap_bars": max(gaps, default=1),
            "latest_closed_epoch": latest,
            "latest_closed_utc": datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest is not None else None,
        }

    # This endpoint is a research detector. Unverified all-in execution costs
    # block any validated or executable recommendation.
    return {
        "api_version": "2.4.4-rc1",
        "engine": "SQAO_STEP_INDEX_V23_CANONICAL",
        "symbol": resolved,
        "symbol_resolution": mode,
        "source": "Deriv public market data",
        "read_only": True,
        "decision": "NO_TRADE",
        "candidate_setup": setup,
        "candidate_confirmed": bool(setup.get("confirmed")),
        "execution_eligible": False,
        "cost_gate": "BLOCKED_MISSING_VERIFIABLE_ALL_IN_COST",
        "decision_epoch": decision_epoch,
        "next_m1_open": next_open,
        "data_complete": all(len(aligned[tf]) >= required for tf, required in
                             {"M1": 40, "M5": 40, "M15": 30, "H1": 30, "H4": 30}.items()),
        "data_quality": data_quality,
        "timeframes": context,
        "candles": frames,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Canonical v23 trigger is research-only. NO_TRADE is enforced until all-in costs and out-of-sample eligibility are independently verified.",
    }
