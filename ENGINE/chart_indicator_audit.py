"""Complete, grouped indicator audit for SQAO Step Index charts.

Calculates only indicators with explicit, reproducible definitions from closed OHLC.
Unlabelled screenshot-only panes are deliberately marked unidentified and never scored.
Correlated indicators are grouped so they cannot inflate directional confluence.
"""
from __future__ import annotations

import math
from typing import Any

TIMEFRAMES = ("H4", "H1", "M15", "M5", "M1")
WEIGHTS = {"H4": 3, "H1": 2, "M15": 2, "M5": 1, "M1": 1}


def _valid(rows: list[dict[str, Any]]) -> list[dict[str, float]]:
    out = []
    for row in rows:
        try:
            x = {k: float(row[k]) for k in ("open", "high", "low", "close")}
            if not all(math.isfinite(v) for v in x.values()):
                continue
            if x["high"] < max(x["open"], x["close"], x["low"]):
                continue
            if x["low"] > min(x["open"], x["close"], x["high"]):
                continue
            out.append(x)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for x in values[period:]:
        value = alpha * x + (1.0 - alpha) * value
    return value


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [b - a for a, b in zip(values[-period-1:-1], values[-period:])]
    gain = sum(max(x, 0.0) for x in changes) / period
    loss = sum(max(-x, 0.0) for x in changes) / period
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _true_ranges(rows: list[dict[str, float]]) -> list[float]:
    return [max(r["high"] - r["low"], abs(r["high"] - rows[i-1]["close"]),
                abs(r["low"] - rows[i-1]["close"])) for i, r in enumerate(rows) if i]


def _adx(rows: list[dict[str, float]], period: int = 14) -> dict[str, float | None]:
    if len(rows) < period * 2 + 1:
        return {"adx14": None, "plus_di14": None, "minus_di14": None}
    plus, minus, tr = [], [], []
    for prev, cur in zip(rows, rows[1:]):
        up = cur["high"] - prev["high"]
        down = prev["low"] - cur["low"]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
        tr.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]),
                      abs(cur["low"] - prev["close"])))
    dx = []
    for i in range(period - 1, len(tr)):
        tr_sum = sum(tr[i-period+1:i+1])
        if tr_sum <= 0:
            dx.append(0.0)
            continue
        pdi = 100.0 * sum(plus[i-period+1:i+1]) / tr_sum
        mdi = 100.0 * sum(minus[i-period+1:i+1]) / tr_sum
        denom = pdi + mdi
        dx.append(0.0 if denom == 0 else 100.0 * abs(pdi - mdi) / denom)
    if len(dx) < period:
        return {"adx14": None, "plus_di14": None, "minus_di14": None}
    # Transparent rolling DX mean; do not label this Wilder-smoothed ADX.
    adx_value = sum(dx[-period:]) / period
    tr_sum = sum(tr[-period:])
    pdi = 100.0 * sum(plus[-period:]) / tr_sum if tr_sum else None
    mdi = 100.0 * sum(minus[-period:]) / tr_sum if tr_sum else None
    return {"adx14": adx_value, "plus_di14": pdi, "minus_di14": mdi}


def _macd(values: list[float]) -> dict[str, float | None]:
    if len(values) < 35:
        return {"macd_line": None, "macd_signal": None, "macd_histogram": None}
    line = []
    for i in range(len(values)):
        a, b = _ema(values[:i+1], 12), _ema(values[:i+1], 26)
        if a is not None and b is not None:
            line.append(a - b)
    signal = _ema(line, 9)
    current = line[-1] if line else None
    return {"macd_line": current, "macd_signal": signal,
            "macd_histogram": current - signal if current is not None and signal is not None else None}


