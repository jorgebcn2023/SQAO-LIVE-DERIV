"""Chronological M1 replay for the v23 MTF pullback detector. No orders."""
import json, math, os
from pathlib import Path
from datetime import datetime, timezone
from ENGINE.step_index_scalping_v23 import TF, detect, market


def wilson(w, n, z=1.96):
    if not n:
        return [None, None]
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def stats(rs):
    n = len(rs)
    wins = sum(x > 0 for x in rs)
    gp = sum(x for x in rs if x > 0)
    gl = -sum(x for x in rs if x < 0)
    eq = peak = dd = 0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "n": n,
        "win_rate": wins / n if n else None,
        "wilson95": wilson(wins, n),
        "expectancy_r": sum(rs) / n if n else None,
        "profit_factor": gp / gl if gl else None,
        "max_drawdown_r": dd,
        "total_r": sum(rs),
    }


def r_multiple(entry, exit_price, risk, side):
    if risk <= 0:
        raise ValueError("risk must be positive")
    signed_move = (exit_price - entry) * (1 if side == "LONG" else -1)
    return signed_move / risk


def replay(frames, cost):
    m1 = frames["M1"]
    trades = []
    next_i = 0
    for i in range(80, len(m1) - 2):
        if i < next_i:
            continue
        decision = m1[i]["epoch"] + TF["M1"]
        hist = {
            tf: [r for r in rows if r["epoch"] + TF[tf] <= decision]
            for tf, rows in frames.items()
        }
        signal = detect(hist)
        if not signal.get("confirmed"):
            continue

        entry = float(m1[i + 1]["open"])
        stop = float(signal["stop_reference"])
        side = signal["direction"]

        # Reject a next-bar gap that has already crossed the stop.
        if (side == "LONG" and stop >= entry) or (side == "SHORT" and stop <= entry):
            continue
        risk = abs(entry - stop)
        if not math.isfinite(risk) or risk <= 0:
            continue

        target = entry + (risk if side == "LONG" else -risk)
        exit_price = None
        reason = "TIME_EXIT"
        end = min(len(m1) - 1, i + 21)
        for j in range(i + 1, end + 1):
            high, low = float(m1[j]["high"]), float(m1[j]["low"])
            stop_hit = low <= stop if side == "LONG" else high >= stop
            target_hit = high >= target if side == "LONG" else low <= target
            if stop_hit:
                exit_price = stop
                reason = "STOP_FIRST" if target_hit else "STOP"
                break
            if target_hit:
                exit_price = target
                reason = "TARGET"
                break

        if exit_price is None:
            exit_price = float(m1[end]["close"])
        gross_r = r_multiple(entry, exit_price, risk, side)
        cost_r = cost / risk
        net_r = gross_r - cost_r
        trades.append({
            "signal_epoch": decision,
            "direction": side,
            "entry": entry,
            "exit": exit_price,
            "stop": stop,
            "gross_r": gross_r,
            "cost_r": cost_r,
            "net_r": net_r,
            "exit_reason": reason,
        })
        next_i = end + 1

    rs = [trade["net_r"] for trade in trades]
    split = int(len(trades) * 0.6)
    valid = int(len(trades) * 0.8)
    return {
        "method": "closed-candle MTF replay; next M1 open; stop-first; one position at a time; max hold 20 M1 bars",
        "round_trip_cost_price": cost,
        "all": stats(rs),
        "train": stats(rs[:split]),
        "validation": stats(rs[split:valid]),
        "oos": stats(rs[valid:]),
        "trades": trades,
    }


def main():
    raw = os.getenv("SQAO_SCALP_ROUND_TRIP_COST_PRICE", "").strip()
    if not raw:
        raise SystemExit("BLOCKED_MISSING_ROUND_TRIP_COST_PRICE: configure realistic spread+slippage+commission in quoted price units")
    cost = float(raw)
    if not math.isfinite(cost) or cost < 0:
        raise SystemExit("Invalid round-trip cost")
    sym, frames = __import__("asyncio").run(market())
    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": sym,
        "data_counts": {k: len(v) for k, v in frames.items()},
        "read_only": True,
        "backtest": replay(frames, cost),
    }
    Path("DATA").mkdir(exist_ok=True)
    Path("DATA/step_index_scalping_v23_backtest.json").write_text(
        json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(json.dumps({"symbol": sym, "counts": result["data_counts"], "oos": result["backtest"]["oos"]}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
