"""End-to-end Step Index research pipeline for SQAO.

Fetches public Deriv OHLC, calculates a fixed MTF breakout research rule,
evaluates the final chronological holdout, and emits JSON/PDF outputs.
Research-only: it never sends or places trading orders.
"""
from __future__ import annotations

import asyncio
import bisect
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets

from .step_index_quant import analyze_backtest, equity_stats, log_returns, acceptance_gate

WS = os.getenv("DERIV_PUBLIC_WS", "wss://api.derivws.com/trading/v1/options/ws/public")
GRANULARITY = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}
MAX_CANDLE_CHUNK = 5000

# Deriv-published classic Step Index mechanics; descriptive metadata only.
# Not MT5 tick_size/tick_value and never used to convert price moves into USD.
STEP_INDEX_MARKET_MECHANICS = {
    "instrument_family": "classic_step_index",
    "price_step_per_tick": 0.1,
    "direction_probability_up": 0.5,
    "direction_probability_down": 0.5,
    "published_drift": 0.0,
    "units": "quoted_price_units",
    "use_in_ohlc_calculations": False,
    "mt5_tick_size_verified": False,
    "mt5_tick_value_verified": False,
    "monetary_conversion_enabled": False,
    "source": "Deriv Academy — Step Indices evolution",
    "source_url": "https://traders-academy.deriv.com/es/trading-guides/step-indices-evolution-step",
}
DEFAULT_COUNTS = {"M1": 5000, "M5": 20000, "M15": 7000, "H1": 2500, "H4": 1500, "D1": 1000, "W1": 260}


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for x in values[period:]:
        value = x * alpha + value * (1.0 - alpha)
    return value


