"""Step Index quantitative validation utilities.

Research-only: does not place trades and does not promise a future win rate.
Functions are dependency-free and use closed OHLC candles supplied by callers.
"""
from __future__ import annotations

import math
from typing import Any, Iterable


def log_returns(closes: Iterable[float]) -> list[float]:
    """Natural-log returns ln(P[t] / P[t-1]); invalid/nonpositive prices are skipped."""
    prices = [float(x) for x in closes]
    out: list[float] = []
    for a, b in zip(prices, prices[1:]):
        if a > 0 and b > 0 and math.isfinite(a) and math.isfinite(b):
            out.append(math.log(b / a))
    return out


def wilson_interval(wins: int, n: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    """Two-sided Wilson score interval for a binomial proportion."""
    if n <= 0 or wins < 0 or wins > n:
        return None, None
    p = wins / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / den
    return max(0.0, center - half), min(1.0, center + half)


def _finite_sample_sd(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def equity_stats(r_multiples: Iterable[float], cost_r: float = 0.0) -> dict[str, Any]:
    """Descriptive performance in R units after a user-supplied round-trip cost."""
    rs = [float(x) - float(cost_r) for x in r_multiples]
    rs = [x for x in rs if math.isfinite(x)]
    n = len(rs)
    wins = sum(x > 0 for x in rs)
    losses = sum(x < 0 for x in rs)
    flats = n - wins - losses
    p = wins / n if n else None
    lo, hi = wilson_interval(wins, n)
    gross_wins = sum(x for x in rs if x > 0)
    gross_losses = -sum(x for x in rs if x < 0)
    mean = sum(rs) / n if n else None
    sd = _finite_sample_sd(rs)
    equity = peak = max_dd = 0.0
    curve = [0.0]
    for value in rs:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        curve.append(equity)
    downside_rms = math.sqrt(sum(min(x, 0.0) ** 2 for x in rs) / n) if n else None
    return {
        "n": n, "wins": wins, "losses": losses, "flats": flats,
        "win_rate": p, "wilson_95_low": lo, "wilson_95_high": hi,
        "expectancy_r": mean, "sample_sd_r": sd,
        "profit_factor": gross_wins / gross_losses if gross_losses else (math.inf if gross_wins else None),
        "max_drawdown_r": max_dd,
        "sharpe_per_trade_not_annualized": mean / sd if mean is not None and sd not in (None, 0) else None,
        "sortino_per_trade_not_annualized": mean / downside_rms if mean is not None and downside_rms else None,
        "net_sum_r": sum(rs) if n else None,
        "equity_curve_r": curve,
        "cost_r_per_trade": float(cost_r),
    }


def log_compounding(r_multiples: Iterable[float], risk_fraction: float) -> dict[str, Any]:
    """Hypothetical compounding; f is account fraction risked per 1R trade."""
    if not 0 < risk_fraction < 1:
        raise ValueError("risk_fraction must be in (0, 1)")
    rs = [float(x) for x in r_multiples]
    factors = [1.0 + risk_fraction * x for x in rs]
    if any(x <= 0 or not math.isfinite(x) for x in factors):
        return {"risk_fraction": risk_fraction, "valid": False, "log_growth": None, "return_fraction": None}
    growth = sum(math.log(x) for x in factors)
    return {
        "risk_fraction": risk_fraction,
        "valid": True,
        "log_growth": growth,
        "return_fraction": math.expm1(growth),
        "geometric_growth_per_trade": math.exp(growth / len(factors)) - 1 if factors else None,
    }


def acceptance_gate(
    stats: dict[str, Any],
    *,
    min_trades: int = 100,
    target_win_rate: float = 0.70,
    require_costs: bool = True,
    costs_supplied: bool = False,
) -> dict[str, Any]:
    """Evidence gate: never treat target_win_rate as a guaranteed forecast."""
    checks = {
        "minimum_out_of_sample_trades": stats.get("n", 0) >= min_trades,
        "observed_win_rate_at_or_above_target": (stats.get("win_rate") is not None and stats["win_rate"] >= target_win_rate),
        "wilson_95_lower_bound_at_or_above_target": (stats.get("wilson_95_low") is not None and stats["wilson_95_low"] >= target_win_rate),
        "positive_net_expectancy": (stats.get("expectancy_r") is not None and stats["expectancy_r"] > 0),
        "profit_factor_above_one": (stats.get("profit_factor") is not None and stats["profit_factor"] > 1),
        "round_trip_costs_provided": (costs_supplied or not require_costs),
    }
    return {
        "eligible": all(checks.values()),
        "decision": "ELIGIBLE_FOR_FURTHER_REVIEW" if all(checks.values()) else "NO_TRADE",
        "checks": checks,
        "target_win_rate": target_win_rate,
        "disclaimer": "Historical evidence gate only. It is not a guarantee or a probability for the next trade.",
    }


def analyze_backtest(r_multiples: Iterable[float], close_prices: Iterable[float] | None = None,
                     cost_r: float | None = None, min_trades: int = 100) -> dict[str, Any]:
    """Return full quantitative metrics and a conservative trade-eligibility state."""
    raw_rs = [float(x) for x in r_multiples]
    costs_supplied = cost_r is not None
    cost = float(cost_r) if cost_r is not None else 0.0
    stats = equity_stats(raw_rs, cost_r=cost)
    # Preserve whether costs were actually supplied; a zero default must not pass the gate.
    prices = list(close_prices or [])
    logs = log_returns(prices)
    stats["log_return_stats"] = {
        "n": len(logs),
        "mean": sum(logs) / len(logs) if logs else None,
        "sample_sd": _finite_sample_sd(logs),
        "geometric_return_fraction": math.expm1(sum(logs)) if logs else None,
    }
    net_rs = [value - cost for value in raw_rs]
    stats["compounding_scenarios"] = [log_compounding(net_rs, f) for f in (0.005, 0.01, 0.02)]
    stats["acceptance"] = acceptance_gate(
        stats, min_trades=min_trades, require_costs=True, costs_supplied=costs_supplied
    )
    return stats
