"""SQAO Chart Indicator Audit V2.0.

Research-only MTF indicator engine. Uses validated, closed OHLC bars only.
Implements Wilder RSI/ATR/ADX, explicit warm-up handling, data-quality reporting,
and coverage-adjusted confluence (no treating missing indicators as neutral votes).
No broker orders, no execution interface, and no screenshot price extraction.
"""
from __future__ import annotations

import math
from typing import Any

VERSION = "2.0.0"
TIMEFRAMES = ("H4", "H1", "M15", "M5", "M1")
WEIGHTS = {"H4": 3, "H1": 2, "M15": 2, "M5": 1, "M1": 1}
FAMILIES = ("trend", "momentum_macd", "oscillator_rsi_stoch", "directional_strength_adx_di")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _bars(rows: list[dict[str, Any]]) -> tuple[list[dict[str, float]], dict[str, int]]:
    valid: list[dict[str, float]] = []
    invalid = 0
    for row in rows:
        try:
            bar = {k: float(row[k]) for k in ("open", "high", "low", "close")}
            if not all(math.isfinite(v) for v in bar.values()):
                raise ValueError
            if bar["high"] < max(bar["open"], bar["close"], bar["low"]):
                raise ValueError
            if bar["low"] > min(bar["open"], bar["close"], bar["high"]):
                raise ValueError
            epoch = int(row["epoch"]) if row.get("epoch") is not None else None
            if epoch is not None and epoch <= 0:
                raise ValueError
            if epoch is not None:
                bar["epoch"] = float(epoch)
            valid.append(bar)
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid += 1
    # Preserve chronology, collapse duplicate epochs deterministically to the last supplied bar.
    valid.sort(key=lambda x: x.get("epoch", 0.0))
    deduped: list[dict[str, float]] = []
    duplicates = 0
    for bar in valid:
        if "epoch" in bar and deduped and deduped[-1].get("epoch") == bar["epoch"]:
            deduped[-1] = bar
            duplicates += 1
        else:
            deduped.append(bar)
    return deduped, {"input_rows": len(rows), "invalid_rows": invalid, "duplicate_epochs": duplicates,
                     "valid_rows": len(deduped)}


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result += alpha * (value - result)
    return result


def _wilder(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = ((period - 1) * result + value) / period
    return result


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [b - a for a, b in zip(values, values[1:])]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain, avg_loss = _wilder(gains, period), _wilder(losses, period)
    if avg_gain is None or avg_loss is None:
        return None
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    if avg_gain == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _true_ranges(bars: list[dict[str, float]]) -> list[float]:
    out = []
    for i in range(1, len(bars)):
        cur, prev = bars[i], bars[i - 1]
        out.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]),
                       abs(cur["low"] - prev["close"])))
    return out


def _atr(bars: list[dict[str, float]], period: int = 14) -> float | None:
    return _wilder(_true_ranges(bars), period)


def _adx(bars: list[dict[str, float]], period: int = 14) -> dict[str, float | None]:
    if len(bars) < 2 * period + 1:
        return {"adx14": None, "plus_di14": None, "minus_di14": None}
    plus_dm, minus_dm, tr = [], [], []
    for prev, cur in zip(bars, bars[1:]):
        up, down = cur["high"] - prev["high"], prev["low"] - cur["low"]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]),
                      abs(cur["low"] - prev["close"])))
    dx_values = []
    for end in range(period, len(tr) + 1):
        tr_s = _wilder(tr[:end], period)
        p_s, m_s = _wilder(plus_dm[:end], period), _wilder(minus_dm[:end], period)
        if tr_s is None or p_s is None or m_s is None or tr_s <= 0:
            continue
        pdi, mdi = 100.0 * p_s / tr_s, 100.0 * m_s / tr_s
        denom = pdi + mdi
        dx_values.append(0.0 if denom == 0 else 100.0 * abs(pdi - mdi) / denom)
    adx_value = _wilder(dx_values, period)
    tr_s = _wilder(tr, period)
    p_s, m_s = _wilder(plus_dm, period), _wilder(minus_dm, period)
    if tr_s is None or tr_s <= 0 or p_s is None or m_s is None:
        return {"adx14": adx_value, "plus_di14": None, "minus_di14": None}
    return {"adx14": adx_value, "plus_di14": 100.0 * p_s / tr_s,
            "minus_di14": 100.0 * m_s / tr_s}


