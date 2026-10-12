"""End-to-end Step Index research pipeline for SQAO.

Fetches public Deriv OHLC, calculates a fixed MTF breakout research rule,
evaluates the final chronological holdout, and emits JSON/PDF outputs.
Research-only: it never sends or places trading orders.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets

from .step_index_quant import analyze_backtest, equity_stats, log_returns, acceptance_gate

WS = os.getenv("DERIV_PUBLIC_WS", "wss://api.derivws.com/trading/v1/options/ws/public")
GRANULARITY = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "D1": 86400, "W1": 604800}
DEFAULT_COUNTS = {"M1": 1500, "M5": 5000, "M15": 3000, "H1": 1500, "D1": 500, "W1": 200}


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for x in values[period:]:
        value = x * alpha + value * (1.0 - alpha)
    return value


def atr(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(rows) < period + 1:
        return None
    tr = []
    for i in range(1, len(rows)):
        high, low, previous_close = float(rows[i]["high"]), float(rows[i]["low"]), float(rows[i - 1]["close"])
        tr.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(tr[-period:]) / period


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    diffs = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    gain = sum(max(x, 0.0) for x in diffs) / period
    loss = sum(max(-x, 0.0) for x in diffs) / period
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def closed_candles(rows: list[dict[str, Any]], timeframe: str, now_epoch: int | None = None) -> list[dict[str, Any]]:
    """Sort candles and exclude any candle that has not fully closed."""
    now = int(now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp())
    seconds = GRANULARITY[timeframe]
    valid = []
    for row in rows:
        try:
            item = {**row, "epoch": int(row["epoch"]), "open": float(row["open"]),
                    "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])}
        except (KeyError, TypeError, ValueError):
            continue
        if item["epoch"] + seconds <= now and all(math.isfinite(item[k]) for k in ("open", "high", "low", "close")):
            valid.append(item)
    valid.sort(key=lambda x: x["epoch"])
    # Remove duplicate timestamps deterministically.
    return list({x["epoch"]: x for x in valid}.values())


async def _request(ws: Any, payload: dict[str, Any]) -> dict[str, Any]:
    await ws.send(json.dumps(payload))
    request_id = payload.get("req_id")
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
        if message.get("error"):
            raise RuntimeError(message["error"].get("message", "Deriv API error"))
        if message.get("req_id") == request_id:
            return message


async def discover_step_index() -> dict[str, str]:
    async with websockets.connect(WS, ping_interval=20, ping_timeout=20, open_timeout=20) as ws:
        data = await _request(ws, {"active_symbols": "brief", "req_id": 101})
    candidates = []
    for item in data.get("active_symbols", []) or []:
        name = str(item.get("display_name") or item.get("underlying_symbol_name") or "")
        symbol = str(item.get("symbol") or item.get("underlying_symbol") or "")
        if symbol and "step index" in f"{name} {symbol}".lower():
            candidates.append({"symbol": symbol, "display_name": name})
    if not candidates:
        raise RuntimeError("Deriv public API did not return an active Step Index symbol; no proxy instrument will be substituted.")
    preferred = os.getenv("DERIV_STEP_NAME", "").strip().lower()
    for candidate in candidates:
        if preferred and (preferred == candidate["symbol"].lower() or preferred in candidate["display_name"].lower()):
            return candidate
    exact = next((x for x in candidates if x["display_name"].strip().lower() == "step index"), None)
    return exact or candidates[0]


async def fetch_candles(symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
    async with websockets.connect(WS, ping_interval=20, ping_timeout=20, open_timeout=20) as ws:
        data = await _request(ws, {
            "ticks_history": symbol, "end": "latest", "count": count,
            "style": "candles", "granularity": GRANULARITY[timeframe],
            "adjust_start_time": 1, "req_id": GRANULARITY[timeframe],
        })
    return data.get("candles", []) or []


def trend_at(rows: list[dict[str, Any]], decision_epoch: int, timeframe: str) -> str | None:
    seconds = GRANULARITY[timeframe]
    eligible = [r for r in rows if int(r["epoch"]) + seconds <= decision_epoch]
    if len(eligible) < 30:
        return None
    c = [float(r["close"]) for r in eligible]
    fast, slow = ema(c, 10), ema(c, 20)
    if fast is None or slow is None or fast == slow:
        return None
    return "LONG" if fast > slow else "SHORT"


def signal_m5(hist: list[dict[str, Any]]) -> str | None:
    """Fixed breakout rule using only candles closed by the decision timestamp."""
    if len(hist) < 30:
        return None
    c = [float(r["close"]) for r in hist]
    fast, slow = ema(c, 10), ema(c, 20)
    prior = hist[-21:-1]
    if fast is None or slow is None:
        return None
    if c[-1] > max(float(x["high"]) for x in prior) and fast > slow:
        return "LONG"
    if c[-1] < min(float(x["low"]) for x in prior) and fast < slow:
        return "SHORT"
    return None


def backtest_m5(
    m5: list[dict[str, Any]], m15: list[dict[str, Any]], h1: list[dict[str, Any]],
    *, horizon: int = 5, rr: float = 1.5, atr_mult: float = 1.2,
    round_trip_cost_price: float | None = None, train_fraction: float = 0.70,
) -> dict[str, Any]:
    """Chronological test with next-bar-open entry, M15/H1 filters and stop-first ties."""
    if not 0.5 < train_fraction < 0.95:
        raise ValueError("train_fraction must be between 0.5 and 0.95")
    if horizon < 1 or rr <= 0 or atr_mult <= 0:
        raise ValueError("horizon, rr and atr_mult must be positive")
    split = int(len(m5) * train_fraction)
    trades: list[dict[str, Any]] = []
    next_allowed = 0
    for i in range(40, max(40, len(m5) - horizon - 1)):
        if i < next_allowed or i + 1 >= len(m5):
            continue
        hist = m5[:i + 1]
        direction = signal_m5(hist)
        if not direction:
            continue
        decision_epoch = int(m5[i]["epoch"]) + GRANULARITY["M5"]
        if trend_at(m15, decision_epoch, "M15") != direction:
            continue
        if trend_at(h1, decision_epoch, "H1") != direction:
            continue
        risk = atr(hist, 14)
        if risk is None or risk <= 0:
            continue
        risk *= atr_mult
        entry_bar = m5[i + 1]
        entry = float(entry_bar["open"])
        stop = entry - risk if direction == "LONG" else entry + risk
        target = entry + rr * risk if direction == "LONG" else entry - rr * risk
        exit_price = None
        exit_reason = "TIME_EXIT"
        gross_r = 0.0
        last_j = min(len(m5) - 1, i + horizon)
        for j in range(i + 1, last_j + 1):
            candle = m5[j]
            high, low = float(candle["high"]), float(candle["low"])
            stop_hit = low <= stop if direction == "LONG" else high >= stop
            target_hit = high >= target if direction == "LONG" else low <= target
            if stop_hit and target_hit:
                exit_price, exit_reason, gross_r = stop, "STOP_AND_TARGET_SAME_BAR_STOP_FIRST", -1.0
                break
            if stop_hit:
                exit_price, exit_reason, gross_r = stop, "STOP", -1.0
                break
            if target_hit:
                exit_price, exit_reason, gross_r = target, "TARGET", rr
                break
        if exit_price is None:
            exit_price = float(m5[last_j]["close"])
            directional_change = (exit_price - entry) * (1.0 if direction == "LONG" else -1.0)
            gross_r = max(-1.0, min(rr, directional_change / risk))
        cost_r = (float(round_trip_cost_price) / risk) if round_trip_cost_price is not None else 0.0
        net_r = gross_r - cost_r
        trades.append({
            "signal_epoch": decision_epoch, "entry_epoch": int(entry_bar["epoch"]),
            "direction": direction, "entry": entry, "exit": exit_price, "stop": stop, "target": target,
            "risk_price": risk, "gross_r": gross_r, "cost_r": cost_r, "net_r": net_r,
            "exit_reason": exit_reason, "sample": "train" if i < split else "out_of_sample",
        })
        next_allowed = last_j + 1
    train = [x for x in trades if x["sample"] == "train"]
    oos = [x for x in trades if x["sample"] == "out_of_sample"]
    gross_cost_defined = round_trip_cost_price is not None
    train_stats = equity_stats([x["gross_r"] for x in train])
    oos_gross = equity_stats([x["gross_r"] for x in oos])
    oos_net = equity_stats([x["net_r"] for x in oos])
    gate = acceptance_gate(oos_net, min_trades=int(os.getenv("SQAO_STEP_MIN_OOS_TRADES", "100")),
                           target_win_rate=float(os.getenv("SQAO_STEP_TARGET_WIN_RATE", "0.70")),
                           require_costs=True, costs_supplied=gross_cost_defined)
    return {
        "rule": "M5 close breakout of prior 20-bar high/low + EMA10/20 direction; M15 and H1 closed-candle EMA10/20 must agree",
        "parameters": {"horizon_m5_bars": horizon, "target_R": rr, "stop_ATR_multiple": atr_mult,
                       "train_fraction": train_fraction, "round_trip_cost_price": round_trip_cost_price},
        "n_m5_candles": len(m5), "train": {"n_trades": len(train), "stats_gross": train_stats},
        "out_of_sample": {"n_trades": len(oos), "stats_gross": oos_gross, "stats_net": oos_net, "gate": gate},
        "trades": trades,
        "warning": "Historical test of a fixed proxy rule, not proof of the live signal's future success. Cost-adjusted results require a real round-trip cost in quote-price units.",
    }


def snapshot(frames: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    indicators = {}
    for tf, rows in frames.items():
        c = [float(r["close"]) for r in rows]
        e10, e20 = ema(c, 10), ema(c, 20)
        indicators[tf] = {
            "candles": len(rows), "last_closed_epoch": int(rows[-1]["epoch"]) if rows else None,
            "last_close": c[-1] if c else None, "ema10": e10, "ema20": e20,
            "direction": "LONG" if e10 is not None and e20 is not None and e10 > e20 else
                         "SHORT" if e10 is not None and e20 is not None and e10 < e20 else "UNKNOWN",
            "rsi14": rsi(c), "atr14": atr(rows, 14),
        }
    return indicators


def log_distribution(closes: list[float]) -> dict[str, Any]:
    vals = log_returns(closes)
    if not vals:
        return {"n": 0, "mean": None, "sd": None, "skew": None, "excess_kurtosis": None}
    mean = sum(vals) / len(vals)
    variance = sum((x - mean) ** 2 for x in vals) / len(vals)
    sd = math.sqrt(variance)
    skew = sum((x - mean) ** 3 for x in vals) / len(vals) / (sd ** 3) if sd else None
    kurt = sum((x - mean) ** 4 for x in vals) / len(vals) / (sd ** 4) - 3 if sd else None
    return {"n": len(vals), "mean": mean, "sd": sd, "skew": skew, "excess_kurtosis": kurt,
            "cumulative_log_return": sum(vals), "geometric_return_fraction": math.expm1(sum(vals))}


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return "Infinity" if obj > 0 else "-Infinity" if obj < 0 else None
    return obj


def write_pdf(report: dict[str, Any], path: Path) -> None:
    """Render executive PDF. ReportLab is installed by the research workflow."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SQTitle", parent=styles["Title"], fontSize=19, leading=23,
                              textColor=colors.HexColor("#17324D"), alignment=1, spaceAfter=6))
    styles.add(ParagraphStyle(name="SQSub", parent=styles["Normal"], fontSize=8, leading=10,
                              textColor=colors.HexColor("#596B7A"), alignment=1, spaceAfter=10))
    styles.add(ParagraphStyle(name="SQH1", parent=styles["Heading1"], fontSize=13, leading=16,
                              textColor=colors.HexColor("#17324D"), spaceBefore=7, spaceAfter=5))
    styles.add(ParagraphStyle(name="SQH2", parent=styles["Heading2"], fontSize=10, leading=12,
                              textColor=colors.HexColor("#17657A"), spaceBefore=4, spaceAfter=3))
    styles.add(ParagraphStyle(name="SQBody", parent=styles["BodyText"], fontSize=8, leading=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="SQSmall", parent=styles["BodyText"], fontSize=6.8, leading=8, spaceAfter=2))
    styles.add(ParagraphStyle(name="SQAlert", parent=styles["BodyText"], fontSize=9, leading=12,
                              textColor=colors.HexColor("#7D2828"), borderColor=colors.HexColor("#D8A0A0"),
                              borderWidth=.7, borderPadding=6, spaceBefore=4, spaceAfter=7))
    def p(text: str, style: str = "SQBody"):
        return Paragraph(text, styles[style])
    def table(rows: list[list[Any]], widths: list[float]):
        cells = [[Paragraph(str(c), styles["SQSmall"]) for c in row] for row in rows]
        tb = Table(cells, colWidths=widths, repeatRows=1)
        tb.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17324D")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#B7C3CC")),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F2F5F7")]),
            ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        return tb
    oos = report["backtest"]["out_of_sample"]
    s = oos["stats_net"]
    gate = oos["gate"]
    pct = lambda x: "n/d" if x is None else f"{x * 100:.2f}%"
    num = lambda x, d=3: "n/d" if x is None else f"{x:.{d}f}"
    story = [
        Spacer(1, .35*cm),
        p("SQAO · STEP INDEX QUANT RESEARCH", "SQTitle"),
        p(f"Informe técnico ejecutivo · generado {report['generated_at_utc']} · fuente Deriv public OHLC", "SQSub"),
        p(f"DICTAMEN: {gate['decision']}", "SQH1"),
        p("No se ha validado una efectividad del 70% para la próxima operación. El umbral se aplica exclusivamente a una muestra cronológica fuera de muestra con costes reales declarados. Si los criterios no se cumplen, la decisión se mantiene en NO_TRADE.", "SQAlert"),
        p("1. Resultado ejecutivo", "SQH1"),
        table([
            ["Indicador OOS neto","Resultado","Criterio"],
            ["Operaciones fuera de muestra",str(s["n"]),"≥ 100"],
            ["Tasa de acierto",pct(s["win_rate"]),"≥ 70% observado"],
            ["IC Wilson 95%",f"{pct(s['wilson_95_low'])} – {pct(s['wilson_95_high'])}","Límite inferior ≥ 70%"],
            ["Expectativa neta",f"{num(s['expectancy_r'])} R/trade","> 0"],
            ["Profit factor",num(s["profit_factor"]),"> 1"],
            ["Drawdown máximo",f"{num(s['max_drawdown_r'])} R","Control de riesgo"],
            ["Coste round-trip",str(report["backtest"]["parameters"]["round_trip_cost_price"]),"Debe ser proporcionado en unidades de precio"],
        ], [4.6*cm,4.2*cm,6.0*cm]),
        Spacer(1,5),
        p("2. Resumen de marcos temporales", "SQH1"),
        table([["Marco","Velas cerradas","Último cierre","EMA10","EMA20","RSI14","ATR14","Sesgo"]] + [
            [tf, x["candles"], num(x["last_close"], 2), num(x["ema10"],2), num(x["ema20"],2),
             num(x["rsi14"],2), num(x["atr14"],3), x["direction"]] for tf,x in report["indicators"].items()
        ], [1.5*cm,2.0*cm,2.0*cm,2.0*cm,2.0*cm,1.7*cm,1.7*cm,2.2*cm]),
        p("3. Metodología y prevención de sesgo", "SQH1"),
        p(report["backtest"]["rule"], "SQBody"),
        p("La señal se determina al cierre de M5. EMA10/20 de M15 y H1 solo usan velas ya cerradas a la hora de decisión. La entrada de simulación se realiza en la apertura de la siguiente vela M5. Si stop y objetivo aparecen tocados en la misma vela, se contabiliza primero el stop. Las últimas velas incompletas quedan excluidas.", "SQBody"),
        p("4. Estadística y logaritmos", "SQH1"),
        table([
            ["Métrica","Valor"],
            ["n retornos logarítmicos M5",report["log_distribution_m5"]["n"]],
            ["Media retorno log",num(report["log_distribution_m5"]["mean"],7)],
            ["Desviación log",num(report["log_distribution_m5"]["sd"],7)],
            ["Asimetría",num(report["log_distribution_m5"]["skew"],4)],
            ["Exceso de curtosis",num(report["log_distribution_m5"]["excess_kurtosis"],4)],
            ["Retorno geométrico acumulado",pct(report["log_distribution_m5"]["geometric_return_fraction"])],
            ["Expectativa OOS neta",f"{num(s['expectancy_r'])} R"],
            ["Sharpe por operación (sin anualizar)",num(s["sharpe_per_trade_not_annualized"])],
            ["Sortino por operación (sin anualizar)",num(s["sortino_per_trade_not_annualized"])],
        ], [6.0*cm,9.0*cm]),
        p("5. Regla de aceptación", "SQH1"),
        p("Se requiere simultáneamente tamaño de muestra suficiente, win rate observado ≥ objetivo, límite inferior de Wilson 95% ≥ objetivo, expectativa neta positiva, profit factor > 1 y costes declarados. La superación habilita revisión adicional; no garantiza rentabilidad futura ni constituye una probabilidad predictiva calibrada.", "SQBody"),
        p("6. Limitaciones", "SQH1"),
        p("Esta estrategia es un baseline mecánico (ruptura de 20 velas + EMA10/20 + filtros M15/H1), no una optimización del algoritmo de Step Index. El resultado depende del histórico disponible, el régimen de mercado, el coste comunicado y la fidelidad del modelo de ejecución. No hay conexión de órdenes ni ejecución real.", "SQBody"),
        p("7. Conclusión", "SQH1"),
        p(f"Decisión del motor: {gate['decision']}. Estado elegible: {gate['eligible']}. Si no se cumplen todos los filtros o los costes no se han definido, no se emite una operación activa.", "SQAlert"),
    ]
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=1.4*cm, leftMargin=1.4*cm,
                            topMargin=1.1*cm, bottomMargin=1.1*cm, title="SQAO Step Index Quant Research")
    doc.build(story)


