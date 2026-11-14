"""SQAO V2.5 — fail-closed MTF synchronization gate.

Checks that every uploaded timeframe has a corresponding quantitative closed-candle
timestamp and that each frame is fresh relative to one common snapshot timestamp.
This is a data-quality gate, not a directional signal or probability model.
"""
from __future__ import annotations
from datetime import datetime, timezone
import math
import time
from typing import Any

VERSION = "2.5.0"
TIMEFRAME_SECONDS = {"D1": 86400, "H4": 14400, "H1": 3600, "M15": 900, "M5": 300, "M1": 60}
DEFAULT_REQUIRED = ("D1", "H4", "H1", "M15", "M5", "M1")


def _epoch(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = float(value)
        if math.isfinite(number) and number > 0:
            return int(number)
    except (TypeError, ValueError, OverflowError):
        pass
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            return None
    return None


def _frame_epoch(frame: Any) -> int | None:
    if not isinstance(frame, dict):
        return None
    for key in ("last_closed_epoch", "latest_candle_epoch", "latest_epoch",
                "last_closed_timestamp", "timestamp", "epoch", "latest_candle_utc"):
        value = _epoch(frame.get(key))
        if value is not None:
            return value
    latest = frame.get("latest")
    if isinstance(latest, dict):
        for key in ("epoch", "timestamp", "time"):
            value = _epoch(latest.get(key))
            if value is not None:
                return value
    return None


def audit_mtf_synchronization(
    market_snapshot: dict[str, Any] | None,
    *,
    expected_timeframes: tuple[str, ...] | list[str] | None = None,
    now_epoch: int | None = None,
    max_age_bars: float = 2.0,
) -> dict[str, Any]:
    """Audit frame availability/freshness against a shared snapshot timestamp."""
    snapshot = market_snapshot if isinstance(market_snapshot, dict) else {}
    frames = snapshot.get("timeframes")
    frames = frames if isinstance(frames, dict) else {}
    required = tuple(tf.upper() for tf in (expected_timeframes or DEFAULT_REQUIRED)
                     if tf.upper() in TIMEFRAME_SECONDS)
    as_of = None
    for key in ("as_of_epoch", "generated_at_epoch", "generated_at_utc", "generated_at", "timestamp"):
        as_of = _epoch(snapshot.get(key))
        if as_of is not None:
            break
    reference = as_of if as_of is not None else (int(now_epoch) if now_epoch is not None else int(time.time()))
    results: dict[str, Any] = {}
    blockers: list[str] = []
    for tf in required:
        frame = frames.get(tf)
        if not isinstance(frame, dict):
            results[tf] = {"status": "MISSING_QUANT_FRAME", "epoch": None, "age_seconds": None}
            blockers.append(f"{tf}:MISSING_QUANT_FRAME")
            continue
        epoch = _frame_epoch(frame)
        if epoch is None or as_of is None:
            status = "UNVERIFIABLE_TIMESTAMP"
            age = None if epoch is None else reference - epoch
            blockers.append(f"{tf}:{status}")
        else:
            age = as_of - epoch
            max_age = int(TIMEFRAME_SECONDS[tf] * max_age_bars)
            if age < -TIMEFRAME_SECONDS[tf]:
                status = "FUTURE_CANDLE_TIMESTAMP"
                blockers.append(f"{tf}:{status}")
            elif age > max_age:
                status = "STALE"
                blockers.append(f"{tf}:{status}")
            elif age < 0:
                status = "CLOCK_SKEW"
                blockers.append(f"{tf}:{status}")
            else:
                status = "FRESH"
        results[tf] = {"status": status, "epoch": epoch, "age_seconds": age,
                       "max_age_seconds": int(TIMEFRAME_SECONDS[tf] * max_age_bars)}
    passed = bool(required) and not blockers and all(results[tf]["status"] == "FRESH" for tf in required)
    return {
        "version": VERSION, "gate": "MTF_SYNCHRONIZATION",
        "status": "PASS" if passed else "BLOCKED",
        "decision_override": None if passed else "NO_TRADE",
        "as_of_epoch": as_of,
        "as_of_utc": datetime.fromtimestamp(as_of, timezone.utc).isoformat() if as_of else None,
        "required_timeframes": list(required), "frames": results, "blockers": blockers,
        "policy": "Requires a common quantitative snapshot timestamp and fresh, timestamped closed candles for every required timeframe. Screenshot axis labels do not satisfy this gate and are never converted into OHLC.",
    }
