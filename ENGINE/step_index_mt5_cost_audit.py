"""Audit MT5 Step Index cost evidence transcribed from user-provided screenshots.

Research-only: this module does not connect to MT5, place orders, or infer missing
commission/slippage. Screenshot evidence is explicitly distinguished from tick specs.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

MT5_SPEC = {
    "symbol": "Step Index",
    "precision_digits": 1,
    "contract_size": 10.0,
    "spread_spec_points": 1,
    "stops_level_points": 8,
    "margin_currency": "USD",
    "profit_currency": "USD",
    "calculation_mode": "contract_leverage",
    "chart_price_basis": "BID",
    "execution": "MARKET",
    "tick_size_reported": 0.0,
    "tick_value_reported": 0.0,
    "volume_min": 0.10,
    "volume_max": 100.0,
    "volume_step": 0.01,
    "volume_limit": 270.0,
    "commission_summary_usd": 0.0,
    "swap_summary_usd": 0.0,
    "commission_trade_level": None,
    "slippage_price_units": None,
    "tick_size_verified": False,
    "tick_value_verified": False,
}

# Eight closed deals manually transcribed from the MT5 history screenshot.
# Commission and swap cells were visually blank; blank is not converted to zero.
HISTORY_SAMPLE = [
    {"date": "10.11", "side": "SELL", "volume": 0.10, "entry": 7351.6, "exit": 7359.0, "profit_usd": -7.40},
    {"date": "10.17", "side": "SELL", "volume": 0.10, "entry": 7209.7, "exit": 7216.0, "profit_usd": -6.30},
    {"date": "10.17", "side": "SELL", "volume": 0.10, "entry": 3591.3, "exit": 3587.3, "profit_usd": 4.00},
    {"date": "10.17", "side": "SELL", "volume": 0.10, "entry": 7220.5, "exit": 7219.8, "profit_usd": 0.70},
    {"date": "10.18", "side": "BUY", "volume": 0.10, "entry": 7236.9, "exit": 7241.0, "profit_usd": 4.10},
    {"date": "10.28", "side": "SELL", "volume": 0.10, "entry": 7345.4, "exit": 7338.4, "profit_usd": 7.00},
    {"date": "11.01", "side": "BUY", "volume": 0.10, "entry": 7319.6, "exit": 7321.2, "profit_usd": 1.60},
    {"date": "11.03", "side": "SELL", "volume": 0.20, "entry": 7308.9, "exit": 7306.3, "profit_usd": 5.20},
]

# Two independently visible Bid/Ask snapshots from screenshots; not a spread distribution.
QUOTE_SAMPLES = [
    {"bid": 7301.9, "ask": 7302.0},
    {"bid": 7301.5, "ask": 7301.6},
]


def audit() -> dict:
    contract = MT5_SPEC["contract_size"]
    checked = []
    for trade in HISTORY_SAMPLE:
        move = trade["exit"] - trade["entry"]
        signed = move if trade["side"] == "BUY" else -move
        theoretical = signed * trade["volume"] * contract
        delta = trade["profit_usd"] - theoretical
        checked.append({**trade, "theoretical_gross_usd": round(theoretical, 2),
                        "difference_usd": round(delta, 2),
                        "pnl_consistent_with_contract_model": abs(delta) <= 0.011,
                        "commission_usd": None, "swap_usd": None})
    spreads = [round(q["ask"] - q["bid"], 10) for q in QUOTE_SAMPLES]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "source": "Manual transcription of user-provided MT5 specification, quote and history screenshots",
        "specification": MT5_SPEC,
        "history_sample": checked,
        "history_summary": {
            "closed_deals_sampled": len(checked),
            "gross_profit_usd": round(sum(t["profit_usd"] for t in checked), 2),
            "wins": sum(t["profit_usd"] > 0 for t in checked),
            "losses": sum(t["profit_usd"] < 0 for t in checked),
            "pnl_contract_model_consistent": all(t["pnl_consistent_with_contract_model"] for t in checked),
            "commission_deal_level": "UNKNOWN_BLANK_IN_SCREENSHOT",
            "swap_deal_level": "UNKNOWN_BLANK_IN_SCREENSHOT",
        },
        "spread_observations": {
            "samples": len(spreads), "price_units": spreads,
            "minimum": min(spreads), "maximum": max(spreads),
            "mean": round(sum(spreads) / len(spreads), 4),
            "interpretation": "Two snapshots only; not a session distribution or guaranteed fixed spread.",
        },
        "cost_gate": {
            "spread_observed_price_units": round(sum(spreads) / len(spreads), 4),
            "commission_price_units": None,
            "slippage_price_units": None,
            "round_trip_cost_price_units": None,
            "backtest_net_enabled": False,
            "reason": "Insufficient evidence for trade-level commission and slippage; spread sample is not a full cost model.",
        },
        "monetary_risk_gate": {
            "enabled": False,
            "reason": "MT5 reports tick_size=0.0 and tick_value=0; monetary tick conversion is not verified.",
        },
        "decision": "NO_TRADE",
    }


def main() -> None:
    report = audit()
    out = Path("DATA")
    out.mkdir(parents=True, exist_ok=True)
    target = out / "step_index_mt5_cost_audit.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(target), "decision": report["decision"],
                      "history_sample": report["history_summary"],
                      "cost_gate": report["cost_gate"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
