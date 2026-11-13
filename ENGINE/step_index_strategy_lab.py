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
from .chart_indicator_audit import build_mtf_audit
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


def historical_oos_levels(trade: dict[str, Any], target_r: float) -> dict[str, Any] | None:
    """Build auditable historical entry/SL/TP from one recorded OOS trade."""
    try:
        entry = float(trade["entry"])
        risk = float(trade["risk_price"])
        rr = float(target_r)
        direction = str(trade["direction"]).upper()
        epoch = int(trade["signal_epoch"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (direction not in {"LONG", "SHORT"} or not all(math.isfinite(x) for x in (entry, risk, rr))
            or entry <= 0 or risk <= 0 or rr <= 0 or epoch <= 0
            or trade.get("sample") != "out_of_sample"):
        return None
    sign = 1.0 if direction == "LONG" else -1.0
    return {
        "direction": direction, "entry": entry,
        "stop_loss": entry - sign * risk,
        "take_profit": entry + sign * risk * rr,
        "risk_price_units": risk, "reward_price_units": risk * rr,
        "risk_reward": f"1:{rr:g}", "signal_epoch": epoch,
        "signal_time_utc": datetime.fromtimestamp(epoch, timezone.utc).isoformat(),
        "entry_source": "Deriv M5 next-candle open recorded by chronological OOS backtest",
        "stop_target_source": "ATR(14) risk distance recorded by backtest; target_R strategy parameter",
        "exit_reason": trade.get("exit_reason"), "realized_R": trade.get("net_r"),
        "sample": "out_of_sample", "is_current_signal": False,
    }


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
    story.append(Paragraph("TABLA 18 — RANKING HISTÓRICO OOS POR EFECTIVIDAD OBSERVADA (INCLUYE CANDIDATAS INFERIORES AL 70%)", styles["Heading2"]))
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
    t17_score = report.get("chart_indicator_audit", {}).get("score", {})
    story.append(Paragraph(
        "Confluencia técnica agrupada (descriptiva, no probabilidad): LONG " +
        f"{t17_score.get('long','N/D')}/{t17_score.get('max_per_side','N/D')} ({t17_score.get('long_pct',0):.1f}%) · " +
        "SHORT " + f"{t17_score.get('short','N/D')}/{t17_score.get('max_per_side','N/D')} ({t17_score.get('short_pct',0):.1f}%) · " +
        str(t17_score.get("decision", "N/D")), styles["BodyText"]))
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
    table18 = report.get("table_18", {})
    # Safe numeric display for conditional levels; blocked scenarios stay unpublished.
    fmt_price = lambda x: "NOT PUBLISHED — NO_TRADE" if x is None else f"{float(x):.2f}"
    story.append(Spacer(1, 10))
    story.append(Paragraph("TABLA 18 — FICHA DE LA MEJOR CANDIDATA HISTÓRICA", styles["Heading2"]))
    t18_rows = [
        ["Campo", "Resultado"],
        ["Estrategia", str(table18.get("strategy", "N/D"))],
        ["Temporalidad / filtros", str(table18.get("timeframe", "M5 + filtros M15/H1"))],
        ["Periodo OOS", str(table18.get("oos_period_utc", "N/D"))],
        ["Operaciones OOS", str(table18.get("oos_trades", "N/D"))],
        ["Ganadoras / perdedoras", f'{table18.get("wins", "N/D")} / {table18.get("losses", "N/D")}'],
        ["Efectividad observada", pct(table18.get("win_rate"))],
        ["IC Wilson 95%", f'{pct(table18.get("wilson_95_low"))}–{pct(table18.get("wilson_95_high"))}'],
        ["Expectativa", num(table18.get("expectancy_r")) + " R/trade"],
        ["Profit Factor", num(table18.get("profit_factor"))],
        ["Drawdown máximo", num(table18.get("max_drawdown_r")) + " R"],
        ["Base de métricas", str(table18.get("performance_basis", "N/D"))],
        ["Puerta estadística 70%", str(table18.get("eligibility", "N/D"))],
        ["Dictamen", str(table18.get("status", "N/D"))],
        ["Escenario actual", str((table18.get("scenario") or {}).get("status", "NOT_PUBLISHED_NO_TRADE"))],
        ["Dirección escenario", str((table18.get("scenario") or {}).get("direction") or "NOT PUBLISHED — NO_TRADE")],
        ["Apertura escenario", fmt_price((table18.get("scenario") or {}).get("entry"))],
        ["Stop Loss escenario", fmt_price((table18.get("scenario") or {}).get("stop_loss"))],
        ["Take Profit escenario", fmt_price((table18.get("scenario") or {}).get("take_profit"))],
        ["Riesgo / objetivo", (num((table18.get("scenario") or {}).get("risk_price_units")) + " / " +
                               num((table18.get("scenario") or {}).get("reward_price_units")) + " puntos")],
        ["Risk/Reward", str((table18.get("scenario") or {}).get("risk_reward") or "N/D")],
        ["Fuente de precios", str((table18.get("scenario") or {}).get("source", "N/D"))],
        ["Ejemplo OOS histórico (no señal actual)", "—"],
        ["Dirección histórica", str((table18.get("historical_example_oos_trade") or {}).get("direction", "N/D"))],
        ["Apertura histórica", fmt_price((table18.get("historical_example_oos_trade") or {}).get("entry"))],
        ["Stop Loss histórico", fmt_price((table18.get("historical_example_oos_trade") or {}).get("stop_loss"))],
        ["Take Profit histórico", fmt_price((table18.get("historical_example_oos_trade") or {}).get("take_profit"))],
        ["Fecha/hora de señal histórica UTC", str((table18.get("historical_example_oos_trade") or {}).get("signal_time_utc", "N/D"))],
        ["Origen entrada / SL / TP", str((table18.get("historical_example_oos_trade") or {}).get("entry_source", "N/D")) + " / " + str((table18.get("historical_example_oos_trade") or {}).get("stop_target_source", "N/D"))],
    ]
    audit = report.get("chart_indicator_audit", {})
    score = audit.get("score", {})
    t18_rows.extend([
        ["Confluencia MTF LONG (puntos / máximo)", f"{score.get('long', 'N/D')} / {score.get('max_per_side', 'N/D')} ({score.get('long_pct', 0):.1f}%)"],
        ["Confluencia MTF SHORT (puntos / máximo)", f"{score.get('short', 'N/D')} / {score.get('max_per_side', 'N/D')} ({score.get('short_pct', 0):.1f}%)"],
        ["Sesgo de confluencia (no probabilidad)", str(score.get("decision", "N/D"))],
        ["Método de puntuación", str(score.get("method", "N/D"))],
    ])
    for tf in ("H4", "H1", "M15", "M5", "M1"):
        x = audit.get("timeframes", {}).get(tf, {})
        t18_rows.append([f"Indicadores {tf}", "EMA9/20/50="+str(x.get("ema_stack","N/D"))+
            "; RSI14="+str(x.get("rsi14","N/D"))+"; ATR14="+str(x.get("atr14","N/D"))+
            "; MACD hist="+str(x.get("macd_histogram","N/D"))+
            "; BB %B="+str(x.get("bollinger20_percent_b","N/D"))+
            "; ADX/+DI/-DI="+str(x.get("adx14","N/D"))+"/"+str(x.get("plus_di14","N/D"))+"/"+str(x.get("minus_di14","N/D"))+
            "; Stoch K/D="+str(x.get("stochastic9_k","N/D"))+"/"+str(x.get("stochastic9_d","N/D"))])
    t18 = Table(t18_rows, colWidths=[6*cm, 19*cm], repeatRows=1)
    t18.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#243447")),
                             ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                             ("GRID",(0,0),(-1,-1),0.5,colors.grey),
                             ("FONTSIZE",(0,0),(-1,-1),8),
                             ("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(t18)
    story.append(Paragraph("La efectividad es una frecuencia histórica OOS y no representa la probabilidad de la próxima operación. Si no se configuraron costes round-trip, los resultados son brutos y no pueden presentarse como netos.", styles["BodyText"]))
    audit = report.get("chart_indicator_audit", {})
    score = audit.get("score", {})
    story.append(Spacer(1, 10))
    story.append(Paragraph("AUDITORÍA INTEGRAL DE INDICADORES MTF — M1/M5/M15/H1/H4", styles["Heading2"]))
    story.append(Paragraph("Votos agrupados sin doble contabilización: tendencia EMA 9/20/50; momentum MACD(12,26,9); osciladores RSI(14)+Stochastic(9,3,3) en una sola familia; fuerza ADX(14)+DI. Bollinger(20,2) y ATR(14) son diagnósticos, no votos direccionales. Los paneles sin etiqueta se declaran no identificables.", styles["BodyText"]))
    story.append(Paragraph(f"Confluencia descriptiva: LONG {score.get('long','N/D')}/{score.get('max_per_side','N/D')} ({score.get('long_pct',0):.1f}%) · SHORT {score.get('short','N/D')}/{score.get('max_per_side','N/D')} ({score.get('short_pct',0):.1f}%) · {score.get('decision','N/D')}", styles["BodyText"]))
    audit_rows = [["TF","Cierre","EMA9","EMA20","EMA50","RSI14","ATR14","MACD hist","BB %B","ADX14","+DI","-DI","Stoch K/D","Voto L/S"]]
    for tf in ("H4", "H1", "M15", "M5", "M1"):
        x = audit.get("timeframes", {}).get(tf, {})
        v = x.get("group_votes", {})
        n = lambda z: "N/D" if z is None else f"{float(z):.3f}"
        audit_rows.append([tf,n(x.get("last_close")),n(x.get("ema9")),n(x.get("ema20")),n(x.get("ema50")),
            n(x.get("rsi14")),n(x.get("atr14")),n(x.get("macd_histogram")),n(x.get("bollinger20_percent_b")),
            n(x.get("adx14")),n(x.get("plus_di14")),n(x.get("minus_di14")),
            n(x.get("stochastic9_k"))+"/"+n(x.get("stochastic9_d")),
            str(sum(1 for z in v.values() if z == "LONG"))+"/"+str(sum(1 for z in v.values() if z == "SHORT"))])
    audit_table = Table(audit_rows, repeatRows=1)
    audit_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#243447")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.35,colors.grey),
        ("FONTSIZE",(0,0),(-1,-1),6),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story.append(audit_table)
    story.append(Paragraph("Puntuación por familias (orden: tendencia / MACD / RSI+Stochastic / ADX+DI): " + " · ".join(
        tf+": "+"/".join(str(audit.get("confluence",{}).get(tf,{}).get(k,"N/D")) for k in ("long_groups","short_groups"))
        for tf in ("H4","H1","M15","M5","M1")), styles["BodyText"]))
    story.append(Paragraph("Los indicadores no visibles o sin nombre en las capturas no se adivinan ni se puntúan. La puntuación de confluencia no es una probabilidad calibrada ni una estadística OOS.", styles["BodyText"]))
    doc.build(story)


async def run() -> dict[str, Any]:
    symbol = await discover_step_index()
    counts = {"M1": int(os.getenv("SQAO_LAB_M1_CANDLES", "30000")),
              "M5": int(os.getenv("SQAO_LAB_M5_CANDLES", "20000")),
              "M15": int(os.getenv("SQAO_LAB_M15_CANDLES", "7000")),
              "H1": int(os.getenv("SQAO_LAB_H1_CANDLES", "2500")),
              "H4": int(os.getenv("SQAO_LAB_H4_CANDLES", "1000"))}
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
    report = build_report(frames, symbol, cost)
    report["chart_indicator_audit"] = build_mtf_audit(frames)
    return report


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
        "price_source": "Deriv current M1 candle open with exact epoch match" if setup.get("execution_price_confirmed") else "No verified next-M1 open; no executable prices",
        "indicator_confluence": report.get("chart_indicator_audit", {}).get("score"),
        "indicator_timeframes": report.get("chart_indicator_audit", {}).get("timeframes")
    }
    # Table 18 is the strongest historical OOS candidate, separate from live-detector Table 17.
    # Dates are derived only from the actual OOS trades returned by the fixed-rule replay.
    oos_trades = [t for t in (best.get("trades", []) if best else [])
                  if t.get("sample") == "out_of_sample"]
    first_epoch = min((int(t["signal_epoch"]) for t in oos_trades), default=None)
    last_epoch = max((int(t["signal_epoch"]) for t in oos_trades), default=None)
    period = "N/D"
    if first_epoch is not None and last_epoch is not None:
        period = (datetime.fromtimestamp(first_epoch, timezone.utc).isoformat() +
                  " — " + datetime.fromtimestamp(last_epoch, timezone.utc).isoformat())
    best_stats = best.get("oos_net", {}) if best else {}
    best_params = best.get("parameters", {}) if best else {}
    # A representative historical OOS trade supplies real numeric entry/SL/TP.
    # Entry is the next M5 candle open recorded by the backtest; SL/TP are
    # reconstructed from its recorded ATR risk distance and fixed target_R.
    # This is explicitly historical evidence, never a current live signal.
    historical_trade = max(oos_trades, key=lambda t: int(t.get("signal_epoch", 0)), default=None)
    historical_example = historical_oos_levels(historical_trade, float(best_params.get("target_R", 1.5))) if historical_trade else None
    report["table_18"] = {
        "purpose": "Best observed historical strategy from the predeclared Strategy Lab candidates; independent of live detector Table 17",
        "ranking_basis": "OOS observed win rate descending; expectancy and profit factor as tie-breakers",
        "strategy": best.get("strategy") if best else None,
        "rank": best.get("rank_by_oos_win_rate") if best else None,
        "timeframe": "M5 + closed-candle M15/H1 filters",
        "parameters": best_params,
        "oos_period_utc": period,
        "oos_start_epoch": first_epoch,
        "oos_end_epoch": last_epoch,
        "oos_trades": best_stats.get("n"),
        "wins": best_stats.get("wins"),
        "losses": best_stats.get("losses"),
        "win_rate": best_stats.get("win_rate"),
        "wilson_95_low": best_stats.get("wilson_95_low"),
        "wilson_95_high": best_stats.get("wilson_95_high"),
        "expectancy_r": best_stats.get("expectancy_r"),
        "profit_factor": best_stats.get("profit_factor"),
        "max_drawdown_r": best_stats.get("max_drawdown_r"),
        "performance_basis": report.get("performance_basis"),
        "eligibility": "PASS" if best and best.get("gate", {}).get("eligible") else "FAIL — 70% gate not met or costs not verified",
        "status": "CANDIDATA HISTÓRICA PARA REVISIÓN" if best else "SIN CANDIDATA EVALUABLE",
        "historical_example_oos_trade": historical_example,
        "not_a_live_signal": True,
        # Prices are sourced only from the exact-epoch Deriv M1 open in the v23
        # detector. Screenshots are never treated as an exact OHLC price source.
        # Publish levels only if both the OOS candidate and current trigger pass.
        "scenario": {
            "direction": setup.get("direction") if best and best.get("gate", {}).get("eligible")
                         and setup.get("execution_price_confirmed") else None,
            "entry": setup.get("entry_price") if best and best.get("gate", {}).get("eligible")
                     and setup.get("execution_price_confirmed") else None,
            "stop_loss": setup.get("stop_loss") if best and best.get("gate", {}).get("eligible")
                         and setup.get("execution_price_confirmed") else None,
            "take_profit": setup.get("take_profit") if best and best.get("gate", {}).get("eligible")
                           and setup.get("execution_price_confirmed") else None,
            "risk_price_units": (setup.get("execution_levels") or {}).get("risk_price_units")
                                if best and best.get("gate", {}).get("eligible")
                                and setup.get("execution_price_confirmed") else None,
            "reward_price_units": (setup.get("execution_levels") or {}).get("reward_price_units")
                                  if best and best.get("gate", {}).get("eligible")
                                  and setup.get("execution_price_confirmed") else None,
            "risk_reward": (setup.get("execution_levels") or {}).get("risk_reward")
                           if best and best.get("gate", {}).get("eligible")
                           and setup.get("execution_price_confirmed") else None,
            "source": "Deriv closed M1 trigger + exact next-M1 candle open; ATR14 M1",
            "trigger_epoch": setup.get("decision_epoch"),
            "entry_epoch": setup.get("decision_epoch") if setup.get("execution_price_confirmed") else None,
            "status": "CONDITIONAL_SCENARIO_ONLY" if best and best.get("gate", {}).get("eligible")
                      and setup.get("execution_price_confirmed") else "NOT_PUBLISHED_NO_TRADE",
            "visual_screenshots_used_as_price_source": False
        },
        "indicator_confluence": report.get("chart_indicator_audit", {}).get("score"),
        "indicator_timeframes": report.get("chart_indicator_audit", {}).get("timeframes"),
        "indicator_audit_note": "Unlabelled screenshot panes are NOT_IDENTIFIABLE and excluded; indicator values in this report are calculated from closed OHLC, not read from screenshot pixels."
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
    write_pdf(report, pdf_path)
    print(json.dumps({"symbol": report["symbol"], "decision": report["decision"],
                      "strategies": [{"name": x["strategy"], "oos_n": x["oos_n"],
                                      "win_rate": x["oos_net"]["win_rate"],
                                      "expectancy_r": x["oos_net"]["expectancy_r"],
                                      "profit_factor": x["oos_net"]["profit_factor"],
                                      "eligible": x["gate"]["eligible"]} for x in report["strategies"]],
                      "table_18": report.get("table_18"),
                      "pdf": str(pdf_path), "json": str(json_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
