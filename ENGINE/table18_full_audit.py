"""SQAO Table 18 — complete numeric historical trade ledger (research-only).

Consumes the canonical step_index_quant_report.json. Every price is copied from
the chronological OHLC backtest ledger; no screenshot-derived or hypothetical
execution levels are manufactured. Indicator snapshots are explicitly labelled
as latest report context, not historical-at-entry indicator values.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")
INDICATORS = (
    "candles", "last_closed_epoch", "last_close", "ema10", "ema20", "rsi14",
    "atr14", "macd_line", "macd_signal", "macd_histogram",
    "bollinger20_lower", "bollinger20_middle", "bollinger20_upper",
    "stochastic9_k", "stochastic9_d",
)
BASE_FIELDS = (
    "candidate_id", "sample", "direction", "signal_epoch", "entry_epoch",
    "entry", "stop_loss", "take_profit", "exit_epoch", "exit_price",
    "risk_price_units", "reward_price_units", "sl_distance_price_units",
    "tp_distance_price_units", "risk_reward", "gross_r", "cost_r", "net_r",
    "round_trip_cost_price_units", "exit_reason", "holding_bars",
)


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Trade field {name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"Trade field {name} must be finite")
    return result


def _epoch_iso(epoch: Any) -> str | None:
    if epoch is None:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()


def build_table18(report: dict[str, Any]) -> dict[str, Any]:
    """Build one fully numeric row per recorded historical backtest trade."""
    backtest = report.get("backtest") or {}
    trades = backtest.get("trades") or []
    indicators = report.get("indicators") or {}
    params = backtest.get("parameters") or {}
    rows = []
    for index, trade in enumerate(trades, 1):
        direction = str(trade.get("direction", "")).upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError(f"Trade {index}: invalid direction")
        entry = _number(trade.get("entry"), "entry")
        stop = _number(trade.get("stop"), "stop")
        target = _number(trade.get("target"), "target")
        exit_price = _number(trade.get("exit"), "exit")
        risk = abs(entry - stop)
        reward = abs(target - entry)
        if risk <= 0 or (direction == "LONG" and not (stop < entry < target)) or (
            direction == "SHORT" and not (target < entry < stop)
        ):
            raise ValueError(f"Trade {index}: invalid entry/SL/TP geometry")
        rr = reward / risk
        row = {
            "candidate_id": index, "sample": trade.get("sample", "NOT_AVAILABLE"),
            "direction": direction, "signal_epoch": trade.get("signal_epoch"),
            "entry_epoch": trade.get("entry_epoch"), "entry": entry,
            "stop_loss": stop, "take_profit": target,
            "exit_epoch": trade.get("exit_epoch"),
            "exit_price": exit_price, "risk_price_units": risk,
            "reward_price_units": reward, "sl_distance_price_units": risk,
            "tp_distance_price_units": reward, "risk_reward": rr,
            "gross_r": _number(trade.get("gross_r"), "gross_r"),
            "cost_r": _number(trade.get("cost_r"), "cost_r"),
            "net_r": _number(trade.get("net_r"), "net_r"),
            "round_trip_cost_price_units": params.get("round_trip_cost_price"),
            "exit_reason": trade.get("exit_reason", "NOT_AVAILABLE"),
            "holding_bars": trade.get("holding_bars", "NOT_AVAILABLE"),
            "signal_time_utc": _epoch_iso(trade.get("signal_epoch")),
            "entry_time_utc": _epoch_iso(trade.get("entry_epoch")),
            "indicator_provenance": "LATEST_REPORT_CONTEXT_NOT_HISTORICAL_AT_ENTRY",
        }
        # Latest indicator values are retained per timeframe without pretending
        # that these are the values that existed at the historical signal time.
        for tf in TIMEFRAMES:
            snap = indicators.get(tf) or {}
            for key in INDICATORS:
                row[f"latest_{tf.lower()}_{key}"] = snap.get(key)
            row[f"latest_{tf.lower()}_direction"] = snap.get("direction", "NOT_AVAILABLE")
        rows.append(row)

    def summarize(sample: str) -> dict[str, Any]:
        selected = [r for r in rows if r["sample"] == sample]
        rs = [r["net_r"] for r in selected]
        wins = sum(x > 0 for x in rs)
        losses = sum(x < 0 for x in rs)
        gross_profit = sum(x for x in rs if x > 0)
        gross_loss = -sum(x for x in rs if x < 0)
        equity = peak = max_dd = 0.0
        for value in rs:
            equity += value
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        n = len(rs)
        # Wilson interval uses the number of positive net-R outcomes.
        z = 1.96
        if n:
            p = wins / n
            denom = 1 + z*z/n
            center = (p + z*z/(2*n))/denom
            half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/denom
            wilson = [center-half, center+half]
        else:
            wilson = [None, None]
        return {
            "trades": n, "wins": wins, "losses": losses,
            "win_rate": wins/n if n else None, "wilson95": wilson,
            "expectancy_net_r": sum(rs)/n if n else None,
            "profit_factor_net": gross_profit/gross_loss if gross_loss else None,
            "max_drawdown_net_r": max_dd, "total_net_r": sum(rs),
            "costs_configured": params.get("round_trip_cost_price") is not None,
            "costs_verified": False,
        }

    return {
        "schema_version": "18.1.0",
        "generated_at_utc": report.get("generated_at_utc"),
        "symbol": report.get("symbol"),
        "source": report.get("source"),
        "read_only": True,
        "rule": backtest.get("rule"),
        "parameters": params,
        "methodology": "One row per actual chronological backtest trade. Entry/SL/TP/exit are copied from recorded OHLC ledger. Latest MTF indicators are context only; historical-at-entry indicator values require per-trade recomputation from OHLC.",
        "field_order": list(rows[0].keys()) if rows else list(BASE_FIELDS),
        "row_count": len(rows),
        "summary": {sample: summarize(sample) for sample in ("train", "out_of_sample")},
        "rows": rows,
        "missing_data_policy": "Missing indicator values remain null/NOT_AVAILABLE; no imputation or pixel-derived execution prices.",
    }


def write_table18(report_path: str | Path, output_dir: str | Path) -> dict[str, str]:
    source = Path(report_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = json.loads(source.read_text(encoding="utf-8"))
    table = build_table18(report)
    json_path = out / "step_index_table18_complete.json"
    csv_path = out / "step_index_table18_complete.csv"
    json_path.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    fields = table["field_order"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(table["rows"])
    return {"json": str(json_path), "csv": str(csv_path)}


def main() -> None:
    import os
    data_dir = Path(os.getenv("SQAO_DATA_DIR", "DATA"))
    paths = write_table18(data_dir / "step_index_quant_report.json", data_dir)
    print(json.dumps(paths, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
