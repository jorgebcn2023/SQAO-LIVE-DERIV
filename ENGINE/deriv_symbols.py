"""Fail-closed discovery and selection of Deriv Step Index symbols."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any


def normalize_step_candidates(active_symbols: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return all Step Index candidates without choosing a variant."""
    candidates: dict[str, dict[str, str]] = {}
    for item in active_symbols or []:
        symbol = str(item.get("underlying_symbol") or item.get("symbol") or "").strip()
        name = str(item.get("underlying_symbol_name") or item.get("display_name") or "").strip()
        if symbol and "step index" in f"{name} {symbol}".lower():
            candidates[symbol] = {"symbol": symbol, "display_name": name or symbol}
    return sorted(candidates.values(), key=lambda x: (x["display_name"].casefold(), x["symbol"].casefold()))


def select_step_index_symbol(active_symbols: list[dict[str, Any]], requested: str | None = None) -> dict[str, Any]:
    """Select only an exact, unique candidate; ambiguity is a hard error."""
    candidates = normalize_step_candidates(active_symbols)
    stamp = datetime.now(timezone.utc).isoformat()
    selector = (requested if requested is not None else os.getenv("DERIV_STEP_NAME", "")).strip()
    if not candidates:
        raise RuntimeError("STEP_INDEX_SYMBOL_NOT_FOUND: active_symbols contained no Step Index candidates")
    if selector:
        matches = [c for c in candidates if selector.casefold() in {c["symbol"].casefold(), c["display_name"].casefold()}]
        if len(matches) != 1:
            raise RuntimeError(
                "STEP_INDEX_SYMBOL_SELECTION_FAILED: DERIV_STEP_NAME must exactly match one symbol code "
                f"or display name; selector={selector!r}; candidates={candidates!r}"
            )
        selected = matches[0]
        reason = "exact DERIV_STEP_NAME match"
    elif len(candidates) == 1:
        selected = candidates[0]
        reason = "only active Step Index candidate"
    else:
        raise RuntimeError(
            "AMBIGUOUS_STEP_INDEX_SYMBOL: specify DERIV_STEP_NAME as an exact symbol code "
            f"or display name; candidates={candidates!r}"
        )
    return {
        **selected,
        "active_symbols_candidates": candidates,
        "selection_reason": reason,
        "symbol_discovery_timestamp_utc": stamp,
        "selector": selector or None,
    }
