"""Advanced, leakage-aware Step Index diagnostics. Research-only; never places orders.

Hurst, FFT phase and Fisher are descriptive features, not guarantees of predictive power.
Bayesian estimates must be fitted on training trades only and queried with coarse state bins.
Monte Carlo resamples trades WITH replacement to quantify uncertainty in win rate and drawdown;
permuting a fixed win/loss list alone cannot change its win rate.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np


def _finite(values: Sequence[float]) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    return a[np.isfinite(a)]


def calculate_hurst(values: Sequence[float], min_size: int = 20) -> float | None:
    """Approximate R/S Hurst exponent on log-price increments; return None if under-sampled."""
    prices = _finite(values)
    if len(prices) < max(80, min_size * 3) or np.any(prices <= 0):
        return None
    returns = np.diff(np.log(prices))
    if len(returns) < min_size * 3 or np.std(returns) == 0:
        return 0.5 if len(returns) else None
    sizes = np.unique(np.floor(np.geomspace(min_size, min(len(returns) // 2, 256), 10)).astype(int))
    points: list[tuple[float, float]] = []
    for size in sizes:
        rs_values = []
        for start in range(0, len(returns) - size + 1, size):
            segment = returns[start:start + size]
            sigma = float(np.std(segment, ddof=1))
            if sigma <= 0:
                continue
            centered = segment - float(np.mean(segment))
            spread = float(np.max(np.cumsum(centered)) - np.min(np.cumsum(centered)))
            if spread > 0:
                rs_values.append(spread / sigma)
        if rs_values:
            points.append((math.log(float(size)), math.log(float(np.mean(rs_values)))))
    if len(points) < 4:
        return None
    slope = float(np.polyfit([p[0] for p in points], [p[1] for p in points], 1)[0])
    return float(np.clip(slope, 0.0, 1.0))


def hurst_regime(hurst: float | None, trend_threshold: float = 0.55,
                 mean_reversion_threshold: float = 0.45) -> str:
    if hurst is None or not math.isfinite(hurst):
        return "UNKNOWN"
    if hurst > trend_threshold:
        return "TREND"
    if hurst < mean_reversion_threshold:
        return "MEAN_REVERSION"
    return "RANDOM_OR_AMBIGUOUS"


def fft_cycle(values: Sequence[float], min_period: int = 8,
              max_period: int | None = None) -> dict[str, Any]:
    """Dominant non-zero frequency on a detrended, Hann-windowed series."""
    x = _finite(values)
    if len(x) < 32:
        return {"available": False, "reason": "insufficient_history"}
    n = len(x)
    max_period = min(max_period or n // 2, n // 2)
    if max_period < min_period:
        return {"available": False, "reason": "invalid_period_range"}
    t = np.arange(n, dtype=float)
    detrended = x - np.polyval(np.polyfit(t, x, 1), t)
    windowed = detrended * np.hanning(n)
    spectrum = np.fft.rfft(windowed)
    frequencies = np.fft.rfftfreq(n, d=1.0)
    valid = (frequencies > 0) & (1.0 / np.maximum(frequencies, 1e-12) >= min_period) & (
        1.0 / np.maximum(frequencies, 1e-12) <= max_period)
    if not np.any(valid) or float(np.max(np.abs(spectrum[valid]))) <= 1e-12:
        return {"available": False, "reason": "no_dominant_cycle"}
    indexes = np.where(valid)[0]
    peak = int(indexes[np.argmax(np.abs(spectrum[valid]))])
    period = float(1.0 / frequencies[peak])
    phase = float(np.angle(spectrum[peak]))
    power = float(abs(spectrum[peak]) ** 2)
    total_power = float(np.sum(np.abs(spectrum[valid]) ** 2))
    return {"available": True, "dominant_period_bars": period,
            "phase_radians": phase, "phase_degrees": float(np.degrees(phase)),
            "peak_power_share": power / total_power if total_power else None,
            "warning": "Retrospective spectral feature; not a forecast without out-of-sample validation."}


def fisher_transform(highs: Sequence[float], lows: Sequence[float],
                     length: int = 9) -> list[float | None]:
    """Ehlers-style Fisher transform of normalized median price, clipped for numerical stability."""
    hi, lo = _finite(highs), _finite(lows)
    if len(hi) != len(lo) or length < 2 or len(hi) < length:
        return [None] * len(hi)
    median = (hi + lo) / 2.0
    out: list[float | None] = [None] * len(median)
    value = 0.0
    fisher_prev = 0.0
    for i in range(length - 1, len(median)):
        window = median[i - length + 1:i + 1]
        low, high = float(np.min(window)), float(np.max(window))
        if high <= low:
            normalized = 0.0
        else:
            normalized = 2.0 * ((median[i] - low) / (high - low) - 0.5)
        value = float(np.clip(0.33 * normalized + 0.67 * value, -0.999, 0.999))
        fisher = 0.5 * math.log((1.0 + value) / (1.0 - value)) + 0.5 * fisher_prev
        fisher_prev = fisher
        out[i] = fisher
    return out


def squeeze_state(rows: Sequence[dict[str, Any]], length: int = 20,
                  bb_mult: float = 2.0, kc_mult: float = 1.5) -> dict[str, Any]:
    """Bollinger-inside-Keltner squeeze and release; volume confirmation is optional."""
    if len(rows) < length + 1:
        return {"available": False, "squeeze": None, "release": None, "volume_confirmed": None}
    close = np.asarray([float(r["close"]) for r in rows], dtype=float)
    high = np.asarray([float(r["high"]) for r in rows], dtype=float)
    low = np.asarray([float(r["low"]) for r in rows], dtype=float)
    c = close[-length:]
    mean = float(np.mean(c))
    sd = float(np.std(c, ddof=0))
    bb_upper, bb_lower = mean + bb_mult * sd, mean - bb_mult * sd
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - close[:-1]),
                                                   np.abs(low[1:] - close[:-1])))
    atr = float(np.mean(tr[-length:]))
    kc_mid = float(np.mean(close[-length:]))
    kc_upper, kc_lower = kc_mid + kc_mult * atr, kc_mid - kc_mult * atr
    squeeze_now = bb_upper < kc_upper and bb_lower > kc_lower
    prev_rows = rows[:-1]
    previous = squeeze_state(prev_rows, length, bb_mult, kc_mult) if len(prev_rows) >= length + 1 else {
        "available": True, "squeeze": False}
    release = bool(previous.get("squeeze") and not squeeze_now)
    vols = [r.get("volume", r.get("tick_volume")) for r in rows[-length:]]
    volume_confirmed = None
    if all(v is not None for v in vols):
        try:
            v = np.asarray(vols, dtype=float)
            volume_confirmed = bool(v[-1] > np.median(v[:-1]) * 1.2) if len(v) > 1 else None
        except (TypeError, ValueError):
            volume_confirmed = None
    return {"available": True, "squeeze": bool(squeeze_now), "release": release,
            "volume_confirmed": volume_confirmed, "bb_width": float(bb_upper - bb_lower),
            "kc_width": float(kc_upper - kc_lower),
            "volume_note": "Unavailable unless source candles expose volume/tick_volume." if volume_confirmed is None else None}


def condition_key(features: dict[str, Any]) -> tuple[str, str, str, str]:
    """Coarse bins prevent exact-dictionary matching from collapsing the sample size."""
    h = features.get("hurst")
    if h is None:
        regime = "UNKNOWN"
    else:
        regime = hurst_regime(float(h))
    fisher = features.get("fisher")
    if fisher is None:
        fstate = "UNKNOWN"
    elif fisher >= 2:
        fstate = "OVERBOUGHT"
    elif fisher <= -2:
        fstate = "OVERSOLD"
    else:
        fstate = "NEUTRAL"
    return (regime, fstate, str(features.get("squeeze_release", "UNKNOWN")),
            str(features.get("direction", "UNKNOWN")))


def bayesian_probability(training_samples: Sequence[dict[str, Any]],
                         current_features: dict[str, Any],
                         min_samples: int = 30,
                         prior_alpha: float = 1.0, prior_beta: float = 1.0) -> dict[str, Any]:
    """Beta-binomial posterior using matching TRAIN-only samples; never claim a calibrated forecast."""
    key = condition_key(current_features)
    matches = [s for s in training_samples if condition_key(s.get("features", {})) == key]
    wins = sum(1 for s in matches if float(s.get("net_r", 0.0)) > 0)
    n = len(matches)
    alpha, beta = prior_alpha + wins, prior_beta + n - wins
    mean = alpha / (alpha + beta)
    # Wilson interval for observed conditional win rate, with prior smoothing only in posterior mean.
    if n:
        p = wins / n
        z = 1.959963984540054
        denom = 1 + z*z/n
        center = (p + z*z/(2*n)) / denom
        half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
        lower, upper = center-half, center+half
    else:
        lower, upper = None, None
    return {"estimated_probability": mean, "observed_win_rate": wins/n if n else None,
            "matches": n, "wins": wins, "posterior_alpha": alpha, "posterior_beta": beta,
            "wilson_95_low": lower, "wilson_95_high": upper,
            "sufficient_sample": n >= min_samples,
            "threshold_pass": bool(n >= min_samples and lower is not None and lower >= 0.70),
            "condition_key": list(key),
            "note": "Research estimate only; requires chronological OOS calibration and realistic costs."}


def monte_carlo_trade_bootstrap(net_r: Sequence[float], paths: int = 10000,
                                seed: int = 20261012) -> dict[str, Any]:
    """Bootstrap with replacement; report win-rate interval and terminal equity/drawdown distribution."""
    x = _finite(net_r)
    if len(x) < 2:
        return {"available": False, "reason": "at_least_two_trades_required"}
    if paths < 100:
        raise ValueError("paths must be >= 100")
    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, len(x), size=(paths, len(x)))
    samples = x[indexes]
    wins = np.mean(samples > 0, axis=1)
    equity = np.cumsum(samples, axis=1)
    peaks = np.maximum.accumulate(np.concatenate([np.zeros((paths, 1)), equity], axis=1), axis=1)[:, 1:]
    drawdowns = np.min(equity - peaks, axis=1)
    terminals = equity[:, -1]
    return {"available": True, "paths": paths, "seed": seed, "trade_count": int(len(x)),
            "win_rate_p05": float(np.quantile(wins, .05)),
            "win_rate_median": float(np.quantile(wins, .50)),
            "win_rate_p95": float(np.quantile(wins, .95)),
            "terminal_r_p05": float(np.quantile(terminals, .05)),
            "terminal_r_median": float(np.quantile(terminals, .50)),
            "terminal_r_p95": float(np.quantile(terminals, .95)),
            "max_drawdown_r_p95_worst": float(np.quantile(drawdowns, .05)),
            "probability_terminal_positive": float(np.mean(terminals > 0)),
            "warning": "Bootstrap quantifies sampling uncertainty; it does not prove future win rate or robustness."}
