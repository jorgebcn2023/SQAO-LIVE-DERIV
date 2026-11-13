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
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from .step_index_quant import acceptance_gate, equity_stats
from .step_index_research import (
    GRANULARITY, atr_series, closed_candles, discover_step_index, ema_series,
    fetch_candles, rsi, _trend_cache, _cached_trend_at, STEP_INDEX_MARKET_MECHANICS,
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
    # Rank by observed out-of-sample hit rate first, then expectancy and PF.
    # Eligibility remains a separate evidence gate; ranking never implies a guarantee.
    candidates.sort(key=lambda x: (
        x["oos_net"]["win_rate"] if x["oos_net"]["win_rate"] is not None else -math.inf,
        x["oos_net"]["expectancy_r"] if x["oos_net"]["expectancy_r"] is not None else -math.inf,
        x["oos_net"]["profit_factor"] if x["oos_net"]["profit_factor"] is not None else -math.inf,
    ), reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank_by_oos_win_rate"] = rank
    eligible = next((x for x in candidates if x["gate"]["eligible"]), None)
    # Always surface the strongest observed OOS hit-rate candidate, even when it
    # fails the 70% gate. This is a research shortlist, never an automatic trade.
    best_observed = max(candidates, key=lambda x: (
        x["oos_net"]["win_rate"] if x["oos_net"]["win_rate"] is not None else -math.inf,
        x["oos_net"]["expectancy_r"] if x["oos_net"]["expectancy_r"] is not None else -math.inf,
        x["oos_net"]["profit_factor"] if x["oos_net"]["profit_factor"] is not None else -math.inf,
    ), default=None)
    return {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
            "read_only": True,
            "market_mechanics": STEP_INDEX_MARKET_MECHANICS,
            "performance_basis": "NET_AFTER_CONFIGURED_COSTS" if cost is not None else "GROSS_COSTS_NOT_CONFIGURED",
            "oos_net_is_gross_proxy": cost is None,
            "decision": "CANDIDATE_FOR_REVIEW" if eligible else "NO_TRADE",
            "selection_rule": "Rank all candidates by observed out-of-sample win rate descending; expectancy and profit factor are tie-breakers. The 70% eligibility gate is separate; no tuning on holdout.",
            "win_rate_definition": "Observed wins divided by evaluated OOS trades after the selected cost basis; descriptive historical frequency, not a guaranteed future outcome or next-trade probability.",
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


def build_table18(report: dict[str, Any]) -> dict[str, Any]:
    """Best observed OOS hit-rate candidate; historical stats never imply a live trade."""
    best = next((x for x in report.get("strategies", [])
                 if x.get("strategy") == report.get("best_observed_candidate")), None)
    if not best:
        return {"table": 18, "decision": "NO_TRADE", "status": "NO_EVALUABLE_CANDIDATE"}
    metrics = best.get("oos_net") or {}
    params = best.get("parameters") or {}
    strategy = best.get("strategy")
    rule = {
        "rsi_reversal": {
            "long": "RSI(14) de M5 cruza al alza 30: RSI previo <30 y RSI cerrado actual >=30",
            "short": "RSI(14) de M5 cruza a la baja 70: RSI previo >70 y RSI cerrado actual <=70",
            "filters": "Sin filtro M15/H1 en la regla evaluada; no añadir filtros nuevos sin rebacktest"
        },
        "breakout20_mtf": {
            "long": "Cierre M5 supera el máximo de las 20 velas M5 cerradas previas y EMA10 > EMA20; M15/H1 alineados",
            "short": "Cierre M5 rompe el mínimo de las 20 velas M5 cerradas previas y EMA10 < EMA20; M15/H1 alineados",
            "filters": "Confirmación de tendencia M15 y H1 en la misma dirección"
        },
        "ema_pullback_mtf": {
            "long": "EMA10 > EMA20; vela M5 previa cierra <= EMA10 y vela cerrada actual recupera por encima de EMA10; M15/H1 alineados",
            "short": "EMA10 < EMA20; vela M5 previa cierra >= EMA10 y vela cerrada actual cae por debajo de EMA10; M15/H1 alineados",
            "filters": "Confirmación de tendencia M15 y H1 en la misma dirección"
        }
    }.get(strategy, {})
    lo = metrics.get("wilson_95_low")
    hi = metrics.get("wilson_95_high")
    eligible = bool(best.get("gate", {}).get("eligible"))
    # This strategy lab has no live quote/trigger execution sheet for its top candidate.
    # Negative expectancy or unverified costs must never be converted into an executable order.
    blockers = []
    if not eligible:
        blockers.append("NO_SUPERA_FILTRO_ESTADISTICO_O_COSTES")
    if metrics.get("expectancy_r") is None or metrics.get("expectancy_r", 0) <= 0:
        blockers.append("EXPECTATIVA_OOS_NO_POSITIVA")
    if report.get("oos_net_is_gross_proxy"):
        blockers.append("COSTES_REALES_NO_CONFIGURADOS")
    return {
        "table": 18,
        "instrument": "Step Index 100",
        "symbol": report.get("symbol", {}).get("symbol", "stpRNG"),
        "selection": "Mayor efectividad observada OOS entre las estrategias predefinidas; desempate por expectativa y PF",
        "strategy": strategy,
        "historical_oos": {
            "trades": metrics.get("n"), "wins": metrics.get("wins"), "losses": metrics.get("losses"),
            "hit_rate": metrics.get("win_rate"), "wilson_95": [lo, hi],
            "expectancy_r": metrics.get("expectancy_r"), "profit_factor": metrics.get("profit_factor"),
            "max_drawdown_r": metrics.get("max_drawdown_r"),
            "performance_basis": report.get("performance_basis"),
            "is_gross_proxy": bool(report.get("oos_net_is_gross_proxy"))
        },
        "parameters": {
            "signal_timeframe": "M5", "rsi_period": 14 if strategy == "rsi_reversal" else None,
            "long_trigger": rule.get("long"), "short_trigger": rule.get("short"),
            "trend_filters": rule.get("filters"),
            "entry": "Apertura de la siguiente vela M5 después del cierre confirmado de la señal",
            "stop_loss": f"1.2 x ATR(14) M5 desde el precio real de entrada; debajo para LONG y encima para SHORT",
            "take_profit": f"{params.get('target_R', 1.5)}R desde la entrada, en dirección de la operación",
            "risk_reward": f"1:{params.get('target_R', 1.5)}",
            "atr_multiplier": params.get("stop_ATR", 1.2),
            "maximum_holding_period_m5_bars": params.get("horizon_m5", 5),
            "round_trip_cost_price_units": params.get("round_trip_cost_price")
        },
        "live_execution": {
            "decision": "CONDITIONAL_SETUP_REQUIRES_LIVE_CONFIRMATION" if eligible else "NO_TRADE",
            "direction": None, "entry_price": None, "stop_loss_price": None, "take_profit_price": None,
            "activation_utc": None, "expiry_utc": None,
            "status": "NO_LIVE_TRIGGER_OR_EXECUTABLE_NEXT_M5_QUOTE",
            "position_size_lots": None,
            "blockers": blockers or ["FALTA_CONFIRMACION_DE_TRIGGER_Y_COTIZACION_EJECUTABLE"]
        },
        "interpretation": "El porcentaje es la frecuencia histórica de aciertos de esta estrategia en la muestra OOS, no la probabilidad de la siguiente operación ni una garantía. Si la expectativa es negativa o faltan costes reales, NO_TRADE.",
        "read_only": True
    }


def write_table18_pdf(table18: dict[str, Any], path: Path) -> None:
    """Standalone execution sheet for the highest observed OOS hit-rate candidate."""
    styles = getSampleStyleSheet()
    rows = [["Campo", "Valor"]]
    hist, params, live = (table18.get("historical_oos", {}), table18.get("parameters", {}),
                          table18.get("live_execution", {}))
    pct = lambda x: "N/D" if x is None else f"{100*float(x):.2f}%"
    values = [
        ("Estrategia", table18.get("strategy")), ("Aciertos OOS", f'{hist.get("wins","N/D")}/{hist.get("trades","N/D")}'),
        ("Efectividad OOS", pct(hist.get("hit_rate"))),
        ("IC Wilson 95%", pct((hist.get("wilson_95") or [None,None])[0]) + " – " + pct((hist.get("wilson_95") or [None,None])[1])),
        ("Expectativa R", hist.get("expectancy_r")), ("Profit Factor", hist.get("profit_factor")),
        ("Señal LONG", params.get("long_trigger")), ("Señal SHORT", params.get("short_trigger")),
        ("Entrada", params.get("entry")), ("Stop Loss", params.get("stop_loss")),
        ("Take Profit", params.get("take_profit")), ("R:R", params.get("risk_reward")),
        ("Permanencia máxima", params.get("maximum_holding_period_m5_bars")),
        ("Dirección actual", live.get("direction")), ("Precio de entrada actual", live.get("entry_price")),
        ("SL/TP actuales", "NO DISPONIBLES: falta trigger y cotización ejecutable"),
        ("Decisión", live.get("decision")), ("Bloqueos", ", ".join(live.get("blockers", []))),
    ]
    rows.extend([[str(k), "N/D" if v is None else str(v)] for k,v in values])
    table = Table(rows, colWidths=[6*cm, 19*cm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#243447")),
                               ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                               ("GRID",(0,0),(-1,-1),0.5,colors.grey),
                               ("FONTSIZE",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"TOP")]))
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), title="SQAO Table 18")
    doc.build([Paragraph("SQAO — TABLA 18 · MEJOR EFECTIVIDAD OOS", styles["Title"]),
               Paragraph("Step Index 100 · READ-ONLY · Parámetros de la estrategia mejor clasificada", styles["Normal"]),
               Spacer(1, 12), table, Spacer(1, 12),
               Paragraph(table18.get("interpretation", ""), styles["BodyText"])])


