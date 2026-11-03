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
    # User-declared conversion: 0.10 USD per 0.1 index point at 0.10 lots.
    # This is kept separate from the broker-reported MT5 tick fields (both zero).
    "user_reported_tick_size_price_units": 0.1,
    "user_reported_tick_value_usd": 0.10,
    "user_reported_reference_volume_lots": 0.10,
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
    user_tick_size = MT5_SPEC["user_reported_tick_size_price_units"]
    user_tick_value = MT5_SPEC["user_reported_tick_value_usd"]
    reference_volume = MT5_SPEC["user_reported_reference_volume_lots"]
    usd_per_price_unit_at_reference_volume = user_tick_value / user_tick_size
    # Independently reconcile the user-declared conversion against closed deal P&L.
    conversion_checks = []
    for trade in HISTORY_SAMPLE:
        move = abs(trade["exit"] - trade["entry"])
        expected = (move / user_tick_size) * user_tick_value * (trade["volume"] / reference_volume)
        conversion_checks.append(abs(abs(trade["profit_usd"]) - expected) <= 0.011)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "source": "Manual transcription of user-provided MT5 specification, quote and history screenshots",
        "specification": MT5_SPEC,
        "user_declared_monetary_conversion": {
            "tick_price_units": user_tick_size,
            "tick_value_usd": user_tick_value,
            "reference_volume_lots": reference_volume,
            "usd_per_price_unit_at_reference_volume": round(usd_per_price_unit_at_reference_volume, 6),
            "usd_per_tick_per_lot": round(user_tick_value / reference_volume, 6),
            "history_pnl_crosscheck_all_eight_deals": all(conversion_checks),
            "evidence_status": "USER_DECLARED_AND_RECONCILED_WITH_TRANSCRIBED_HISTORY; NOT_BROKER_SPEC_VERIFIED",
        },
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
            "enabled": True,
            "basis": "USER_DECLARED_CONVERSION_CROSS_CHECKED_AGAINST_EIGHT_TRANSCRIBED_CLOSED_DEALS",
            "reference_volume_lots": reference_volume,
            "usd_per_tick": user_tick_value,
            "usd_per_price_unit": round(usd_per_price_unit_at_reference_volume, 6),
            "broker_tick_spec_verified": False,
            "limitations": "Use only as a provisional conversion for risk estimates. MT5 broker Tick size/value fields still display zero; trade-level commission and slippage remain unknown, so net backtest and executable cost validation remain disabled.",
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
