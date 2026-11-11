from __future__ import annotations

import csv
import json
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
    out = []
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


def ema_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    result = [value]
    for x in values[period:]:
        value = x * k + value * (1.0 - k)
        result.append(value)
    return result


def ema(values: list[float], period: int) -> float | None:
    series = ema_series(values, period)
    return series[-1] if series else None


def macd(values: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict[str, float | str | None]:
    fast_s, slow_s = ema_series(values, fast), ema_series(values, slow)
    if not fast_s or not slow_s or len(values) < slow:
        return {"macd": None, "signal": None, "histogram": None, "state": "INSUFFICIENT_DATA"}
    # Align EMA series to the same candle indices; MACD begins when slow EMA is available.
    offset = slow - fast
    line = [fast_s[i + offset] - slow_s[i] for i in range(len(slow_s))]
    signal_s = ema_series(line, signal_period)
    if not signal_s:
        return {"macd": line[-1], "signal": None, "histogram": None, "state": "INSUFFICIENT_DATA"}
    current = line[-1]
    sig = signal_s[-1]
    hist = current - sig
    state = "BULLISH" if current > sig and hist > 0 else "BEARISH" if current < sig and hist < 0 else "NEUTRAL"
    return {"macd": current, "signal": sig, "histogram": hist, "state": state}


def bollinger(values: list[float], period: int = 20, deviations: float = 2.0) -> dict[str, float | str | None]:
    if len(values) < period:
        return {"middle": None, "upper": None, "lower": None, "bandwidth_pct": None, "position": "INSUFFICIENT_DATA"}
    window = values[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = variance ** 0.5
    upper, lower = middle + deviations * std, middle - deviations * std
    close = values[-1]
    bandwidth = ((upper - lower) / abs(middle) * 100.0) if middle else None
    if close > upper:
        position = "ABOVE_UPPER"
    elif close < lower:
        position = "BELOW_LOWER"
    elif close >= middle:
        position = "UPPER_HALF"
    else:
        position = "LOWER_HALF"
    return {"middle": middle, "upper": upper, "lower": lower, "bandwidth_pct": bandwidth, "position": position}


def atr_value(rows: list[dict[str, str]], period: int = 14) -> float | None:
    _, highs, lows, cs = ohlc(rows)
    if len(cs) < period + 1:
        return None
    trs = [max(highs[i] - lows[i], abs(highs[i] - cs[i - 1]), abs(lows[i] - cs[i - 1])) for i in range(1, len(cs))]
    return sum(trs[-period:]) / period


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    deltas = [b - a for a, b in zip(values[-period - 1:-1], values[-period:])]
    avg_gain = sum(max(d, 0.0) for d in deltas) / period
    avg_loss = sum(max(-d, 0.0) for d in deltas) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def direction(rows: list[dict[str, str]], fast_period: int = 10, slow_period: int = 20) -> str:
    c = closes(rows)
    fast, slow = ema(c, fast_period), ema(c, slow_period)
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
    _, _, lows, _ = ohlc(rows)
    c = closes(rows)
    if len(c) < lookback or len(lows) < lookback:
        return False
    floor = min(lows[-lookback:])
    return lows[-1] <= floor * (1.0 + tolerance) and c[-1] >= floor


def breakout_confirmed(rows: list[dict[str, str]], lookback: int = 20) -> bool:
    _, _, lows, c = ohlc(rows)
    return len(c) >= lookback + 1 and c[-1] < min(lows[-lookback - 1:-1])


def recovery_confirmed(rows: list[dict[str, str]], lookback: int = 20) -> bool:
    _, highs, _, c = ohlc(rows)
    return len(c) >= lookback + 1 and c[-1] > max(highs[-lookback - 1:-1])


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
    e10, e20 = ema(c, 10), ema(c, 20)
    macd_data = macd(c)
    bb = bollinger(c)
    return {
        "count": len(rows),
        "direction": direction(rows),
        "latest_close": c[-1] if c else None,
        "ema10": e10,
        "ema20": e20,
        "ema_cross_state": "BULLISH" if e10 is not None and e20 is not None and e10 > e20 else "BEARISH" if e10 is not None and e20 is not None and e10 < e20 else "UNKNOWN",
        "rsi14": rsi(c),
        "macd": macd_data,
        "bollinger20_2": bb,
        "atr14": atr,
        "range20_high": max(ohlc(rows)[1][-20:]) if len(c) >= 20 else None,
        "range20_low": min(ohlc(rows)[2][-20:]) if len(c) >= 20 else None,
        "latest_candle_epoch": latest_ts,
        "latest_candle_utc": datetime.fromtimestamp(latest_ts, timezone.utc).isoformat() if latest_ts else None,
    }


def analyze_rows(frames: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    available = {tf: frames.get(tf, []) for tf in TIMEFRAMES}
    snapshots = {tf: timeframe_snapshot(available[tf]) for tf in TIMEFRAMES}
    dirs = {tf: snapshots[tf]["direction"] for tf in TIMEFRAMES}
    valid_dirs = [d for d in dirs.values() if d in {"BULLISH", "BEARISH"}]
    bull_count, bear_count = valid_dirs.count("BULLISH"), valid_dirs.count("BEARISH")
    complete = all(len(available[tf]) >= 35 for tf in TIMEFRAMES)

    m1, m5, m15 = available["M1"], available["M5"], available["M15"]
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

    # Confirmation requires price structure plus MACD confirmation on M5, with M1 as timing only.
    m5_macd = snapshots["M5"]["macd"]["state"]
    m5_bb = snapshots["M5"]["bollinger20_2"]["position"]
    long_confirm = recovery_confirmed(m5) and m5_macd == "BULLISH" and m5_bb not in {"ABOVE_UPPER", "INSUFFICIENT_DATA"}
    short_confirm = breakout_confirmed(m5) and m5_macd == "BEARISH" and m5_bb not in {"BELOW_LOWER", "INSUFFICIENT_DATA"}

    if not complete or len(valid_dirs) != 5:
        decision = "NO_TRADE"
    elif bull_count == 5 and long_confirm:
        decision = "LONG"
    elif bear_count == 5 and short_confirm:
        decision = "SHORT"
    else:
        decision = "WAIT"

    epochs = [snapshots[tf]["latest_candle_epoch"] for tf in TIMEFRAMES if available[tf]]
    newest = max((x for x in epochs if x is not None), default=None)
    age = max(0, int(datetime.now(timezone.utc).timestamp()) - newest) if newest is not None else None
    indicator_alignment = {
        tf: {
            "ema": snapshots[tf]["ema_cross_state"],
            "macd": snapshots[tf]["macd"]["state"],
            "bollinger_position": snapshots[tf]["bollinger20_2"]["position"],
            "rsi14": snapshots[tf]["rsi14"],
        } for tf in TIMEFRAMES
    }
    return {
        "decision": decision,
        "decision_mode": "CONSERVATIVE_MTF_INDICATOR_CONFLUENCE",
        "model_estimate": True,
        "mtf_alignment": {"bullish": bull_count, "bearish": bear_count, "valid_timeframes": len(valid_dirs)},
        "indicator_alignment": indicator_alignment,
        "confirmation": {
            "m5_macd_state": m5_macd,
            "m5_bollinger_position": m5_bb,
            "long_structure_confirmed": recovery_confirmed(m5),
            "short_structure_confirmed": breakout_confirmed(m5),
            "long_confirmed": long_confirm,
            "short_confirmed": short_confirm,
        },
        "data_complete": complete,
        "minimum_candles_required": 35,
        "latest_data_age_seconds": age,
        "timeframes": snapshots,
        "scenarios": [s.to_dict() for s in br],
        "decision_basis": best.to_dict() if best else None,
        "note": "MODEL_ESTIMATE only. EMA10/20, RSI14, MACD(12,26,9), Bollinger(20,2), ATR14, OHLC structure and D1/H1/M15/M5/M1 alignment are evaluated. No win rate or execution guarantee is inferred.",
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
