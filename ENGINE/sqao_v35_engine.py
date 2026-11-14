"""SQAO V3.5 experimental quantitative engine.

READ-ONLY / RESEARCH-ONLY. Pure functions; no broker, network, or order APIs.
All prices are quoted price units. Monetary sizing requires verified MT5 specs.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

TIMEFRAME_WEIGHTS = {"D1": 0.35, "H4": 0.25, "H1": 0.15,
                     "M15": 0.15, "M5": 0.05, "M1": 0.05}
REQUIRED_TIMEFRAMES = tuple(TIMEFRAME_WEIGHTS)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def validate_ohlc(rows: Iterable[dict[str, Any]], timeframe_seconds: int,
                  now_epoch: int) -> dict[str, Any]:
    """Validate, sort and deduplicate closed OHLC candles; report gaps separately."""
    if timeframe_seconds <= 0:
        raise ValueError("timeframe_seconds must be positive")
    valid, invalid, forming = [], 0, 0
    seen: dict[int, dict[str, Any]] = {}
    duplicates = 0
    for row in rows:
        try:
            epoch = int(row["epoch"])
            candle = {k: float(row[k]) for k in ("open", "high", "low", "close")}
            if not all(math.isfinite(v) for v in candle.values()) or epoch < 0:
                raise ValueError
            if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
                raise ValueError
            if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
                raise ValueError
            if epoch + timeframe_seconds > int(now_epoch):
                forming += 1
                continue
            if epoch in seen:
                duplicates += 1
            seen[epoch] = {"epoch": epoch, **candle}
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid += 1
    valid = [seen[k] for k in sorted(seen)]
    gaps = []
    for left, right in zip(valid, valid[1:]):
        delta = right["epoch"] - left["epoch"]
        if delta > timeframe_seconds:
            gaps.append({"from_epoch": left["epoch"], "to_epoch": right["epoch"],
                         "missing_intervals": max(0, delta // timeframe_seconds - 1)})
    ordered = all(a["epoch"] < b["epoch"] for a, b in zip(valid, valid[1:]))
    return {"candles": valid, "count": len(valid), "invalid_rows": invalid,
            "forming_rows_excluded": forming, "duplicates_removed": duplicates,
            "gaps": gaps, "ordered": ordered,
            "integrity_pass": bool(valid) and invalid == 0 and not gaps and ordered}


def log_returns(closes: Iterable[float]) -> list[float]:
    prices = [float(x) for x in closes]
    result = []
    for a, b in zip(prices, prices[1:]):
        if a > 0 and b > 0 and math.isfinite(a) and math.isfinite(b):
            result.append(math.log(b / a))
    return result


def autocorrelation(values: Iterable[float], max_lag: int = 10) -> dict[str, Any]:
    xs = [float(x) for x in values]
    if len(xs) < 3 or max_lag < 1:
        return {"n": len(xs), "acf": {}, "status": "INSUFFICIENT_SAMPLE"}
    if not all(math.isfinite(x) for x in xs):
        return {"n": len(xs), "acf": {}, "status": "INVALID_VALUES"}
    mean = sum(xs) / len(xs)
    denom = sum((x - mean) ** 2 for x in xs)
    if denom == 0:
        return {"n": len(xs), "acf": {}, "status": "ZERO_VARIANCE"}
    acf = {}
    for lag in range(1, min(max_lag, len(xs) - 1) + 1):
        acf[str(lag)] = sum((xs[i] - mean) * (xs[i-lag] - mean)
                            for i in range(lag, len(xs))) / denom
    return {"n": len(xs), "acf": acf, "status": "OK"}


def runs_test(values: Iterable[float]) -> dict[str, Any]:
    """Wald-Wolfowitz runs test on signs around the sample median; ties are omitted."""
    xs = [float(x) for x in values if _finite(x)]
    if len(xs) < 10:
        return {"n": len(xs), "runs": None, "z": None, "status": "INSUFFICIENT_SAMPLE"}
    ordered = sorted(xs)
    median = (ordered[(len(ordered)-1)//2] + ordered[len(ordered)//2]) / 2
    signs = [1 if x > median else 0 for x in xs if x != median]
    n1, n2 = sum(signs), len(signs) - sum(signs)
    if min(n1, n2) < 2:
        return {"n": len(signs), "runs": None, "z": None, "status": "INSUFFICIENT_CLASSES"}
    runs = 1 + sum(a != b for a, b in zip(signs, signs[1:]))
    n = n1 + n2
    expected = 1 + 2*n1*n2/n
    variance = (2*n1*n2*(2*n1*n2-n))/(n*n*(n-1))
    z = (runs - expected) / math.sqrt(variance) if variance > 0 else None
    return {"n": n, "positive_class": n1, "negative_class": n2,
            "runs": runs, "expected_runs": expected, "z": z,
            "interpretation": ("CLUSTERING_EVIDENCE" if z is not None and z < -1.96
                               else "ALTERNATION_EVIDENCE" if z is not None and z > 1.96
                               else "NO_SIGNIFICANT_DEPARTURE"),
            "status": "OK"}


def ema(values: Iterable[float], period: int) -> float | None:
    xs = [float(x) for x in values]
    if period < 2 or len(xs) < period or not all(math.isfinite(x) for x in xs):
        return None
    alpha = 2.0 / (period + 1)
    value = sum(xs[:period]) / period
    for x in xs[period:]:
        value = alpha*x + (1-alpha)*value
    return value


def rsi(values: Iterable[float], period: int = 14) -> float | None:
    xs = [float(x) for x in values]
    if len(xs) < period + 1:
        return None
    changes = [b-a for a,b in zip(xs[-period-1:-1], xs[-period:])]
    gains = sum(max(x, 0) for x in changes) / period
    losses = sum(max(-x, 0) for x in changes) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return 100 - 100/(1 + gains/losses)


def macd(values: Iterable[float]) -> dict[str, float | None]:
    xs = [float(x) for x in values]
    if len(xs) < 35:
        return {"line": None, "signal": None, "histogram": None}
    fast, slow = [], []
    alpha_f, alpha_s = 2/13, 2/27
    f = sum(xs[:12])/12
    s = sum(xs[:26])/26
    for i, x in enumerate(xs):
        if i >= 12:
            f = alpha_f*x + (1-alpha_f)*f
        if i >= 26:
            s = alpha_s*x + (1-alpha_s)*s
        if i >= 25:
            fast.append(f-s)
    if len(fast) < 9:
        return {"line": None, "signal": None, "histogram": None}
    sig = sum(fast[:9])/9
    for x in fast[9:]:
        sig = (2/10)*x + (8/10)*sig
    line = fast[-1]
    return {"line": line, "signal": sig, "histogram": line-sig}


def indicator_snapshot(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    candles = list(rows)
    closes = [float(x["close"]) for x in candles]
    m = macd(closes)
    return {"close": closes[-1] if closes else None, "ema9": ema(closes,9),
            "ema20": ema(closes,20), "ema50": ema(closes,50),
            "ema200": ema(closes,200), "rsi14": rsi(closes,14), "macd": m}


def classify_regime(snapshot: dict[str, Any]) -> str:
    e20, e50, close = snapshot.get("ema20"), snapshot.get("ema50"), snapshot.get("close")
    if not all(_finite(x) for x in (e20,e50,close)) or close <= 0:
        return "UNCLASSIFIED"
    separation = abs(e20-e50)/close
    if separation < 0.00015:
        return "RANGE"
    if e20 > e50:
        return "TREND_UP"
    if e20 < e50:
        return "TREND_DOWN"
    return "TRANSITION"


def mtf_confluence(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    buy = sell = covered = 0.0
    details = {}
    for tf, weight in TIMEFRAME_WEIGHTS.items():
        snap = snapshots.get(tf)
        if not snap:
            details[tf] = {"status":"MISSING", "weight":weight}
            continue
        regime = classify_regime(snap)
        macd_data = snap.get("macd") or {}
        direction = 1 if regime == "TREND_UP" else -1 if regime == "TREND_DOWN" else 0
        hist = macd_data.get("histogram")
        if _finite(hist) and direction and ((hist > 0 and direction > 0) or (hist < 0 and direction < 0)):
            direction *= 1
        if direction > 0: buy += weight
        elif direction < 0: sell += weight
        else: covered += weight
        details[tf] = {"status":"OK", "regime":regime, "direction":direction, "weight":weight}
    total = buy+sell+covered
    return {"buy_score":buy, "sell_score":sell, "neutral_score":covered,
            "coverage":total, "details":details,
            "scores_are_probabilities":False,
            "status":"COMPLETE" if len(snapshots.keys() & TIMEFRAME_WEIGHTS.keys()) == 6 else "INCOMPLETE"}


def size_position(balance: float, risk_fraction: float, stop_distance: float,
                  tick_size: float, tick_value_per_lot: float,
                  volume_min: float, volume_step: float,
                  estimated_cost_per_lot: float = 0.0) -> dict[str, Any]:
    vals = (balance,risk_fraction,stop_distance,tick_size,tick_value_per_lot,
            volume_min,volume_step,estimated_cost_per_lot)
    if not all(_finite(x) for x in vals) or balance <= 0 or not 0 < risk_fraction < 1:
        raise ValueError("Invalid risk sizing inputs")
    if min(stop_distance,tick_size,tick_value_per_lot,volume_min,volume_step) <= 0 or estimated_cost_per_lot < 0:
        raise ValueError("Distances, contract values and volume constraints must be positive")
    risk_budget = balance*risk_fraction
    loss_per_lot = (stop_distance/tick_size)*tick_value_per_lot + estimated_cost_per_lot
    raw = risk_budget/loss_per_lot
    steps = math.floor((raw+1e-12)/volume_step)
    volume = steps*volume_step
    if volume + 1e-12 < volume_min:
        return {"eligible":False,"decision":"NO_TRADE","reason":"MIN_VOLUME_EXCEEDS_RISK_BUDGET",
                "risk_budget":risk_budget,"minimum_volume_loss":volume_min*loss_per_lot,
                "theoretical_volume":raw,"volume":0.0}
    return {"eligible":True,"decision":"SIZE_WITHIN_RISK","risk_budget":risk_budget,
            "theoretical_volume":raw,"volume":round(volume,8),
            "estimated_loss":volume*loss_per_lot,"loss_per_lot":loss_per_lot}


def final_decision(*, data_integrity_pass: bool, mtf_complete: bool,
                   costs_verified: bool, oos_gate_pass: bool,
                   technical_direction: str | None, risk_gate_pass: bool) -> dict[str, Any]:
    blockers = []
    for passed, name in ((data_integrity_pass,"DATA_INTEGRITY"),
                         (mtf_complete,"MTF_INCOMPLETE"),(costs_verified,"COSTS_UNVERIFIED"),
                         (oos_gate_pass,"OOS_GATE_FAILED"),(risk_gate_pass,"RISK_GATE_FAILED")):
        if not passed:
            blockers.append(name)
    if technical_direction not in {"BUY","SELL"}:
        blockers.append("NO_CONFIRMED_TECHNICAL_DIRECTION")
    decision = technical_direction if not blockers else "NO_TRADE"
    return {"decision":decision,"execution_eligible":False,
            "mode":"READ_ONLY","blockers":blockers,
            "note":"Analytical classification only; no order execution is available."}
