from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .predictive import build_hour_scenarios

TIMEFRAMES = ("D1", "H1", "M15", "M5", "M1")


def load_recent(path: str | Path, limit: int = 200) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))[-limit:]


def closes(rows: list[dict[str, str]]) -> list[float]:
    out: list[float] = []
    for row in rows:
        try:
            out.append(float(row["close"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def ohlc(rows: list[dict[str, str]]) -> tuple[list[float], list[float], list[float], list[float]]:
    op, hi, lo, cl = [], [], [], []
    for r in rows:
        try:
            op.append(float(r["open"])); hi.append(float(r["high"])); lo.append(float(r["low"])); cl.append(float(r["close"]))
        except (KeyError, TypeError, ValueError):
            continue
    return op, hi, lo, cl


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for x in values[period:]:
        value = x * k + value * (1.0 - k)
    return value


def atr_value(rows: list[dict[str, str]], period: int = 14) -> float | None:
    _, highs, lows, cs = ohlc(rows)
    if len(cs) < period + 1:
        return None
    trs = []
    for i in range(1, len(cs)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - cs[i - 1]), abs(lows[i] - cs[i - 1])))
    return sum(trs[-period:]) / period


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains = []; losses = []
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        d = b - a
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def direction(rows: list[dict[str, str]], fast_period: int = 10, slow_period: int = 20) -> str:
    c = closes(rows)
    fast = ema(c, fast_period); slow = ema(c, slow_period)
    if fast is None or slow is None:
        return "UNKNOWN"
    return "BULLISH" if fast > slow else "BEARISH" if fast < slow else "NEUTRAL"


def bearish(rows: list[dict[str, str]], lookback: int = 20) -> bool:
    c = closes(rows)
    return len(c) >= lookback and c[-1] < c[-lookback]


def bullish(rows: list[dict[str, str]], lookback: int = 20) -> bool:
    c = closes(rows)
    return len(c) >= lookback and c[-1] > c[-lookback]


def support_holds(rows: list[dict[str, str]], lookback: int = 20, tolerance: float = 0.0005) -> bool:
    c = closes(rows)
    if len(c) < lookback:
        return False
    lo = min(c[-lookback:])
    return c[-1] <= lo * (1.0 + tolerance)


def breakout_confirmed(rows: list[dict[str, str]], lookback: int = 20) -> bool:
    c = closes(rows)
    return len(c) >= lookback + 1 and c[-1] < min(c[-lookback - 1:-1])


def recovery_confirmed(rows: list[dict[str, str]], lookback: int = 20) -> bool:
    c = closes(rows)
    return len(c) >= lookback + 1 and c[-1] > max(c[-lookback - 1:-1])


def _epoch(row: dict[str, Any]) -> int | None:
    for key in ("timestamp", "epoch"):
        try:
            return int(float(row[key]))
        except (KeyError, TypeError, ValueError):
            pass
    return None


def timeframe_snapshot(rows: list[dict[str, str]]) -> dict[str, Any]:
    c = closes(rows)
    last = rows[-1] if rows else None
    latest_ts = _epoch(last) if last else None
    atr = atr_value(rows)
    e10 = ema(c, 10)
    e20 = ema(c, 20)
    return {
        "count": len(rows),
        "direction": direction(rows),
        "latest_close": c[-1] if c else None,
        "ema10": e10,
        "ema20": e20,
        "rsi14": rsi(c),
        "atr14": atr,
        "range20_high": max(c[-20:]) if len(c) >= 20 else None,
        "range20_low": min(c[-20:]) if len(c) >= 20 else None,
        "latest_candle_epoch": latest_ts,
        "latest_candle_utc": datetime.fromtimestamp(latest_ts, timezone.utc).isoformat() if latest_ts else None,
    }


def analyze_rows(frames: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    available = {tf: frames.get(tf, []) for tf in TIMEFRAMES}
    dirs = {tf: direction(available[tf]) for tf in TIMEFRAMES}
    valid_dirs = [d for d in dirs.values() if d in {"BULLISH", "BEARISH"}]
    bull_count = valid_dirs.count("BULLISH")
    bear_count = valid_dirs.count("BEARISH")
    complete = all(len(available[tf]) >= 20 for tf in TIMEFRAMES)

    m1 = available["M1"]; m5 = available["M5"]; m15 = available["M15"]
    br = build_hour_scenarios(
        d1_bearish=dirs["D1"] == "BEARISH",
        m15_bearish=dirs["M15"] == "BEARISH",
        m5_bearish=dirs["M5"] == "BEARISH",
        support_holds=support_holds(m1),
        breakout_confirmed=breakout_confirmed(m5),
        recovery_confirmed=recovery_confirmed(m5),
        extended_impulse=bearish(m1, 10),
    )
    best = max(br, key=lambda x: x.score) if br else None
    if not complete or not m1 or not m5:
        decision = "NO_TRADE"
    elif bull_count == len(valid_dirs) and len(valid_dirs) == 5 and recovery_confirmed(m5):
        decision = "LONG"
    elif bear_count == len(valid_dirs) and len(valid_dirs) == 5 and breakout_confirmed(m5):
        decision = "SHORT"
    else:
        decision = "WAIT"

    latest_epochs = [timeframe_snapshot(available[tf])["latest_candle_epoch"] for tf in TIMEFRAMES if available[tf]]
    newest = max((x for x in latest_epochs if x is not None), default=None)
    age = None
    if newest is not None:
        age = max(0, int(datetime.now(timezone.utc).timestamp()) - newest)

    return {
        "decision": decision,
        "decision_mode": "CONSERVATIVE_MTF",
        "model_estimate": True,
        "mtf_alignment": {"bullish": bull_count, "bearish": bear_count, "valid_timeframes": len(valid_dirs)},
        "data_complete": complete,
        "latest_data_age_seconds": age,
        "timeframes": {tf: timeframe_snapshot(available[tf]) for tf in TIMEFRAMES},
        "scenarios": [s.to_dict() for s in br],
        "decision_basis": best.to_dict() if best else None,
        "note": "MODEL_ESTIMATE only; no historical win rate, guarantee, spread, slippage or execution claim is inferred.",
    }


def summarize(data_dir: str = "DATA") -> dict[str, Any]:
    d = Path(data_dir)
    frames = {tf: load_recent(d / f"ohlc_{tf}.csv", 500) for tf in TIMEFRAMES}
    result = analyze_rows(frames)
    result["data_quality"] = {tf: len(frames[tf]) for tf in TIMEFRAMES}
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["latest"] = {tf: frames[tf][-1] if frames[tf] else None for tf in TIMEFRAMES}
    return result


if __name__ == "__main__":
    print(json.dumps(summarize(), indent=2, ensure_ascii=False))