def atr(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(rows) < period + 1:
        return None
    tr = []
    for i in range(1, len(rows)):
        high, low, previous_close = float(rows[i]["high"]), float(rows[i]["low"]), float(rows[i - 1]["close"])
        tr.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(tr[-period:]) / period


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    diffs = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    gain = sum(max(x, 0.0) for x in diffs) / period
    loss = sum(max(-x, 0.0) for x in diffs) / period
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def closed_candles(rows: list[dict[str, Any]], timeframe: str, now_epoch: int | None = None) -> list[dict[str, Any]]:
    """Sort candles and exclude any candle that has not fully closed."""
    now = int(now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp())
    seconds = GRANULARITY[timeframe]
    valid = []
    for row in rows:
        try:
            item = {**row, "epoch": int(row["epoch"]), "open": float(row["open"]),
                    "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])}
        except (KeyError, TypeError, ValueError):
            continue
        if item["epoch"] + seconds <= now and all(math.isfinite(item[k]) for k in ("open", "high", "low", "close")):
            valid.append(item)
    valid.sort(key=lambda x: x["epoch"])
    # Remove duplicate timestamps deterministically.
    return list({x["epoch"]: x for x in valid}.values())


async def _request(ws: Any, payload: dict[str, Any]) -> dict[str, Any]:
    await ws.send(json.dumps(payload))
    request_id = payload.get("req_id")
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
        if message.get("error"):
            raise RuntimeError(message["error"].get("message", "Deriv API error"))
        if message.get("req_id") == request_id:
            return message


async def discover_step_index() -> dict[str, str]:
    async with websockets.connect(WS, ping_interval=20, ping_timeout=20, open_timeout=20) as ws:
        data = await _request(ws, {"active_symbols": "brief", "req_id": 101})
    candidates = []
    for item in data.get("active_symbols", []) or []:
        name = str(item.get("display_name") or item.get("underlying_symbol_name") or "")
        symbol = str(item.get("symbol") or item.get("underlying_symbol") or "")
        if symbol and "step index" in f"{name} {symbol}".lower():
            candidates.append({"symbol": symbol, "display_name": name})
    if not candidates:
        raise RuntimeError("Deriv public API did not return an active Step Index symbol; no proxy instrument will be substituted.")
    preferred = os.getenv("DERIV_STEP_NAME", "").strip().lower()
    for candidate in candidates:
        if preferred and (preferred == candidate["symbol"].lower() or preferred in candidate["display_name"].lower()):
            return candidate
    exact = next((x for x in candidates if x["display_name"].strip().lower() == "step index"), None)
    return exact or candidates[0]


async def fetch_candles(symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
    """Fetch longer histories in <=5000-candle pages, walking backward by epoch."""
    if count <= 0:
        raise ValueError("count must be positive")
    all_rows: dict[int, dict[str, Any]] = {}
    end: str | int = "latest"
    granularity = GRANULARITY[timeframe]
    async with websockets.connect(WS, ping_interval=20, ping_timeout=20, open_timeout=20) as ws:
        request_id = 20000 + granularity
        while len(all_rows) < count:
            remaining = count - len(all_rows)
            page_count = min(MAX_CANDLE_CHUNK, remaining)
            data = await _request(ws, {
                "ticks_history": symbol, "end": end, "count": page_count,
                "style": "candles", "granularity": granularity,
                "adjust_start_time": 1, "req_id": request_id,
            })
            page = data.get("candles", []) or []
            if not page:
                break
            before = len(all_rows)
            for row in page:
                try:
                    all_rows[int(row["epoch"])] = row
                except (KeyError, TypeError, ValueError):
                    continue
            ordered_epochs = sorted(all_rows)
            if len(all_rows) == before or not ordered_epochs:
                break
            if len(all_rows) >= count:
                break
            earliest = ordered_epochs[0]
            new_end = earliest - 1
            if not isinstance(end, str) and new_end >= end:
                break
            end = new_end
            request_id += 1
    return [all_rows[k] for k in sorted(all_rows)][-count:]


def ema_series(values: list[float], period: int) -> list[float | None]:
    """EMA values aligned to input rows, in O(n) time."""
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    out[period - 1] = value
    for i in range(period, len(values)):
        value = values[i] * alpha + value * (1.0 - alpha)
        out[i] = value
    return out


def atr_series(rows: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """Simple rolling ATR aligned to candles, matching atr() semantics."""
    out: list[float | None] = [None] * len(rows)
    if len(rows) < period + 1:
        return out
    trs: list[float] = []
    for i in range(1, len(rows)):
        high, low, previous_close = float(rows[i]["high"]), float(rows[i]["low"]), float(rows[i - 1]["close"])
        trs.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        if len(trs) >= period:
            out[i] = sum(trs[-period:]) / period
    return out


def _trend_cache(rows: list[dict[str, Any]], timeframe: str) -> tuple[list[int], list[float | None], list[float | None]]:
    seconds = GRANULARITY[timeframe]
    decision_epochs = [int(row["epoch"]) + seconds for row in rows]
    closes = [float(row["close"]) for row in rows]
    return decision_epochs, ema_series(closes, 10), ema_series(closes, 20)


def _cached_trend_at(cache: tuple[list[int], list[float | None], list[float | None]], decision_epoch: int) -> str | None:
    epochs, fast_values, slow_values = cache
    index = bisect.bisect_right(epochs, decision_epoch) - 1
    if index < 29:
        return None
    fast, slow = fast_values[index], slow_values[index]
    if fast is None or slow is None or fast == slow:
        return None
    return "LONG" if fast > slow else "SHORT"


def trend_at(rows: list[dict[str, Any]], decision_epoch: int, timeframe: str) -> str | None:
    """Reference implementation for tests and occasional live lookups."""
    return _cached_trend_at(_trend_cache(rows, timeframe), decision_epoch)


def signal_m5(hist: list[dict[str, Any]]) -> str | None:
    """Fixed breakout rule using only candles closed by the decision timestamp."""
    if len(hist) < 30:
        return None
    c = [float(r["close"]) for r in hist]
    fast, slow = ema(c, 10), ema(c, 20)
    prior = hist[-21:-1]
    if fast is None or slow is None:
        return None
    if c[-1] > max(float(x["high"]) for x in prior) and fast > slow:
        return "LONG"
    if c[-1] < min(float(x["low"]) for x in prior) and fast < slow:
        return "SHORT"
    return None


def backtest_m5(
    m5: list[dict[str, Any]], m15: list[dict[str, Any]], h1: list[dict[str, Any]],
    *, horizon: int = 5, rr: float = 1.5, atr_mult: float = 1.2,
    round_trip_cost_price: float | None = None, train_fraction: float = 0.70,
) -> dict[str, Any]:
    """Chronological test with next-bar-open entry, M15/H1 filters and stop-first ties."""
    if not 0.5 < train_fraction < 0.95:
        raise ValueError("train_fraction must be between 0.5 and 0.95")
    if horizon < 1 or rr <= 0 or atr_mult <= 0:
        raise ValueError("horizon, rr and atr_mult must be positive")
    split = int(len(m5) * train_fraction)
    trades: list[dict[str, Any]] = []
    next_allowed = 0
    closes = [float(row["close"]) for row in m5]
    ema10 = ema_series(closes, 10)
    ema20 = ema_series(closes, 20)
    atr_values = atr_series(m5, 14)
    m15_cache = _trend_cache(m15, "M15")
    h1_cache = _trend_cache(h1, "H1")
    for i in range(40, max(40, len(m5) - horizon - 1)):
        if i < next_allowed or i + 1 >= len(m5):
            continue
        direction = None
        fast, slow = ema10[i], ema20[i]
        previous = m5[i - 20:i]
        if fast is not None and slow is not None and len(previous) == 20:
            if closes[i] > max(float(x["high"]) for x in previous) and fast > slow:
                direction = "LONG"
            elif closes[i] < min(float(x["low"]) for x in previous) and fast < slow:
                direction = "SHORT"
        if not direction:
            continue
        decision_epoch = int(m5[i]["epoch"]) + GRANULARITY["M5"]
        if _cached_trend_at(m15_cache, decision_epoch) != direction:
            continue
        if _cached_trend_at(h1_cache, decision_epoch) != direction:
            continue
        risk_value = atr_values[i]
        if risk_value is None or risk_value <= 0:
            continue
        risk = risk_value * atr_mult
        entry_bar = m5[i + 1]
        entry = float(entry_bar["open"])
        stop = entry - risk if direction == "LONG" else entry + risk
        target = entry + rr * risk if direction == "LONG" else entry - rr * risk
        exit_price = None
        exit_reason = "TIME_EXIT"
        gross_r = 0.0
        last_j = min(len(m5) - 1, i + horizon)
        for j in range(i + 1, last_j + 1):
            candle = m5[j]
            high, low = float(candle["high"]), float(candle["low"])
            stop_hit = low <= stop if direction == "LONG" else high >= stop
            target_hit = high >= target if direction == "LONG" else low <= target
            if stop_hit and target_hit:
                exit_price, exit_reason, gross_r = stop, "STOP_AND_TARGET_SAME_BAR_STOP_FIRST", -1.0
                break
            if stop_hit:
                exit_price, exit_reason, gross_r = stop, "STOP", -1.0
                break
            if target_hit:
                exit_price, exit_reason, gross_r = target, "TARGET", rr
                break
        if exit_price is None:
            exit_price = float(m5[last_j]["close"])
            directional_change = (exit_price - entry) * (1.0 if direction == "LONG" else -1.0)
            gross_r = max(-1.0, min(rr, directional_change / risk))
        cost_r = (float(round_trip_cost_price) / risk) if round_trip_cost_price is not None else 0.0
        net_r = gross_r - cost_r
        trades.append({
            "signal_epoch": decision_epoch, "entry_epoch": int(entry_bar["epoch"]),
            "direction": direction, "entry": entry, "exit": exit_price, "stop": stop, "target": target,
            "risk_price": risk, "gross_r": gross_r, "cost_r": cost_r, "net_r": net_r,
            "exit_reason": exit_reason, "sample": "train" if i < split else "out_of_sample",
        })
        next_allowed = last_j + 1
    train = [x for x in trades if x["sample"] == "train"]
    oos = [x for x in trades if x["sample"] == "out_of_sample"]
    gross_cost_defined = round_trip_cost_price is not None
    train_stats = equity_stats([x["gross_r"] for x in train])
    oos_gross = equity_stats([x["gross_r"] for x in oos])
    oos_net = equity_stats([x["net_r"] for x in oos])
    gate = acceptance_gate(oos_net, min_trades=int(os.getenv("SQAO_STEP_MIN_OOS_TRADES", "100")),
                           target_win_rate=float(os.getenv("SQAO_STEP_TARGET_WIN_RATE", "0.70")),
                           require_costs=True, costs_supplied=gross_cost_defined)
    return {
        "rule": "M5 close breakout of prior 20-bar high/low + EMA10/20 direction; M15 and H1 closed-candle EMA10/20 must agree",
        "parameters": {"horizon_m5_bars": horizon, "target_R": rr, "stop_ATR_multiple": atr_mult,
                       "train_fraction": train_fraction, "round_trip_cost_price": round_trip_cost_price},
        "n_m5_candles": len(m5), "train": {"n_trades": len(train), "stats_gross": train_stats},
        "out_of_sample": {"n_trades": len(oos), "stats_gross": oos_gross, "stats_net": oos_net, "gate": gate},
        "trades": trades,
        "warning": "Historical test of a fixed proxy rule, not proof of the live signal's future success. Cost-adjusted results require a real round-trip cost in quote-price units.",
    }


def indicator_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    c = [float(r["close"]) for r in rows]
    e10, e20 = ema(c, 10), ema(c, 20)
    e12, e26 = ema_series(c, 12), ema_series(c, 26)
    macd_line = [a - b if a is not None and b is not None else None for a, b in zip(e12, e26)]
    compact_macd = [x for x in macd_line if x is not None]
    macd_signal_values = ema_series(compact_macd, 9)
    macd_value = compact_macd[-1] if compact_macd else None
    signal_value = macd_signal_values[-1] if macd_signal_values else None
    bb_mid = bb_low = bb_high = None
    if len(c) >= 20:
        recent = c[-20:]
        bb_mid = sum(recent) / 20
        sd = math.sqrt(sum((x - bb_mid) ** 2 for x in recent) / 20)
        bb_low, bb_high = bb_mid - 2 * sd, bb_mid + 2 * sd
    stoch_values = []
    for i in range(max(8, len(rows) - 10), len(rows)):
        segment = rows[max(0, i - 8):i + 1]
        lo = min(float(x["low"]) for x in segment)
        hi = max(float(x["high"]) for x in segment)
        stoch_values.append(50.0 if hi == lo else 100.0 * (float(rows[i]["close"]) - lo) / (hi - lo))
    stoch_k = stoch_values[-1] if stoch_values else None
    stoch_d = sum(stoch_values[-3:]) / min(3, len(stoch_values)) if stoch_values else None
    extra = _chart_series(rows) if len(rows) >= 60 else {}
    fib = {}
    if rows:
        hi = max(float(x["high"]) for x in rows[-100:])
        lo = min(float(x["low"]) for x in rows[-100:])
        span = hi - lo
        fib = {str(ratio): hi - span * ratio for ratio in (0.236, 0.382, 0.5, 0.618, 0.786)}
    return {
        "candles": len(rows), "last_closed_epoch": int(rows[-1]["epoch"]) if rows else None,
        "last_close": c[-1] if c else None, "ema9": ema(c, 9), "ema10": e10, "ema20": e20, "ema50": ema(c, 50),
        "direction": "LONG" if e10 is not None and e20 is not None and e10 > e20 else
                     "SHORT" if e10 is not None and e20 is not None and e10 < e20 else "UNKNOWN",
        "rsi14": rsi(c), "atr14": atr(rows, 14),
        "macd_line": macd_value, "macd_signal": signal_value,
        "macd_histogram": macd_value - signal_value if macd_value is not None and signal_value is not None else None,
        "bollinger20_lower": bb_low, "bollinger20_middle": bb_mid, "bollinger20_upper": bb_high,
        "stochastic9_k": stoch_k, "stochastic9_d": stoch_d,
        "adx14": (extra.get("adx") or [None])[-1], "plus_di14": (extra.get("plus_di") or [None])[-1],
        "minus_di14": (extra.get("minus_di") or [None])[-1],
        "fibonacci_rolling_100": fib,
    }


def snapshot(frames: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {tf: indicator_snapshot(rows) for tf, rows in frames.items()}


def current_setup(frames: dict[str, list[dict[str, Any]]], *, rr: float = 1.5, atr_mult: float = 1.2) -> dict[str, Any]:
    m5, m15, h1 = frames.get("M5", []), frames.get("M15", []), frames.get("H1", [])
    if len(m5) < 40 or len(m15) < 30 or len(h1) < 30:
        return {"confirmed": False, "state": "INSUFFICIENT_DATA"}
    direction = signal_m5(m5)
    last = m5[-1]
    decision_epoch = int(last["epoch"]) + GRANULARITY["M5"]
    if not direction:
        return {"confirmed": False, "state": "NO_CURRENT_TRIGGER",
                "reference_price": float(last["close"]), "decision_epoch": decision_epoch}
    if trend_at(m15, decision_epoch, "M15") != direction or trend_at(h1, decision_epoch, "H1") != direction:
        return {"confirmed": False, "state": "MTF_FILTER_MISMATCH", "direction": direction,
                "reference_price": float(last["close"]), "decision_epoch": decision_epoch}
    volatility = atr(m5, 14)
    if volatility is None or volatility <= 0:
        return {"confirmed": False, "state": "ATR_UNAVAILABLE", "direction": direction}
    entry = float(last["close"])
    risk = volatility * atr_mult
    stop = entry - risk if direction == "LONG" else entry + risk
    target = entry + risk * rr if direction == "LONG" else entry - risk * rr
    return {"confirmed": True, "state": "CONDITIONAL_SETUP",
            "direction": direction, "reference_price": entry, "stop_reference": stop,
            "target_reference": target, "risk_price": risk, "target_R": rr,
            "decision_epoch": decision_epoch,
            "note": "Reference at last closed M5 close only; confirm current quote and execution costs before any decision."}


def oos_subperiods(trades: list[dict[str, Any]], m5: list[dict[str, Any]], train_fraction: float = 0.70, folds: int = 4) -> list[dict[str, Any]]:
    if not m5 or folds < 2:
        return []
    start = int(m5[int(len(m5) * train_fraction)]["epoch"]) if int(len(m5) * train_fraction) < len(m5) else int(m5[-1]["epoch"])
    end = int(m5[-1]["epoch"]) + GRANULARITY["M5"]
    width = max(1, (end - start) // folds)
    results = []
    for index in range(folds):
        a = start + index * width
        b = end if index == folds - 1 else min(end, a + width)
        sample = [t for t in trades if a <= int(t["signal_epoch"]) < b and t["sample"] == "out_of_sample"]
        stats = equity_stats([t["net_r"] for t in sample])
        results.append({"fold": index + 1, "start_epoch": a, "end_epoch": b, "stats_net": stats})
    return results


def log_distribution(closes: list[float]) -> dict[str, Any]:
    vals = log_returns(closes)
    if not vals:
        return {"n": 0, "mean": None, "sd": None, "skew": None, "excess_kurtosis": None}
    mean = sum(vals) / len(vals)
    variance = sum((x - mean) ** 2 for x in vals) / len(vals)
    sd = math.sqrt(variance)
    skew = sum((x - mean) ** 3 for x in vals) / len(vals) / (sd ** 3) if sd else None
    kurt = sum((x - mean) ** 4 for x in vals) / len(vals) / (sd ** 4) - 3 if sd else None
    return {"n": len(vals), "mean": mean, "sd": sd, "skew": skew, "excess_kurtosis": kurt,
            "cumulative_log_return": sum(vals), "geometric_return_fraction": math.expm1(sum(vals))}


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return "Infinity" if obj > 0 else "-Infinity" if obj < 0 else None
    return obj


def _chart_series(rows: list[dict[str, Any]]) -> dict[str, list[float | None]]:
    """Build display-only EMA, Bollinger, MACD, RSI, ATR and ADX series from closed OHLC."""
    n = len(rows)
    close = [float(r["close"]) for r in rows]
    high = [float(r["high"]) for r in rows]
    low = [float(r["low"]) for r in rows]
    def rolling_mean(values: list[float], period: int) -> list[float | None]:
        return [None if i + 1 < period else sum(values[i + 1-period:i+1]) / period for i in range(n)]
    def rolling_std(values: list[float], period: int) -> list[float | None]:
        out: list[float | None] = [None] * n
        for i in range(period - 1, n):
            seg = values[i-period+1:i+1]
            avg = sum(seg) / period
            out[i] = math.sqrt(sum((v-avg)**2 for v in seg) / period)
        return out
    ema9, ema20, ema50 = ema_series(close,9), ema_series(close,20), ema_series(close,50)
    mid = rolling_mean(close,20); sd = rolling_std(close,20)
    upper = [None if mid[i] is None or sd[i] is None else mid[i]+2*sd[i] for i in range(n)]
    lower = [None if mid[i] is None or sd[i] is None else mid[i]-2*sd[i] for i in range(n)]
    e12,e26 = ema_series(close,12),ema_series(close,26)
    macd = [None if e12[i] is None or e26[i] is None else e12[i]-e26[i] for i in range(n)]
    valid_macd = [v for v in macd if v is not None]
    sig_valid = ema_series(valid_macd,9)
    signal: list[float | None] = [None]*n
    j=0
    for i,v in enumerate(macd):
        if v is not None:
            if j < len(sig_valid): signal[i]=sig_valid[j]
            j+=1
    hist = [None if macd[i] is None or signal[i] is None else macd[i]-signal[i] for i in range(n)]
    rsi_values: list[float | None] = [None]*n
    for i in range(14,n):
        diffs=[close[k]-close[k-1] for k in range(i-13,i+1)]
        gain=sum(max(v,0) for v in diffs)/14; loss=sum(max(-v,0) for v in diffs)/14
        rsi_values[i]=100 if loss==0 and gain>0 else 50 if loss==0 else 100-100/(1+gain/loss)
    tr=[0.0]*n; plus_dm=[0.0]*n; minus_dm=[0.0]*n
    for i in range(1,n):
        tr[i]=max(high[i]-low[i],abs(high[i]-close[i-1]),abs(low[i]-close[i-1]))
        up=high[i]-high[i-1]; down=low[i-1]-low[i]
        plus_dm[i]=up if up>down and up>0 else 0.0
        minus_dm[i]=down if down>up and down>0 else 0.0
    atr_values: list[float | None]=[None]*n
    pdi: list[float | None]=[None]*n; mdi: list[float | None]=[None]*n
    dx: list[float | None]=[None]*n; adx_values: list[float | None]=[None]*n
    for i in range(14,n):
        av=sum(tr[i-13:i+1])/14
        atr_values[i]=av
        if av>0:
            pdi[i]=100*sum(plus_dm[i-13:i+1])/14/av
            mdi[i]=100*sum(minus_dm[i-13:i+1])/14/av
            denom=(pdi[i] or 0)+(mdi[i] or 0)
            dx[i]=0 if denom==0 else 100*abs((pdi[i] or 0)-(mdi[i] or 0))/denom
    for i in range(27,n):
        vals=[v for v in dx[i-13:i+1] if v is not None]
        if len(vals)==14: adx_values[i]=sum(vals)/14
    return {"ema9":ema9,"ema20":ema20,"ema50":ema50,"bb_upper":upper,"bb_mid":mid,"bb_lower":lower,
            "macd":macd,"macd_signal":signal,"macd_hist":hist,"rsi":rsi_values,
            "atr":atr_values,"adx":adx_values,"plus_di":pdi,"minus_di":mdi}


def generate_mtf_charts(frames: dict[str, list[dict[str, Any]]], outdir: Path) -> dict[str, str]:
    """Write consistent five-panel MTF PNG charts using closed Deriv OHLC only."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    from datetime import timedelta
    outdir.mkdir(parents=True, exist_ok=True)
    paths: dict[str,str] = {}
    for tf in ("M1","M5","M15","H1","H4"):
        rows=frames.get(tf,[])
        if len(rows)<60:
            continue
        ind=_chart_series(rows)
        # Keep the PDF legible while preserving a recent, fixed display window.
        limit={"M1":240,"M5":240,"M15":200,"H1":180,"H4":160}[tf]
        start=max(0,len(rows)-limit); view=rows[start:]
        x=[datetime.fromtimestamp(int(r["epoch"]),tz=timezone.utc) for r in view]
        ix=list(range(len(view)))
        fig,axes=plt.subplots(5,1,figsize=(13.0,10.0),sharex=True,
                              gridspec_kw={"height_ratios":[4.2,1.25,1.15,1.0,1.25]})
        fig.suptitle(f"SQAO · STEP INDEX · {tf} · Deriv OHLC cerrado · última vela {x[-1].strftime('%Y-%m-%d %H:%M UTC')}",
                     fontsize=13,fontweight="bold")
        ax=axes[0]
        def vals(key): return ind[key][start:]
        for k in range(len(view)):
            r=view[k]; o,h,l,c=map(float,(r["open"],r["high"],r["low"],r["close"]))
            up=c>=o; candle_color="#159D83" if up else "#D9534F"
            ax.vlines(k,l,h,color=candle_color,linewidth=.75)
            body=max(abs(c-o),0.012)
            ax.add_patch(Rectangle((k-.28,min(o,c)),.56,body,facecolor=candle_color,edgecolor=candle_color,linewidth=.5))
        for key,label,color in [("ema9","EMA 9","#D946EF"),("ema20","EMA 20","#06A6A6"),("ema50","EMA 50","#E0A526")]:
            ax.plot(ix,vals(key),label=label,linewidth=1.0,color=color)
        ax.plot(ix,vals("bb_upper"),color="#36A9E1",linewidth=.75,linestyle=":")
        ax.plot(ix,vals("bb_mid"),color="#36A9E1",linewidth=.55,alpha=.6)
        ax.plot(ix,vals("bb_lower"),color="#36A9E1",linewidth=.75,linestyle=":",label="Bollinger 20,2")
        ax.set_ylabel("Precio"); ax.legend(loc="upper left",ncol=4,fontsize=8); ax.grid(alpha=.2)
        ax=axes[1]; hist=vals("macd_hist")
        ax.bar(ix,[0 if v is None else v for v in hist],color=["#159D83" if (v or 0)>=0 else "#D9534F" for v in hist],width=.7)
        ax.plot(ix,vals("macd"),label="MACD",linewidth=.8,color="#168C99")
        ax.plot(ix,vals("macd_signal"),label="Señal",linewidth=.8,color="#D97706")
        ax.axhline(0,color="grey",linewidth=.5); ax.set_ylabel("MACD"); ax.legend(loc="upper left",fontsize=7); ax.grid(alpha=.2)
        ax=axes[2]; ax.plot(ix,vals("rsi"),color="#2563EB",linewidth=.9); ax.axhline(70,color="grey",ls="--",lw=.6); ax.axhline(50,color="grey",ls=":",lw=.5); ax.axhline(30,color="grey",ls="--",lw=.6); ax.set_ylim(0,100); ax.set_ylabel("RSI 14"); ax.grid(alpha=.2)
        ax=axes[3]; ax.plot(ix,vals("atr"),color="#0D9488",linewidth=.9); ax.set_ylabel("ATR 14"); ax.grid(alpha=.2)
        ax=axes[4]; ax.plot(ix,vals("adx"),label="ADX 14",color="#7C3AED",linewidth=.9); ax.plot(ix,vals("plus_di"),label="+DI",color="#159D83",linewidth=.75); ax.plot(ix,vals("minus_di"),label="-DI",color="#D9534F",linewidth=.75); ax.axhline(25,color="grey",ls="--",lw=.6); ax.set_ylabel("ADX / DI"); ax.legend(loc="upper left",ncol=3,fontsize=7); ax.grid(alpha=.2)
        step=max(1,len(ix)//8); ticks=ix[::step]
        axes[-1].set_xticks(ticks); axes[-1].set_xticklabels([x[i].strftime("%d %b\n%H:%M") for i in ticks],fontsize=7)
        axes[-1].set_xlabel("Tiempo (UTC)")
        fig.tight_layout(rect=[0,0,1,.97])
        path=outdir/f"step_index_chart_{tf.lower()}.png"
        fig.savefig(path,dpi=145,bbox_inches="tight"); plt.close(fig)
        paths[tf]=str(path)
    return paths


def write_pdf(report: dict[str, Any], path: Path, chart_paths: dict[str, str] | None = None) -> None:
    """Render executive PDF. ReportLab is installed by the research workflow."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as PDFImage
    from reportlab.graphics.shapes import Drawing, String, Line, PolyLine

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SQTitle", parent=styles["Title"], fontSize=19, leading=23,
                              textColor=colors.HexColor("#17324D"), alignment=1, spaceAfter=6))
    styles.add(ParagraphStyle(name="SQSub", parent=styles["Normal"], fontSize=8, leading=10,
                              textColor=colors.HexColor("#596B7A"), alignment=1, spaceAfter=10))
    styles.add(ParagraphStyle(name="SQH1", parent=styles["Heading1"], fontSize=13, leading=16,
                              textColor=colors.HexColor("#17324D"), spaceBefore=7, spaceAfter=5))
    styles.add(ParagraphStyle(name="SQH2", parent=styles["Heading2"], fontSize=10, leading=12,
                              textColor=colors.HexColor("#17657A"), spaceBefore=4, spaceAfter=3))
    styles.add(ParagraphStyle(name="SQBody", parent=styles["BodyText"], fontSize=8, leading=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="SQSmall", parent=styles["BodyText"], fontSize=6.8, leading=8, spaceAfter=2))
    styles.add(ParagraphStyle(name="SQSmallHeader", parent=styles["BodyText"], fontName="Helvetica-Bold",
                              fontSize=6.8, leading=8, textColor=colors.white, spaceAfter=2))
    styles.add(ParagraphStyle(name="SQAlert", parent=styles["BodyText"], fontSize=9, leading=12,
                              textColor=colors.HexColor("#7D2828"), borderColor=colors.HexColor("#D8A0A0"),
                              borderWidth=.7, borderPadding=6, spaceBefore=4, spaceAfter=7))
    def p(text: str, style: str = "SQBody"):
        return Paragraph(text, styles[style])
    def table(rows: list[list[Any]], widths: list[float]):
        cells = [[Paragraph(str(c), styles["SQSmallHeader"] if row_index == 0 else styles["SQSmall"])
                  for c in row] for row_index, row in enumerate(rows)]
        tb = Table(cells, colWidths=widths, repeatRows=1)
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17324D")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#B7C3CC")),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F2F5F7")]),
            ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        return tb
    oos = report["backtest"]["out_of_sample"]
    s = oos["stats_net"]
    gate = oos["gate"]
    setup = report.get("current_setup", {})
    costs_supplied = report["backtest"]["parameters"]["round_trip_cost_price"] is not None
    metric_basis = "neto tras coste declarado" if costs_supplied else "bruto, antes de costes"
    expectancy_label = "Expectativa neta" if costs_supplied else "Expectativa bruta"
    winrate_label = "Win rate neto" if costs_supplied else "Win rate bruto"
    pf_label = "PF neto" if costs_supplied else "PF bruto"
    setup_state = setup.get("state", "n/d")
    if setup_state == "NO_CURRENT_TRIGGER":
        setup_state = "NO TRIGGER"
    cost_display = str(report["backtest"]["parameters"]["round_trip_cost_price"]) if costs_supplied else "NO CONFIGURADO"
    gate_warning = ("No se ha validado una efectividad del 70% para la próxima operación. El umbral solo se aplica a una muestra cronológica fuera de muestra."
                    " Si los criterios no se cumplen, la decisión se mantiene en NO_TRADE.")
    if not costs_supplied:
        gate_warning += " Los costes round-trip no están configurados; los resultados de rentabilidad son brutos, antes de costes."
    pct = lambda x: "n/d" if x is None else f"{x * 100:.2f}%"
    num = lambda x, d=3: "n/d" if x is None else f"{x:.{d}f}"
    chart = Drawing(470, 150)
    curve = s.get("equity_curve_r", []) or [0.0]
    if len(curve) == 1:
        curve = curve * 2
    low, high = min(curve), max(curve)
    if high == low:
        high = low + 1.0
    left, right, bottom, top = 38, 455, 20, 125
    chart.add(Line(left, bottom + (0 - low) / (high - low) * (top - bottom),
                   right, bottom + (0 - low) / (high - low) * (top - bottom),
                   strokeColor=colors.HexColor("#8996A3"), strokeWidth=.6))
    pts = []
    for idx, val in enumerate(curve):
        x = left + (right - left) * idx / max(1, len(curve) - 1)
        y = bottom + (top - bottom) * (val - low) / (high - low)
        pts.extend([x, y])
    chart.add(PolyLine(pts, strokeColor=colors.HexColor("#17657A"), strokeWidth=1.5))
    chart.add(String(8, 127, f"OOS equity R | min={low:.2f} max={high:.2f}", fontSize=8, fillColor=colors.HexColor("#17324D")))
    chart.add(String(8, 4, "Trade index", fontSize=7, fillColor=colors.HexColor("#596B7A")))
    chart_flow = [PageBreak()]
    for tf in ("M1", "M5", "M15", "H1", "H4"):
        if chart_paths and tf in chart_paths:
            chart_flow.extend([
                p(f"Gráfico {tf} — fuente Deriv OHLC cerrada", "SQH2"),
                PDFImage(chart_paths[tf], width=18.0*cm, height=13.85*cm),
                PageBreak(),
            ])
        else:
            chart_flow.append(p(
                f"Gráfico {tf}: NO DISPONIBLE — histórico insuficiente o no generado.",
                "SQAlert",
            ))
    story = [
        Spacer(1, .35*cm),
        p("SQAO · STEP INDEX QUANT RESEARCH", "SQTitle"),
        p(f"Instrumento: {report['symbol'].get('display_name', report['symbol'].get('symbol', 'Step Index'))} "
          f"({report['symbol'].get('symbol', 'n/d')}) · generado {report['generated_at_utc']} · fuente Deriv public OHLC", "SQSub"),
        p(f"DICTAMEN OPERATIVO: {report['decision']}", "SQH1"),
        p("Mecánica publicada Deriv: paso de precio 0,1 por tick; probabilidades direccionales 50/50 y deriva publicada 0. Este paso descriptivo no equivale a tick_size/tick_value de MT5 y no se convierte a USD.", "SQBody"),
        p(f"Puerta estadística histórica: {gate['decision']} · setup M5 actual: {setup_state}", "SQBody"),
        p(gate_warning, "SQAlert"),
        p("1. Resultado ejecutivo", "SQH1"),
        table([
            [f"Indicadores OOS {metric_basis}","Resultado","Criterio"],
            ["Operaciones fuera de muestra",str(s["n"]),"≥ 100"],
            ["Tasa de acierto",pct(s["win_rate"]),"≥ 70% observado"],
            ["IC Wilson 95%",f"{pct(s['wilson_95_low'])} – {pct(s['wilson_95_high'])}","Límite inferior ≥ 70%"],
            [expectancy_label,f"{num(s['expectancy_r'])} R/trade","> 0"],
            ["Profit factor",num(s["profit_factor"]),"> 1"],
            ["Drawdown máximo",f"{num(s['max_drawdown_r'])} R","Control de riesgo"],
            ["Coste round-trip",cost_display,"Debe estar configurado para afirmar resultados netos"],
        ], [4.6*cm,4.2*cm,6.0*cm]),
        Spacer(1,5),
        p("2. Resumen de marcos temporales", "SQH1"),
        table([["Marco","Velas","Último cierre","EMA10","EMA20","RSI14","ATR14","Sesgo"]] + [
            [tf, x["candles"], num(x["last_close"], 2), num(x["ema10"],2), num(x["ema20"],2),
             num(x["rsi14"],2), num(x["atr14"],3), x["direction"]] for tf,x in report["indicators"].items()
        ], [1.2*cm,1.4*cm,2.2*cm,2.0*cm,2.0*cm,1.7*cm,1.7*cm,2.2*cm]),
        p("Indicadores complementarios por marco", "SQH2"),
        table([["Marco","MACD","Señal MACD","Histograma","BB inferior","BB superior","Stoch %K","Stoch %D"]] + [
            [tf, num(x["macd_line"],3), num(x["macd_signal"],3), num(x["macd_histogram"],3),
             num(x["bollinger20_lower"],2), num(x["bollinger20_upper"],2),
             num(x["stochastic9_k"],1), num(x["stochastic9_d"],1)] for tf,x in report["indicators"].items()
        ], [1.2*cm,2.0*cm,2.0*cm,2.0*cm,2.3*cm,2.3*cm,1.7*cm,1.7*cm]),
        p("Fibonacci rolling (últimas 100 velas; aproximación de rango, no pivotes confirmados)", "SQH2"),
        table([["Marco","23,6%","38,2%","50%","61,8%","78,6%"]] + [
            [tf] + [num(x["fibonacci_rolling_100"].get(str(k)),2) for k in (0.236,0.382,0.5,0.618,0.786)]
            for tf,x in report["indicators"].items()
        ], [1.5*cm,2.5*cm,2.5*cm,2.5*cm,2.5*cm,2.5*cm]),
        p("3. Gráficos técnicos MTF — estándar oficial SQAO", "SQH1"),
        p("Cada gráfico presenta velas OHLC cerradas, EMA 9/20/50, Bollinger(20,2), MACD(12,26,9), RSI(14), ATR(14) y ADX/+DI/-DI(14). Los indicadores son descriptivos y no constituyen confirmaciones estadísticamente independientes.", "SQBody"),
        *chart_flow,
        p("4. Escenario de scalping actual (condicional; no es una orden)", "SQH1"),
        table([
            ["Estado","Dirección","Precio de referencia","Stop orientativo","Objetivo orientativo","R:R"],
            [setup_state, setup.get("direction","n/d"),
             num(setup.get("reference_price"),2), num(setup.get("stop_reference"),2),
             num(setup.get("target_reference"),2), num(setup.get("target_R"),2)]
        ], [3.0*cm,2.0*cm,2.8*cm,2.8*cm,3.0*cm,1.4*cm]),
        p("Los niveles, cuando existen, usan el último cierre M5 disponible. Verifique cotización vigente, especificación del contrato y coste real antes de actuar. La operación queda bloqueada si la validación histórica no pasa todos los criterios.", "SQBody"),
        p("5. Metodología y prevención de sesgo", "SQH1"),
        p(report["backtest"]["rule"], "SQBody"),
        p("La señal se determina al cierre de M5. EMA10/20 de M15 y H1 solo usan velas ya cerradas a la hora de decisión. La entrada de simulación se realiza en la apertura de la siguiente vela M5. Si stop y objetivo aparecen tocados en la misma vela, se contabiliza primero el stop. Las últimas velas incompletas quedan excluidas.", "SQBody"),
        p("Cálculos: retorno logarítmico = ln(C[t] / C[t-1]); expectativa = media de R por operación; profit factor = suma de R positivos / valor absoluto de la suma de R negativos; drawdown = máxima caída desde un máximo previo; tasa de acierto con intervalo Wilson bilateral del 95%.", "SQBody"),
        p("6. Estadística y logaritmos", "SQH1"),
        table([
            ["Métrica","Valor"],
            ["n retornos logarítmicos M5",report["log_distribution_m5"]["n"]],
            ["Media retorno log",num(report["log_distribution_m5"]["mean"],7)],
            ["Desviación log",num(report["log_distribution_m5"]["sd"],7)],
            ["Asimetría",num(report["log_distribution_m5"]["skew"],4)],
            ["Exceso de curtosis",num(report["log_distribution_m5"]["excess_kurtosis"],4)],
            ["Retorno geométrico acumulado",pct(report["log_distribution_m5"]["geometric_return_fraction"])],
            [f"{expectancy_label} OOS",f"{num(s['expectancy_r'])} R"],
            ["Sharpe por operación (sin anualizar)",num(s["sharpe_per_trade_not_annualized"])],
            ["Sortino por operación (sin anualizar)",num(s["sortino_per_trade_not_annualized"])],
        ], [6.0*cm,9.0*cm]),
        p("7. Curva de capital fuera de muestra", "SQH1"),
        chart,
        p("8. Estabilidad por subperiodos cronológicos", "SQH1"),
        table([["Bloque OOS","Operaciones",winrate_label, f"{expectancy_label} (R)",pf_label]] + [
            [fold["fold"], fold["stats_net"]["n"], pct(fold["stats_net"]["win_rate"]),
             num(fold["stats_net"]["expectancy_r"]), num(fold["stats_net"]["profit_factor"])]
            for fold in oos.get("subperiods", [])
        ], [2.3*cm,2.8*cm,3.0*cm,3.8*cm,2.8*cm]),
        p("9. Regla de aceptación", "SQH1"),
        p("Se requiere simultáneamente tamaño de muestra suficiente, win rate observado ≥ objetivo, límite inferior de Wilson 95% ≥ objetivo, expectativa neta positiva, profit factor > 1 y costes declarados. La superación habilita revisión adicional; no garantiza rentabilidad futura ni constituye una probabilidad predictiva calibrada.", "SQBody"),
        p("10. Limitaciones", "SQH1"),
        p("Esta estrategia es un baseline mecánico (ruptura de 20 velas + EMA10/20 + filtros M15/H1), no una optimización del algoritmo de Step Index. El resultado depende del histórico disponible, el régimen de mercado, el coste comunicado y la fidelidad del modelo de ejecución. No hay conexión de órdenes ni ejecución real.", "SQBody"),
        p("11. Conclusión", "SQH1"),
        p(f"Decisión operativa del motor: {report['decision']}. Puerta histórica elegible: {gate['eligible']}. Si no se cumplen todos los filtros o los costes no se han definido, no se emite una operación activa.", "SQAlert"),
    ]
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=1.4*cm, leftMargin=1.4*cm,
                            topMargin=1.1*cm, bottomMargin=1.1*cm, title="SQAO Step Index Quant Research")
    doc.build(story)


def aggregate_weekly_from_daily(rows: list[dict[str, Any]], now_epoch: int | None = None) -> list[dict[str, Any]]:
    """Aggregate closed daily candles into complete UTC Monday-Sunday candles.

    This avoids relying on broker support for a 604800-second candle interval.
    """
    now = int(now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp())
    groups: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        ts = int(row["epoch"])
        dt = datetime.fromtimestamp(ts, timezone.utc)
        monday = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        monday_epoch = int(monday.timestamp()) - monday.weekday() * GRANULARITY["D1"]
        groups.setdefault(monday_epoch, []).append(row)
    out = []
    for week_start in sorted(groups):
        # Require the full seven-day UTC week to have elapsed.
        if week_start + GRANULARITY["W1"] > now:
            continue
        week = sorted(groups[week_start], key=lambda x: int(x["epoch"]))
        if not week:
            continue
        out.append({
            "epoch": week_start,
            "open": float(week[0]["open"]),
            "high": max(float(x["high"]) for x in week),
            "low": min(float(x["low"]) for x in week),
            "close": float(week[-1]["close"]),
        })
    return out


async def run_research() -> dict[str, Any]:
    symbol = await discover_step_index()
    frames: dict[str, list[dict[str, Any]]] = {}
    counts = {tf: int(os.getenv(f"SQAO_STEP_CANDLES_{tf}", str(n))) for tf, n in DEFAULT_COUNTS.items()}
    # W1 is aggregated from D1 so the pipeline does not depend on provider weekly granularity support.
    requested_frames = {tf: n for tf, n in counts.items() if tf != "W1"}
    tasks = {tf: fetch_candles(symbol["symbol"], tf, requested_frames[tf]) for tf in requested_frames}
    raw = await asyncio.gather(*tasks.values())
    now = int(datetime.now(timezone.utc).timestamp())
    for tf, rows in zip(tasks.keys(), raw):
        frames[tf] = closed_candles(rows, tf, now)
    frames["W1"] = aggregate_weekly_from_daily(frames.get("D1", []), now)
    for tf in ("M5", "M15", "H1"):
        if len(frames[tf]) < 100:
            raise RuntimeError(f"Insufficient closed OHLC candles for {tf}: {len(frames[tf])}")
    cost_text = os.getenv("SQAO_STEP_ROUND_TRIP_COST_PRICE", "").strip()
    cost_price = float(cost_text) if cost_text else None
    if cost_price is not None and (not math.isfinite(cost_price) or cost_price < 0):
        raise ValueError("SQAO_STEP_ROUND_TRIP_COST_PRICE must be a non-negative number in quoted-price units")
    bt = backtest_m5(frames["M5"], frames["M15"], frames["H1"],
                     horizon=int(os.getenv("SQAO_STEP_HORIZON_M5", "5")),
                     rr=float(os.getenv("SQAO_STEP_TARGET_R", "1.5")),
                     atr_mult=float(os.getenv("SQAO_STEP_ATR_MULT", "1.2")),
                     round_trip_cost_price=cost_price,
                     train_fraction=float(os.getenv("SQAO_STEP_TRAIN_FRACTION", "0.70")))
    m5_closes = [float(x["close"]) for x in frames["M5"]]
    folds = oos_subperiods(bt["trades"], frames["M5"], float(os.getenv("SQAO_STEP_TRAIN_FRACTION", "0.70")), folds=4)
    setup = current_setup(frames, rr=float(os.getenv("SQAO_STEP_TARGET_R", "1.5")),
                          atr_mult=float(os.getenv("SQAO_STEP_ATR_MULT", "1.2")))
    historical_gate = bt["out_of_sample"]["gate"]
    # Historical gate alone never turns into an immediate live order recommendation.
    decision = "CONDITIONAL_SETUP_REQUIRES_LIVE_CONFIRMATION" if historical_gate["eligible"] and setup.get("confirmed") else "NO_TRADE"
    bt["out_of_sample"]["subperiods"] = folds
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "market_mechanics": STEP_INDEX_MARKET_MECHANICS,
        "source": "Deriv public OHLC; closed candles only",
        "read_only": True,
        "indicators": snapshot(frames),
        "current_setup": setup,
        "log_distribution_m5": log_distribution(m5_closes),
        "backtest": bt,
        "decision": decision,
        "historical_eligibility": historical_gate,
        "methodology": "chronological 70/30 holdout; fixed parameters; no parameter optimization; entry at next M5 open; stop first on same-bar conflict; four descriptive chronological holdout subperiods",
        "data_counts": {tf: len(rows) for tf, rows in frames.items()},
        "limitations": ["A 70% target is not guaranteed.", "Out-of-sample history is not a prediction for the next trade.",
                        "The rule is a fixed baseline; results need independent rolling walk-forward confirmation.",
                        "Cost-adjusted eligibility is blocked unless realistic round-trip cost is provided.",
                        "Any candidate price is based on the last closed candle and is not a live executable quote."],
    }


def main() -> None:
    report = asyncio.run(run_research())
    outdir = Path(os.getenv("SQAO_DATA_DIR", "DATA"))
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "step_index_quant_report.json"
    pdf_path = outdir / "step_index_quant_report.pdf"
    json_path.write_text(json.dumps(_json_safe(report), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    chart_paths = generate_mtf_charts(frames, outdir)
    report["chart_files"] = {tf: Path(path).name for tf, path in chart_paths.items()}
    write_pdf(report, pdf_path, chart_paths)
    print(json.dumps({
        "symbol": report["symbol"], "decision": report["decision"],
        "oos_n": report["backtest"]["out_of_sample"]["n_trades"],
        "oos_win_rate": report["backtest"]["out_of_sample"]["stats_net"]["win_rate"],
        "oos_expectancy_r": report["backtest"]["out_of_sample"]["stats_net"]["expectancy_r"],
        "profit_factor": report["backtest"]["out_of_sample"]["stats_net"]["profit_factor"],
        "pdf": str(pdf_path), "json": str(json_path), "charts": report.get("chart_files", {}),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