async def run_research() -> dict[str, Any]:
    symbol = await discover_step_index()
    frames: dict[str, list[dict[str, Any]]] = {}
    counts = {tf: int(os.getenv(f"SQAO_STEP_CANDLES_{tf}", str(n))) for tf, n in DEFAULT_COUNTS.items()}
    tasks = {tf: fetch_candles(symbol["symbol"], tf, counts[tf]) for tf in counts}
    raw = await asyncio.gather(*tasks.values())
    now = int(datetime.now(timezone.utc).timestamp())
    for tf, rows in zip(tasks.keys(), raw):
        frames[tf] = closed_candles(rows, tf, now)
    for tf in ("M5", "M15", "H1"):
        if len(frames[tf]) < 100:
            raise RuntimeError(f"Insufficient closed OHLC candles for {tf}: {len(frames[tf])}")
    cost_text = os.getenv("SQAO_STEP_ROUND_TRIP_COST_PRICE", "").strip()
    cost_price = float(cost_text) if cost_text else None
    if cost_price is not None and (not math.isfinite(cost_price) or cost_price < 0):
        raise ValueError("SQAO_STEP_ROUND_TRIP_COST_PRICE must be a non-negative number in quoted-price units")
    bt = backtest_m5(frames["M5"], frames["M15"], frames["H1"],
                     horizon=int(os.getenv("SQAO_STEP_HORIZON_M5", "5")),
                     rr=float(os.getenv("SQAO_STEP_TARGET_R", "1.5")),
                     atr_mult=float(os.getenv("SQAO_STEP_ATR_MULT", "1.2")),
                     round_trip_cost_price=cost_price,
                     train_fraction=float(os.getenv("SQAO_STEP_TRAIN_FRACTION", "0.70")))
    m5_closes = [float(x["close"]) for x in frames["M5"]]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "source": "Deriv public OHLC; closed candles only",
        "read_only": True,
        "indicators": snapshot(frames),
        "log_distribution_m5": log_distribution(m5_closes),
        "backtest": bt,
        "decision": bt["out_of_sample"]["gate"]["decision"],
        "eligibility": bt["out_of_sample"]["gate"],
        "methodology": "chronological 70/30 split; fixed parameters; no parameter optimization; entry at next M5 open; stop first on same-bar conflict",
        "data_counts": {tf: len(rows) for tf, rows in frames.items()},
        "limitations": ["A 70% target is not guaranteed.", "Out-of-sample history is not a prediction for the next trade.",
                        "The rule is a baseline and requires further walk-forward validation.",
                        "Cost-adjusted eligibility is blocked unless realistic round-trip cost is provided."],
    }


def main() -> None:
    report = asyncio.run(run_research())
    outdir = Path(os.getenv("SQAO_DATA_DIR", "DATA"))
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "step_index_quant_report.json"
    pdf_path = outdir / "step_index_quant_report.pdf"
    json_path.write_text(json.dumps(_json_safe(report), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_pdf(report, pdf_path)
    print(json.dumps({
        "symbol": report["symbol"], "decision": report["decision"],
        "oos_n": report["backtest"]["out_of_sample"]["n_trades"],
        "oos_win_rate": report["backtest"]["out_of_sample"]["stats_net"]["win_rate"],
        "oos_expectancy_r": report["backtest"]["out_of_sample"]["stats_net"]["expectancy_r"],
        "profit_factor": report["backtest"]["out_of_sample"]["stats_net"]["profit_factor"],
        "pdf": str(pdf_path), "json": str(json_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
