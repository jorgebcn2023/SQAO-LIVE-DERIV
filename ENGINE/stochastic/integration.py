"""Adapter for the SQAO API snapshot. Research-only; consumes validated closed OHLC."""
from __future__ import annotations
import hashlib
import json
from typing import Any
from .audit import run_stochastic_audit
from .instrument_profile import InstrumentProfile

REQUIRED_TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")

def audit_mtf_closed_frames(frames: dict[str, list[dict[str, Any]]], *, symbol: str,
                            generated_at_utc: str, expected_count: int = 500,
                            q_values: tuple[int, ...] = (2, 5, 10, 20),
                            paths: int = 2000, seed: int = 20261118) -> dict[str, Any]:
    """Run independent diagnostics per timeframe; never infer MTF synchronization."""
    results: dict[str, Any] = {}
    for tf in REQUIRED_TIMEFRAMES:
        rows = frames.get(tf) or []
        normalized, errors, epochs = [], [], []
        for row in rows:
            try:
                epoch = int(row["epoch"])
                o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
                if not all(map(lambda x: x == x and abs(x) != float("inf"), (o, h, l, c))):
                    raise ValueError("NON_FINITE_OHLC")
                if min(o, h, l, c) <= 0 or h < max(o, l, c) or l > min(o, h, c):
                    raise ValueError("INVALID_OHLC_RANGE")
                normalized.append({"epoch": epoch, "open": o, "high": h, "low": l, "close": c})
                epochs.append(epoch)
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                errors.append(str(exc))
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(payload).hexdigest()
        if errors or len(normalized) != len(rows):
            results[tf] = {"status": "DATA_QUALITY_BLOCK", "decision": "NO_TRADE",
                           "execution_eligible": False, "errors": errors[:10],
                           "received_rows": len(rows), "valid_rows": len(normalized), "input_sha256": digest}
            continue
        if len(epochs) != len(set(epochs)) or epochs != sorted(epochs):
            results[tf] = {"status": "TIMESTAMP_BLOCK", "decision": "NO_TRADE",
                           "execution_eligible": False, "input_sha256": digest}
            continue
        if len(epochs) > 1:
            from .timeframes import GRANULARITY_SECONDS
            step = GRANULARITY_SECONDS.get(tf)
            if step and any((b - a) != step for a, b in zip(epochs, epochs[1:])):
                results[tf] = {"status": "GAP_BLOCK", "decision": "NO_TRADE",
                               "execution_eligible": False, "input_sha256": digest,
                               "n_prices": len(normalized)}
                continue
        if len(normalized) < 100:
            results[tf] = {"status": "INSUFFICIENT_DATA", "decision": "NO_TRADE",
                           "execution_eligible": False, "n_prices": len(normalized), "input_sha256": digest}
            continue
        profile = InstrumentProfile(name="Step Index", symbol=symbol,
                                    source="Deriv API validated closed OHLC; quote units only")
        audit = run_stochastic_audit([r["close"] for r in normalized], profile=profile,
                                     q_values=q_values, paths=paths, seed=seed)
        results[tf] = {
            **audit, "timeframe": tf, "symbol": symbol,
            "source_class": "API_RAW_CLOSED_OHLC -> DERIVED",
            "first_closed_epoch": epochs[0], "latest_closed_epoch": epochs[-1],
            "received_closed_candles": len(normalized), "requested_candles": expected_count,
            "sample_shortfall": max(0, expected_count - len(normalized)),
            "input_sha256": digest, "generated_at_utc": generated_at_utc,
            "mtf_sync_claim": "NOT_EVALUATED_BY_ALT_MODULE",
        }
    statuses = [results.get(tf, {}).get("status", "MISSING") for tf in REQUIRED_TIMEFRAMES]
    all_complete = all(s == "COMPLETED_RESEARCH_ONLY" for s in statuses)
    return {
        "module": "SQAO_V3.2.1_ALT_STOCHASTIC",
        "status": "COMPLETED_RESEARCH_ONLY" if all_complete else "PARTIAL_OR_BLOCKED",
        "symbol": symbol, "timeframes": results, "mtf_sync_verified": False,
        "decision": "NO_TRADE", "execution_eligible": False,
        "account_access": False, "trade_execution": False,
        "note": "Independent timeframe diagnostics only. No signal, win probability, synchronization claim, or execution authorization is produced.",
    }
