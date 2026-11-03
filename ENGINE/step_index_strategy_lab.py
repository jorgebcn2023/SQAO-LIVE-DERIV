"""Compare a small, predeclared set of Step Index strategies on a chronological holdout.

Research only. Parameters are fixed in code; this module does not optimize for a target
win rate and never places orders. Run with: python -m ENGINE.step_index_strategy_lab
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from .step_index_quant import acceptance_gate, equity_stats
from .step_index_research import (
    GRANULARITY, atr_series, closed_candles, discover_step_index, ema_series,
    fetch_candles, rsi, _trend_cache, _cached_trend_at,
)


def _rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for i in range(period, len(closes)):
        out[i] = rsi(closes[: i + 1], period)
    return out


def _direction_at(cache: tuple[list[int], list[float | None], list[float | None]], epoch: int) -> str | None:
    """Return trend using completed candles only; cached close epochs respect each timeframe."""
    return _cached_trend_at(cache, epoch)


def _signal(name: str, i: int, rows: list[dict[str, Any]],
            closes: list[float], e10: list[float | None], e20: list[float | None],
            rsi_values: list[float | None]) -> str | None:
    if i < 40 or e10[i] is None or e20[i] is None:
        return None
    fast, slow = e10[i], e20[i]
    if name == "breakout20_mtf":
        previous = rows[i - 20:i]
        if closes[i] > max(float(x["high"]) for x in previous) and fast > slow:
            return "LONG"
        if closes[i] < min(float(x["low"]) for x in previous) and fast < slow:
            return "SHORT"
    elif name == "ema_pullback_mtf":
        if e10[i - 1] is None:
            return None
        if fast > slow and closes[i - 1] <= e10[i - 1] and closes[i] > fast:
            return "LONG"
        if fast < slow and closes[i - 1] >= e10[i - 1] and closes[i] < fast:
            return "SHORT"
    elif name == "rsi_reversal":
        now, before = rsi_values[i], rsi_values[i - 1]
        if now is None or before is None:
            return None
        if before < 30 <= now:
            return "LONG"
        if before > 70 >= now:
            return "SHORT"
    return None


def evaluate_strategy(
    name: str, m5: list[dict[str, Any]], m15: list[dict[str, Any]], h1: list[dict[str, Any]],
    *, train_fraction: float = 0.70, horizon: int = 5, rr: float = 1.5,
    atr_mult: float = 1.2, round_trip_cost_price: float | None = None,
) -> dict[str, Any]:
    """Evaluate one fixed rule with next-bar open entry and conservative stop-first ties."""
    if not 0.5 < train_fraction < 0.95:
        raise ValueError("train_fraction must be between 0.5 and 0.95")
    if len(m5) < 100:
        raise ValueError("At least 100 M5 candles are required")
    closes = [float(r["close"]) for r in m5]
    e10, e20 = ema_series(closes, 10), ema_series(closes, 20)
    atrs, rsis = atr_series(m5, 14), _rsi_series(closes)
    split = int(len(m5) * train_fraction)
    m15_cache = _trend_cache(m15, "M15")
    h1_cache = _trend_cache(h1, "H1")
    trades: list[dict[str, Any]] = []
    next_allowed = 40
    for i in range(40, len(m5) - horizon - 1):
        if i < next_allowed:
            continue
        direction = _signal(name, i, m5, closes, e10, e20, rsis)
        if direction is None:
            continue
        decision_epoch = int(m5[i]["epoch"]) + GRANULARITY["M5"]
        if name != "rsi_reversal":
            if _direction_at(m15_cache, decision_epoch) != direction or _direction_at(h1_cache, decision_epoch) != direction:
                continue
        a = atrs[i]
        if a is None or a <= 0:
            continue
        risk = a * atr_mult
        entry_bar = m5[i + 1]
        entry = float(entry_bar["open"])
        stop = entry - risk if direction == "LONG" else entry + risk
        target = entry + rr * risk if direction == "LONG" else entry - rr * risk
        last_j = min(len(m5) - 1, i + horizon)
        gross_r = 0.0
        exit_reason = "TIME_EXIT"
        for j in range(i + 1, last_j + 1):
            high, low = float(m5[j]["high"]), float(m5[j]["low"])
            stop_hit = low <= stop if direction == "LONG" else high >= stop
            target_hit = high >= target if direction == "LONG" else low <= target
            if stop_hit:
                gross_r, exit_reason = -1.0, "STOP" if not target_hit else "STOP_AND_TARGET_STOP_FIRST"
                break
            if target_hit:
                gross_r, exit_reason = rr, "TARGET"
                break
            if j == last_j:
                move = (float(m5[j]["close"]) - entry) * (1 if direction == "LONG" else -1)
                gross_r = max(-1.0, min(rr, move / risk))
        cost_r = float(round_trip_cost_price) / risk if round_trip_cost_price is not None else 0.0
        trades.append({"signal_epoch": decision_epoch, "direction": direction, "entry": entry,
                       "risk_price": risk, "gross_r": gross_r, "cost_r": cost_r,
                       "net_r": gross_r - cost_r, "exit_reason": exit_reason,
                       "sample": "train" if i < split else "out_of_sample"})
        next_allowed = last_j + 1
    train = [t for t in trades if t["sample"] == "train"]
    oos = [t for t in trades if t["sample"] == "out_of_sample"]
    gross = equity_stats([t["gross_r"] for t in oos])
    net = equity_stats([t["net_r"] for t in oos])
    gate = acceptance_gate(net, min_trades=int(os.getenv("SQAO_STEP_MIN_OOS_TRADES", "100")),
                           target_win_rate=float(os.getenv("SQAO_STEP_TARGET_WIN_RATE", "0.70")),
                           require_costs=True, costs_supplied=round_trip_cost_price is not None)
    return {"strategy": name, "parameters": {"train_fraction": train_fraction, "horizon_m5": horizon,
            "target_R": rr, "stop_ATR": atr_mult, "round_trip_cost_price": round_trip_cost_price},
            "n_trades_total": len(trades), "train_n": len(train), "oos_n": len(oos),
            "oos_gross": gross, "oos_net": net, "gate": gate, "trades": trades}


def build_report(frames: dict[str, list[dict[str, Any]]], symbol: dict[str, str],
                 cost: float | None = None) -> dict[str, Any]:
    m5, m15, h1 = frames["M5"], frames["M15"], frames["H1"]
    candidates = [
        evaluate_strategy("breakout20_mtf", m5, m15, h1, round_trip_cost_price=cost),
        evaluate_strategy("ema_pullback_mtf", m5, m15, h1, round_trip_cost_price=cost),
        evaluate_strategy("rsi_reversal", m5, m15, h1, round_trip_cost_price=cost),
    ]
    candidates.sort(key=lambda x: (
        bool(x["gate"]["eligible"]),
        x["oos_net"]["expectancy_r"] if x["oos_net"]["expectancy_r"] is not None else -math.inf,
        x["oos_net"]["profit_factor"] if x["oos_net"]["profit_factor"] is not None else -math.inf,
    ), reverse=True)
    eligible = next((x for x in candidates if x["gate"]["eligible"]), None)
    # Always surface the strongest observed OOS hit-rate candidate, even when it
    # fails the 70% gate. This is a research shortlist, never an automatic trade.
    best_observed = max(candidates, key=lambda x: (
        x["oos_net"]["win_rate"] if x["oos_net"]["win_rate"] is not None else -math.inf,
        x["oos_net"]["expectancy_r"] if x["oos_net"]["expectancy_r"] is not None else -math.inf,
        x["oos_net"]["profit_factor"] if x["oos_net"]["profit_factor"] is not None else -math.inf,
    ), default=None)
    return {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
            "read_only": True, "decision": "CANDIDATE_FOR_REVIEW" if eligible else "NO_TRADE",
            "selection_rule": "Highest observed OOS win rate first; expectancy and profit factor as tie-breakers. Eligibility gate reported separately; no tuning on holdout.",
            "best_observed_candidate": best_observed["strategy"] if best_observed else None,
            "best_observed_candidate_metrics": best_observed["oos_net"] if best_observed else None,
            "best_observed_candidate_parameters": best_observed["parameters"] if best_observed else None,
            "execution_sheet": {
                "status": "CONDITIONAL_ONLY_NO_LIVE_ENTRY_PRICE",
                "volume_scenarios_lots": [0.10, 0.20],
                "entry": "Next M5 candle open after a fully closed and confirmed signal; refresh Bid/Ask before sending any manual order.",
                "stop": "1.2 x M5 ATR(14) from entry; strategy-specific stop logic remains in the tested rule.",
                "target": "1.5R from entry",
                "maximum_holding_period_m5_bars": 5,
                "spread_observed_price_units": 0.1,
                "round_trip_cost_price_units": cost,
                "commission_and_slippage": "Not supplied; not assumed to be zero.",
                "live_entry_sl_tp": None,
                "warning": "No live entry, SL or TP prices are emitted unless a current closed-candle trigger and executable quote are both available."
            },
            "strategies": candidates,
            "limitations": ["Small fixed candidate set; results are not proof of future performance.",
                           "Best observed candidate may still have negative expectancy or fail the 70% gate.",
                           "No candidate is eligible without realistic round-trip costs.",
                           "No order placement or live trading is implemented."]}


def write_pdf(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), title="SQAO Step Index Strategy Lab")
    story = [Paragraph("SQAO — Step Index Strategy Lab", styles["Title"]),
             Paragraph(f"Generado UTC: {report['generated_at_utc']} | Símbolo: {report['symbol']['symbol']}",
                       styles["Normal"]), Spacer(1, 12),
             Paragraph(f"Decisión: {report['decision']}", styles["Heading2"]),
             Paragraph("Comparación cronológica fuera de muestra. No es una predicción ni garantiza resultados.",
                       styles["BodyText"]), Spacer(1, 12)]
    rows = [["Estrategia", "N OOS", "Acierto", "IC Wilson 95%", "Expectativa R", "PF", "DD máx R", "Elegible"]]
    for item in report["strategies"]:
        s = item["oos_net"]
        pct = lambda x: "N/D" if x is None else f"{100*x:.2f}%"
        num = lambda x: "N/D" if x is None or not math.isfinite(x) else f"{x:.3f}"
        ci = f"{pct(s['wilson_95_low'])}–{pct(s['wilson_95_high'])}"
        rows.append([item["strategy"], str(item["oos_n"]), pct(s["win_rate"]), ci,
                     num(s["expectancy_r"]), num(s["profit_factor"]), num(s["max_drawdown_r"]),
                     "SÍ" if item["gate"]["eligible"] else "NO"])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243447")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("FONTSIZE", (0, 0), (-1, -1), 8),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#edf2f7")])]))
    story.extend([table, Spacer(1, 12)])
    best_name = report.get("best_observed_candidate")
    best = next((x for x in report["strategies"] if x["strategy"] == best_name), None)
    story.append(Paragraph("MEJOR CANDIDATA OBSERVADA (SE MUESTRA AUNQUE SEA <70%)", styles["Heading2"]))
    if best is None:
        story.append(Paragraph("No hay una candidata evaluable con los datos disponibles.", styles["BodyText"]))
    else:
        s = best["oos_net"]
        pct = lambda x: "N/D" if x is None else f"{100*x:.2f}%"
        num = lambda x: "N/D" if x is None or not math.isfinite(x) else f"{x:.3f}"
        story.append(Paragraph(
            f"Estrategia: {best['strategy']} · Muestra OOS: {best['oos_n']} · "
            f"Acierto observado: {pct(s['win_rate'])} · IC Wilson 95%: "
            f"{pct(s['wilson_95_low'])}–{pct(s['wilson_95_high'])} · "
            f"Expectativa: {num(s['expectancy_r'])} R · PF: {num(s['profit_factor'])}. "
            f"Puerta 70%: {'APROBADA' if best['gate']['eligible'] else 'NO SUPERADA'}.",
            styles["BodyText"]))
        story.append(Paragraph(
            "Parámetros evaluados: entrada en apertura de la siguiente vela M5; "
            f"objetivo {best['parameters']['target_R']} R; stop {best['parameters']['stop_ATR']} x ATR(14); "
            f"horizonte máximo {best['parameters']['horizon_m5']} velas M5. "
            "La regla concreta de entrada depende de la estrategia seleccionada y de sus filtros M15/H1.",
            styles["BodyText"]))
    sheet = report.get("execution_sheet", {})
    story.append(Spacer(1, 8))
    story.append(Paragraph("FICHA DE EJECUCIÓN CONDICIONAL", styles["Heading2"]))
    exec_rows = [
        ["Campo", "Valor"],
        ["Estado", sheet.get("status", "N/D")],
        ["Volúmenes de referencia", ", ".join(str(x) for x in sheet.get("volume_scenarios_lots", [])) + " lotes"],
        ["Entrada", sheet.get("entry", "N/D")],
        ["Stop", sheet.get("stop", "N/D")],
        ["Objetivo", sheet.get("target", "N/D")],
        ["Spread observado", str(sheet.get("spread_observed_price_units", "N/D")) + " unidades de precio"],
        ["Coste round-trip configurado", str(sheet.get("round_trip_cost_price_units", "NO CONFIGURADO"))],
        ["Comisión / deslizamiento", sheet.get("commission_and_slippage", "N/D")],
        ["Precios actuales de entrada/SL/TP", "NO DISPONIBLES: falta trigger y cotización ejecutable"]
    ]
    et = Table(exec_rows, colWidths=[6*cm, 19*cm], repeatRows=1)
    et.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#243447")),
                            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                            ("GRID",(0,0),(-1,-1),0.5,colors.grey),
                            ("FONTSIZE",(0,0),(-1,-1),8),
                            ("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.extend([et, Spacer(1, 10),
        Paragraph("La mejor candidata se informa por su tasa de acierto OOS observada, con expectativa, PF e intervalo de confianza para evitar elegir una tasa alta pero económicamente negativa. No equivale a una probabilidad predictiva ni a una recomendación automática. Si no supera los filtros o faltan costes reales, la decisión sigue siendo NO_TRADE.",
                  styles["BodyText"]),
        Paragraph("Regla de seguridad: si no supera todos los filtros, no operar.", styles["Heading3"])])
    doc.build(story)


async def run() -> dict[str, Any]:
    symbol = await discover_step_index()
    counts = {"M5": int(os.getenv("SQAO_LAB_M5_CANDLES", "20000")),
              "M15": int(os.getenv("SQAO_LAB_M15_CANDLES", "7000")),
              "H1": int(os.getenv("SQAO_LAB_H1_CANDLES", "2500"))}
    frames = {}
    for tf, count in counts.items():
        rows = await fetch_candles(symbol["symbol"], tf, count)
        frames[tf] = closed_candles(rows, tf)
    if min(len(frames[x]) for x in ("M5", "M15", "H1")) < 100:
        raise RuntimeError("Insufficient closed candle history for strategy comparison")
    raw_cost = os.getenv("SQAO_STEP_ROUND_TRIP_COST_PRICE", "").strip()
    cost = float(raw_cost) if raw_cost else None
    if cost is not None and (not math.isfinite(cost) or cost < 0):
        raise ValueError("SQAO_STEP_ROUND_TRIP_COST_PRICE must be non-negative")
    return build_report(frames, symbol, cost)


def main() -> None:
    report = asyncio.run(run())
    out = Path(os.getenv("SQAO_DATA_DIR", "DATA"))
    out.mkdir(parents=True, exist_ok=True)
    json_path, pdf_path = out / "step_index_strategy_lab.json", out / "step_index_strategy_lab.pdf"
    def json_safe(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [json_safe(v) for v in value]
        return value
    json_path.write_text(json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_pdf(report, pdf_path)
    print(json.dumps({"symbol": report["symbol"], "decision": report["decision"],
                      "strategies": [{"name": x["strategy"], "oos_n": x["oos_n"],
                                      "win_rate": x["oos_net"]["win_rate"],
                                      "expectancy_r": x["oos_net"]["expectancy_r"],
                                      "profit_factor": x["oos_net"]["profit_factor"],
                                      "eligible": x["gate"]["eligible"]} for x in report["strategies"]],
                      "pdf": str(pdf_path), "json": str(json_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