def _macd(values: list[float]) -> dict[str, float | None]:
    if len(values) < 35:
        return {"macd_line": None, "macd_signal": None, "macd_histogram": None}
    line = []
    for end in range(26, len(values) + 1):
        sample = values[:end]
        fast, slow = _ema(sample, 12), _ema(sample, 26)
        if fast is not None and slow is not None:
            line.append(fast - slow)
    signal = _ema(line, 9)
    current = line[-1] if line else None
    return {"macd_line": current, "macd_signal": signal,
            "macd_histogram": current - signal if current is not None and signal is not None else None}


def _stochastic(bars: list[dict[str, float]], period: int = 14) -> dict[str, float | None]:
    if len(bars) < period + 2:
        return {"stochastic14_k": None, "stochastic3_k": None, "stochastic3_d": None}
    raw_k = []
    # Calculate a rolling %K series for the final three bars.
    for end in range(len(bars) - 2, len(bars) + 1):
        segment = bars[end - period:end]
        lo, hi = min(x["low"] for x in segment), max(x["high"] for x in segment)
        raw_k.append(50.0 if hi == lo else 100.0 * (bars[end - 1]["close"] - lo) / (hi - lo))
    smooth_k = sum(raw_k) / 3.0
    return {"stochastic14_k": raw_k[-1], "stochastic3_k": smooth_k,
            "stochastic3_d": smooth_k}


def _vote(value: str | None) -> str:
    return value if value in ("LONG", "SHORT") else "NEUTRAL" if value == "NEUTRAL" else "UNAVAILABLE"


def indicator_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bars, quality = _bars(rows)
    closes = [x["close"] for x in bars]
    emas = {f"ema{p}": _ema(closes, p) for p in (9, 20, 50)}
    rsi = _rsi(closes)
    atr = _atr(bars)
    macd = _macd(closes)
    adx = _adx(bars)
    stoch = _stochastic(bars)
    bb = {"bollinger20_lower": None, "bollinger20_middle": None, "bollinger20_upper": None,
          "bollinger20_width": None, "bollinger20_percent_b": None}
    if len(closes) >= 20:
        sample = closes[-20:]
        middle = sum(sample) / 20
        sd = math.sqrt(sum((x - middle) ** 2 for x in sample) / 20)
        lower, upper = middle - 2 * sd, middle + 2 * sd
        bb = {"bollinger20_lower": lower, "bollinger20_middle": middle, "bollinger20_upper": upper,
              "bollinger20_width": (upper - lower) / middle if middle else None,
              "bollinger20_percent_b": (closes[-1] - lower) / (upper - lower) if upper != lower else 0.5}
    e9, e20, e50 = emas["ema9"], emas["ema20"], emas["ema50"]
    trend = ("BULLISH" if None not in (e9, e20, e50) and e9 > e20 > e50 else
             "BEARISH" if None not in (e9, e20, e50) and e9 < e20 < e50 else "MIXED/NA")
    trend_vote = "LONG" if trend == "BULLISH" else "SHORT" if trend == "BEARISH" else (
        "NEUTRAL" if None not in (e9, e20, e50) else None)
    hist = macd["macd_histogram"]
    macd_vote = "LONG" if hist is not None and hist > 0 else "SHORT" if hist is not None and hist < 0 else (
        "NEUTRAL" if hist is not None else None)
    osc_values = []
    if rsi is not None:
        osc_values.append(1 if rsi >= 55 else -1 if rsi <= 45 else 0)
    k, d = stoch["stochastic3_k"], stoch["stochastic3_d"]
    if k is not None and d is not None:
        osc_values.append(1 if k > d and k < 80 else -1 if k < d and k > 20 else 0)
    osc_vote = ("LONG" if sum(osc_values) > 0 else "SHORT" if sum(osc_values) < 0 else "NEUTRAL") if osc_values else None
    pdi, mdi, adxv = adx["plus_di14"], adx["minus_di14"], adx["adx14"]
    di_vote = ("LONG" if adxv is not None and adxv >= 20 and pdi is not None and mdi is not None and pdi > mdi else
               "SHORT" if adxv is not None and adxv >= 20 and pdi is not None and mdi is not None and mdi > pdi else
               "NEUTRAL" if adxv is not None and pdi is not None and mdi is not None else None)
    votes = {"trend": _vote(trend_vote), "momentum_macd": _vote(macd_vote),
             "oscillator_rsi_stoch": _vote(osc_vote), "directional_strength_adx_di": _vote(di_vote)}
    last_epoch = int(bars[-1]["epoch"]) if bars and "epoch" in bars[-1] else None
    return {
        "version": VERSION, "candles_used": len(bars), "last_closed_epoch": last_epoch,
        "last_close": closes[-1] if closes else None, **emas, "ema_stack": trend,
        "rsi14": rsi, "atr14": atr, **macd, **bb, **adx, **stoch,
        "group_votes": votes, "data_quality": quality,
        "unlabelled_chart_panes": "NOT_IDENTIFIABLE_FROM_SCREENSHOT; excluded from scoring",
        "indicator_parameters": {"EMA": [9, 20, 50], "Bollinger": [20, 2], "MACD": [12, 26, 9],
                                 "RSI_WILDER": 14, "ATR_WILDER": 14, "ADX_WILDER_DI": 14,
                                 "Stochastic": [14, 3, 3]},
    }