def indicator_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bars = _valid(rows)
    c = [x["close"] for x in bars]
    last = c[-1] if c else None
    emas = {f"ema{p}": _ema(c, p) for p in (9, 20, 50)}
    atrs = _true_ranges(bars)
    atr14 = sum(atrs[-14:]) / 14 if len(atrs) >= 14 else None
    bb = {"bollinger20_lower": None, "bollinger20_middle": None, "bollinger20_upper": None,
          "bollinger20_width": None, "bollinger20_percent_b": None}
    if len(c) >= 20:
        sample = c[-20:]
        mid = sum(sample) / 20
        sd = math.sqrt(sum((x-mid)**2 for x in sample) / 20)
        lo, hi = mid - 2*sd, mid + 2*sd
        bb = {"bollinger20_lower": lo, "bollinger20_middle": mid, "bollinger20_upper": hi,
              "bollinger20_width": (hi-lo)/mid if mid else None,
              "bollinger20_percent_b": (last-lo)/(hi-lo) if hi != lo else 0.5}
    stoch = {"stochastic9_k": None, "stochastic9_d": None}
    if len(bars) >= 11:
        ks = []
        for i in range(len(bars)-3, len(bars)):
            seg = bars[i-8:i+1]
            lo, hi = min(x["low"] for x in seg), max(x["high"] for x in seg)
            ks.append(50.0 if hi == lo else 100.0*(bars[i]["close"]-lo)/(hi-lo))
        stoch = {"stochastic9_k": ks[-1], "stochastic9_d": sum(ks[-3:])/3}
    macd = _macd(c)
    adx = _adx(bars)
    ema9, ema20, ema50 = emas.values()
    trend = "BULLISH" if all(x is not None for x in (ema9,ema20,ema50)) and ema9>ema20>ema50 else (
        "BEARISH" if all(x is not None for x in (ema9,ema20,ema50)) and ema9<ema20<ema50 else "MIXED/NA")
    # One vote per independent feature family; correlated members never add separate votes.
    groups: dict[str, str] = {}
    groups["trend"] = "LONG" if trend == "BULLISH" else "SHORT" if trend == "BEARISH" else "NEUTRAL"
    hist = macd["macd_histogram"]
    groups["momentum_macd"] = "LONG" if hist is not None and hist > 0 else "SHORT" if hist is not None and hist < 0 else "NEUTRAL"
    rsi = _rsi(c)
    k, d = stoch["stochastic9_k"], stoch["stochastic9_d"]
    # RSI and stochastic are combined into one oscillator family to avoid double counting.
    osc_votes = []
    if rsi is not None and rsi > 55: osc_votes.append(1)
    elif rsi is not None and rsi < 45: osc_votes.append(-1)
    if k is not None and d is not None and k > d and k < 80: osc_votes.append(1)
    elif k is not None and d is not None and k < d and k > 20: osc_votes.append(-1)
    groups["oscillator_rsi_stoch"] = "LONG" if sum(osc_votes)>0 else "SHORT" if sum(osc_votes)<0 else "NEUTRAL"
    pdi, mdi, adxv = adx["plus_di14"], adx["minus_di14"], adx["adx14"]
    groups["directional_strength_adx_di"] = ("LONG" if pdi is not None and mdi is not None and adxv is not None and adxv >= 20 and pdi > mdi
        else "SHORT" if pdi is not None and mdi is not None and adxv is not None and adxv >= 20 and mdi > pdi else "NEUTRAL")
    # Bollinger is a volatility/location diagnostic, not a standalone directional vote.
    groups["volatility_bollinger"] = "EXPANSION" if bb["bollinger20_width"] is not None else "NOT_AVAILABLE"
    groups["atr14"] = "AVAILABLE" if atr14 is not None else "NOT_AVAILABLE"
    return {
        "candles_used": len(bars), "last_close": last, **emas, "ema_stack": trend,
        "rsi14": rsi, "atr14": atr14, **macd, **bb, **adx, **stoch,
        "group_votes": groups,
        "unlabelled_chart_panes": "NOT_IDENTIFIABLE_FROM_SCREENSHOT; excluded from scoring",
        "indicator_parameters": {"EMA": [9,20,50], "Bollinger": [20,2], "MACD": [12,26,9],
                                 "RSI": 14, "ATR": 14, "ADX_DI": 14, "Stochastic": [9,3,3]},
    }


def build_mtf_audit(frames: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    snapshots = {tf: indicator_snapshot(frames.get(tf, [])) for tf in TIMEFRAMES}
    groups = ("trend", "momentum_macd", "oscillator_rsi_stoch", "directional_strength_adx_di")
    rows, long_score, short_score = {}, 0, 0
    max_score = sum(WEIGHTS.values()) * len(groups)
    for tf in TIMEFRAMES:
        votes = snapshots[tf]["group_votes"]
        l = sum(1 for g in groups if votes[g] == "LONG")
        s = sum(1 for g in groups if votes[g] == "SHORT")
        weight = WEIGHTS[tf]
        long_score += l * weight
        short_score += s * weight
        rows[tf] = {"weight": weight, "long_groups": l, "short_groups": s,
                    "long_weighted": l*weight, "short_weighted": s*weight,
                    "group_votes": votes}
    total = long_score + short_score
    decision = "LONG_BIAS" if long_score > short_score else "SHORT_BIAS" if short_score > long_score else "NO_DIRECTIONAL_EDGE"
    return {"timeframes": snapshots, "confluence": rows,
            "score": {"long": long_score, "short": short_score, "max_per_side": max_score,
                      "long_pct": 100*long_score/max_score, "short_pct": 100*short_score/max_score,
                      "decision": decision,
                      "method": "Four independent vote families; EMA stack, MACD histogram, combined RSI/Stochastic, ADX/DI; Bollinger/ATR are diagnostics only. Weights H4=3,H1=2,M15=2,M5=1,M1=1."},
            "limitations": ["Unlabelled screenshot indicator panes cannot be identified from pixels and are excluded.",
                            "This audit uses closed OHLC input; it does not infer exact values from screenshot pixels.",
                            "Confluence score is descriptive, not a calibrated probability or backtest win rate."]}