def write_pdf(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), title="SQAO Step Index Strategy Lab")
    story = [Paragraph("SQAO — Step Index Strategy Lab", styles["Title"]),
             Paragraph(f"Generado UTC: {report['generated_at_utc']} | Símbolo: {report['symbol']['symbol']}",
                       styles["Normal"]), Spacer(1, 12),
             Paragraph(f"Decisión: {report['decision']}", styles["Heading2"]),
             Paragraph("Mecánica publicada Deriv: paso 0,1 por tick; probabilidades 50/50 y deriva publicada 0. Es metadato descriptivo, no tick_size/tick_value MT5 ni conversión monetaria.", styles["BodyText"]),
             Paragraph("Comparación cronológica fuera de muestra. " +
                       ("MÉTRICAS BRUTAS: no se configuraron costes round-trip; no deben interpretarse como rendimiento neto." if report.get("oos_net_is_gross_proxy") else "Métricas netas tras aplicar el coste round-trip configurado.") +
                       " No es una predicción ni garantiza resultados.",
                       styles["BodyText"]), Spacer(1, 12)]
    metric_suffix = " (bruto)" if report.get("oos_net_is_gross_proxy") else " (neto)"
    rows = [["Rango", "Estrategia", "Aciertos/N", "Efectividad OOS" + metric_suffix, "IC Wilson 95%", "Expectativa R" + metric_suffix, "PF" + metric_suffix, "DD máx R" + metric_suffix, "Elegible"]]
    for item in report["strategies"]:
        s = item["oos_net"]
        pct = lambda x: "N/D" if x is None else f"{100*x:.2f}%"
        num = lambda x: "N/D" if x is None or not math.isfinite(x) else f"{x:.3f}"
        ci = f"{pct(s['wilson_95_low'])}–{pct(s['wilson_95_high'])}"
        rows.append([str(item.get("rank_by_oos_win_rate", "N/D")), item["strategy"],
                     f'{s["wins"]}/{s["n"]}', pct(s["win_rate"]), ci,
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
    story.append(Paragraph("RANKING OOS POR EFECTIVIDAD OBSERVADA (SE MUESTRAN TODAS LAS CANDIDATAS, INCLUSO <70%)", styles["Heading2"]))
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
    story.extend([et, Spacer(1, 10)])
    table18 = report.get("table_18", {})
    story.append(Spacer(1, 10))
    story.append(Paragraph("TABLA 18 — MEJOR EFECTIVIDAD OOS OBSERVADA", styles["Heading2"]))
    h = table18.get("historical_oos", {})
    p = table18.get("parameters", {})
    live = table18.get("live_execution", {})
    pct = lambda x: "N/D" if x is None else f"{100*float(x):.2f}%"
    t18_rows = [
        ["Campo", "Resultado"],
        ["Estrategia seleccionada", str(table18.get("strategy") or "N/D")],
        ["Aciertos OOS", f'{h.get("wins", "N/D")} / {h.get("trades", "N/D")}'],
        ["Efectividad OOS observada", pct(h.get("hit_rate"))],
        ["IC Wilson 95%", pct((h.get("wilson_95") or [None,None])[0]) + " – " + pct((h.get("wilson_95") or [None,None])[1])],
        ["Expectativa OOS (R)", str(h.get("expectancy_r", "N/D"))],
        ["Profit Factor", str(h.get("profit_factor", "N/D"))],
        ["Regla LONG", str(p.get("long_trigger") or "N/D")],
        ["Regla SHORT", str(p.get("short_trigger") or "N/D")],
        ["Entrada", str(p.get("entry") or "N/D")],
        ["Stop Loss", str(p.get("stop_loss") or "N/D")],
        ["Take Profit", str(p.get("take_profit") or "N/D")],
        ["Máxima permanencia", str(p.get("maximum_holding_period_m5_bars", "N/D")) + " velas M5"],
        ["Estado operativo", str(live.get("decision", "NO_TRADE"))],
        ["Precios ejecutables", "NO DISPONIBLES — falta trigger y cotización M5 actual"],
        ["Bloqueos", ", ".join(live.get("blockers", []))],
    ]
    t18 = Table(t18_rows, colWidths=[6*cm, 19*cm], repeatRows=1)
    t18.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#243447")),
                             ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                             ("GRID",(0,0),(-1,-1),0.5,colors.grey),
                             ("FONTSIZE",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.extend([t18, Paragraph(table18.get("interpretation", ""), styles["BodyText"])])
    table17 = report.get("table_17", {})
    story.append(Paragraph("TABLA 17 — OPERACIÓN SCALPING MEJOR CLASIFICADA", styles["Heading2"]))
    fmt_price = lambda x: "NO DISPONIBLE" if x is None else f"{float(x):.2f}"
    fmt_pct = lambda x: "N/D" if x is None else f"{100*float(x):.2f}%"
    t17_rows = [
        ["Estrategia", "Dirección", "Entrada", "Stop Loss", "Take Profit", "Efectividad OOS", "Estado"],
        [str(table17.get("strategy") or "N/D"), str(table17.get("direction") or "N/D"),
         fmt_price(table17.get("entry")), fmt_price(table17.get("stop_loss")),
         fmt_price(table17.get("take_profit")), fmt_pct(table17.get("oos_win_rate")),
         str(table17.get("status") or "NO_TRADE")]
    ]
    t17 = Table(t17_rows, colWidths=[3.1*cm, 1.8*cm, 2.0*cm, 2.0*cm, 2.0*cm, 2.6*cm, 7.5*cm], repeatRows=1)
    t17.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#243447")),
                             ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                             ("GRID",(0,0),(-1,-1),0.5,colors.grey),
                             ("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story.extend([t17, Spacer(1, 5)])
    money = table17.get("provisional_monetary_scenarios", {})
    risk_usd, reward_usd = money.get("risk_usd", {}), money.get("reward_usd", {})
    money_rows = [["Volumen", "Riesgo teórico USD", "Beneficio teórico USD"],
                  ["0,10 lotes", str(risk_usd.get("0.1", "N/D")), str(reward_usd.get("0.1", "N/D"))],
                  ["0,20 lotes", str(risk_usd.get("0.2", "N/D")), str(reward_usd.get("0.2", "N/D"))]]
    mt = Table(money_rows, colWidths=[5*cm, 7*cm, 7*cm], repeatRows=1)
    mt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#243447")),
                            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                            ("GRID",(0,0),(-1,-1),0.5,colors.grey),
                            ("FONTSIZE",(0,0),(-1,-1),8)]))
    story.extend([Paragraph("RIESGO Y RECOMPENSA MONETARIA PROVISIONAL", styles["Heading3"]),
        mt, Paragraph("Conversión declarada por el usuario: 0,10 USD por cada 0,1 puntos a 0,10 lotes. Conciliada con 8 operaciones históricas; no verificada como Tick Value oficial MT5. Importes teóricos, antes de spread, comisión y slippage; no son beneficio neto ni autorización de ejecución.", styles["BodyText"]), Spacer(1, 5),
        Paragraph("IC Wilson 95%: " + "–".join(fmt_pct(x) for x in (table17.get("wilson95") or [None,None])) +
                  " · Expectativa R: " + ("N/D" if table17.get("expectancy_r") is None else f"{table17['expectancy_r']:.3f}") +
                  " · PF: " + ("N/D" if table17.get("profit_factor") is None else f"{table17['profit_factor']:.3f}") +
                  " · DD máximo R: " + ("N/D" if table17.get("max_drawdown_r") is None else f"{table17['max_drawdown_r']:.3f}"), styles["BodyText"]),
        Paragraph("Estadísticas de esta regla: " + str(table17.get("statistics_status", "N/D")) + ". No se atribuyen a esta señal las métricas de otra estrategia del Strategy Lab.", styles["BodyText"]),
        Paragraph("La entrada/SL/TP solo se publican como precios ejecutables si el detector confirma el disparador y la apertura de la siguiente vela M1 coincide exactamente con el epoch esperado. En otro caso se muestran NO DISPONIBLE y NO_TRADE; no se sustituye por el cierre histórico.", styles["BodyText"]), Spacer(1, 10),
        Paragraph("El ranking ordena por efectividad OOS observada; expectativa, PF e intervalo de confianza permiten contextualizarla. La efectividad es una frecuencia histórica de la muestra, no una garantía ni la probabilidad de la próxima operación. Si no supera los filtros o faltan costes reales, la decisión sigue siendo NO_TRADE.",
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
    detector_path = out / "step_index_scalping_v23.json"
    detector = {}
    if detector_path.is_file():
        try:
            detector = json.loads(detector_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            detector = {}
    setup = detector.get("setup", {}) if isinstance(detector, dict) else {}
    best = next((x for x in report.get("strategies", [])
                 if x.get("strategy") == report.get("best_observed_candidate")), None)
    metrics = best.get("oos_net", {}) if best else {}
    # Never attach Strategy Lab metrics to a different detector rule.
    # The live detector is a M5 pullback + M1 trigger; Strategy Lab candidates
    # (breakout20_mtf / ema_pullback_mtf / rsi_reversal) are separate rules.
    detector_rule = "m5_pullback_m1_trigger"
    same_rule_metrics = None  # No chronological OOS replay exists for detector_rule yet.
    # Provisional USD conversion supplied by the user and reconciled against
    # eight transcribed closed deals: 0.10 USD per 0.1 price unit at 0.10 lots.
    # This is not broker-published MT5 tick_value; never imply cost-net results.
    user_tick_size = 0.1
    user_tick_value_usd = 0.10
    reference_lots = 0.10
    def provisional_usd(distance, lots):
        if distance is None:
            return None
        return round((abs(float(distance)) / user_tick_size) * user_tick_value_usd * (lots / reference_lots), 2)
    entry_ref = setup.get("entry_price")
    stop_ref = setup.get("stop_loss")
    target_ref = setup.get("take_profit")
    stop_distance = abs(float(entry_ref) - float(stop_ref)) if entry_ref is not None and stop_ref is not None else None
    target_distance = abs(float(target_ref) - float(entry_ref)) if entry_ref is not None and target_ref is not None else None
    report["table_17"] = {
        "strategy": detector_rule,
        "direction": setup.get("direction"),
        "entry": setup.get("entry_price"),
        "stop_loss": setup.get("stop_loss"),
        "take_profit": setup.get("take_profit"),
        "stop_distance_price_units": stop_distance,
        "target_distance_price_units": target_distance,
        "provisional_monetary_scenarios": {
            "conversion": "0.10 USD per 0.1 price unit at 0.10 lots; user-declared and history-reconciled, not broker-spec verified",
            "volumes_lots": [0.10, 0.20],
            "risk_usd": {str(v): provisional_usd(stop_distance, v) for v in (0.10, 0.20)},
            "reward_usd": {str(v): provisional_usd(target_distance, v) for v in (0.10, 0.20)},
            "net_of_costs": False
        },
        "execution_price_confirmed": bool(setup.get("execution_price_confirmed")),
        "status": setup.get("status", "NO_TRADE — detector no disponible"),
        "oos_wins": None, "oos_trades": None,
        "oos_win_rate": None,
        "wilson95": [None, None],
        "expectancy_r": None,
        "profit_factor": None,
        "max_drawdown_r": None,
        "statistics_status": "N/A — no OOS backtest for this exact detector rule and parameter set",
        "separate_best_observed_candidate": report.get("best_observed_candidate"),
        "separate_best_observed_metrics": metrics,
        "price_source": "Deriv current M1 candle open with exact epoch match" if setup.get("execution_price_confirmed") else "No verified next-M1 open; no executable prices"
    }
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
    report["table_18"] = build_table18(report)
    write_pdf(report, pdf_path)
    table18_pdf = out / "step_index_table18.pdf"
    write_table18_pdf(report["table_18"], table18_pdf)
    print(json.dumps({"symbol": report["symbol"], "decision": report["decision"],
                      "strategies": [{"name": x["strategy"], "oos_n": x["oos_n"],
                                      "win_rate": x["oos_net"]["win_rate"],
                                      "expectancy_r": x["oos_net"]["expectancy_r"],
                                      "profit_factor": x["oos_net"]["profit_factor"],
                                      "eligible": x["gate"]["eligible"]} for x in report["strategies"]],
                      "pdf": str(pdf_path), "json": str(json_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