def build_mtf_audit(frames: dict[str, list[dict[str, Any]]], *, min_coverage: float = 0.60,
                    min_directional_margin: float = 0.12) -> dict[str, Any]:
    snapshots = {tf: indicator_snapshot(frames.get(tf, [])) for tf in TIMEFRAMES}
    confluence: dict[str, Any] = {}
    long_score = short_score = available_weight = 0
    total_possible = sum(WEIGHTS.values()) * len(FAMILIES)
    for tf in TIMEFRAMES:
        votes = snapshots[tf]["group_votes"]
        weight = WEIGHTS[tf]
        available = sum(1 for family in FAMILIES if votes[family] != "UNAVAILABLE")
        longs = sum(1 for family in FAMILIES if votes[family] == "LONG")
        shorts = sum(1 for family in FAMILIES if votes[family] == "SHORT")
        long_score += longs * weight
        short_score += shorts * weight
        available_weight += available * weight
        confluence[tf] = {"weight": weight, "available_groups": available,
                          "long_groups": longs, "short_groups": shorts,
                          "long_weighted": longs * weight, "short_weighted": shorts * weight,
                          "group_votes": votes}
    coverage = available_weight / total_possible if total_possible else 0.0
    long_pct = 100.0 * long_score / available_weight if available_weight else 0.0
    short_pct = 100.0 * short_score / available_weight if available_weight else 0.0
    margin = abs(long_score - short_score) / available_weight if available_weight else 0.0
    if coverage < min_coverage or margin < min_directional_margin or long_score == short_score:
        decision = "NO_DIRECTIONAL_EDGE"
    else:
        decision = "LONG_BIAS" if long_score > short_score else "SHORT_BIAS"
    return {
        "version": VERSION, "timeframes": snapshots, "confluence": confluence,
        "score": {"long": long_score, "short": short_score, "available_weight": available_weight,
                  "max_per_side": available_weight, "total_possible_weight": total_possible,
                  "coverage_pct": 100.0 * coverage, "long_pct": long_pct, "short_pct": short_pct,
                  "directional_margin_pct": 100.0 * margin, "decision": decision,
                  "is_probability": False, "min_coverage_pct": 100.0 * min_coverage,
                  "min_directional_margin_pct": 100.0 * min_directional_margin,
                  "method": "Coverage-adjusted weighted vote across EMA stack, MACD histogram, RSI/Stochastic and ADX/DI; missing data is excluded, not counted as neutral. H4=3,H1=2,M15=2,M5=1,M1=1."},
        "limitations": ["Confluence is a descriptive score, not a calibrated probability or OOS win rate.",
                        "Only closed OHLC bars are accepted; screenshots are not a source of exact prices.",
                        "Unlabelled screenshot indicator panes are not inferred or scored.",
                        "Wilder smoothing and warm-up requirements are explicit; compare with broker display settings before assuming exact parity."],
    }
