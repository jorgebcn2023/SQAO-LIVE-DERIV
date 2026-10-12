"""Cost-sensitivity stress test for Step Index OOS strategies.

This module never guesses Deriv spread/slippage and never marks a scenario as
broker-realistic. It applies explicitly hypothetical round-trip costs in R
multiples to the OOS trades produced by the fixed strategy lab.
"""
from __future__ import annotations

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

from .step_index_quant import equity_stats

DEFAULT_COSTS_R = (0.0, 0.025, 0.05, 0.10, 0.20, 0.30)


def finite_or_none(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): finite_or_none(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite_or_none(v) for v in value]
    return value


def build_sensitivity(lab: dict[str, Any], costs_r: tuple[float, ...] = DEFAULT_COSTS_R) -> dict[str, Any]:
    results = []
    for strategy in lab.get("strategies", []):
        trades = [t for t in strategy.get("trades", []) if t.get("sample") == "out_of_sample"]
        gross_r = [float(t["gross_r"]) for t in trades]
        if not gross_r:
            continue
        scenarios = []
        for cost_r in costs_r:
            stats = equity_stats(gross_r, cost_r=cost_r)
            scenarios.append({
                "hypothetical_round_trip_cost_R": cost_r,
                "n_oos": stats["n"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate": stats["win_rate"],
                "wilson_95_low": stats["wilson_95_low"],
                "wilson_95_high": stats["wilson_95_high"],
                "expectancy_R": stats["expectancy_r"],
                "profit_factor": stats["profit_factor"],
                "max_drawdown_R": stats["max_drawdown_r"],
                "net_sum_R": stats["net_sum_r"],
            })
        mean_gross = sum(gross_r) / len(gross_r)
        results.append({
            "strategy": strategy.get("strategy", "unknown"),
            "n_oos": len(gross_r),
            "gross_expectancy_R": mean_gross,
            "break_even_cost_upper_bound_R": max(0.0, mean_gross) if mean_gross > 0 else 0.0,
            "scenarios": scenarios,
        })
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": lab.get("symbol"),
        "source_lab_generated_at_utc": lab.get("generated_at_utc"),
        "costs_are_broker_verified": False,
        "decision": "NO_TRADE_COSTS_UNVERIFIED",
        "method": "Fixed hypothetical costs subtracted from OOS R multiples; no cost scenario is claimed to represent actual Deriv spread, slippage, or execution.",
        "cost_grid_R": list(costs_r),
        "strategies": results,
        "limitations": [
            "Hypothetical R-cost stress tests only; Deriv round-trip costs were not supplied or verified.",
            "The zero-cost row is gross performance, not net performance.",
            "These scenarios cannot qualify a live or demo trade; a verified execution-cost input is still required.",
            "The historical OOS results are not a forecast of the next trade."
        ]
    }


def write_pdf(report: dict[str, Any], path: Path) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), title="SQAO Step Index Cost Sensitivity")
    story = [
        Paragraph("SQAO — Step Index Cost Sensitivity", styles["Title"]),
        Paragraph(f"Instrumento: {report.get('symbol', {}).get('display_name', report.get('symbol', {}).get('symbol', 'n/d'))} | Generado UTC: {report['generated_at_utc']}", styles["Normal"]),
        Spacer(1, 8),
        Paragraph("<b>Decisión: NO_TRADE_COSTS_UNVERIFIED</b>", styles["Heading2"]),
        Paragraph("Los escenarios siguientes son pruebas de estrés hipotéticas en unidades R. No son una estimación de spread, comisión o deslizamiento de Deriv.", styles["BodyText"]),
        Spacer(1, 10),
    ]
    for strategy in report["strategies"]:
        story.append(Paragraph(f"Estrategia: {strategy['strategy']} — N OOS: {strategy['n_oos']} — Expectativa bruta: {strategy['gross_expectancy_R']:.4f} R", styles["Heading3"]))
        rows = [["Coste hipotético (R)", "Acierto", "IC Wilson 95%", "Expectativa (R)", "PF", "DD máximo (R)"]]
        for s in strategy["scenarios"]:
            pct = lambda x: "n/d" if x is None else f"{100*x:.2f}%"
            num = lambda x: "n/d" if x is None or not math.isfinite(x) else f"{x:.3f}"
            rows.append([
                f"{s['hypothetical_round_trip_cost_R']:.3f}",
                pct(s["win_rate"]),
                f"{pct(s['wilson_95_low'])}–{pct(s['wilson_95_high'])}",
                num(s["expectancy_R"]),
                num(s["profit_factor"]),
                num(s["max_drawdown_R"]),
            ])
        table = Table(rows, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243447")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#edf2f7")]),
        ]))
        story.extend([table, Spacer(1, 12)])
    story.append(Paragraph("No operar con estos escenarios como si fueran costes reales. Introducir únicamente costes verificados del contrato/ejecución y repetir el workflow antes de cualquier reevaluación.", styles["BodyText"]))
    doc.build(story)


def main() -> None:
    out = Path(os.getenv("SQAO_DATA_DIR", "DATA"))
    source = out / "step_index_strategy_lab.json"
    if not source.is_file():
        raise FileNotFoundError(f"Missing strategy lab output: {source}")
    lab = json.loads(source.read_text(encoding="utf-8"))
    report = finite_or_none(build_sensitivity(lab))
    json_path, pdf_path = out / "step_index_cost_sensitivity.json", out / "step_index_cost_sensitivity.pdf"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_pdf(report, pdf_path)
    print(json.dumps({
        "decision": report["decision"],
        "strategies": [{"name": s["strategy"], "n_oos": s["n_oos"],
                        "gross_expectancy_R": s["gross_expectancy_R"],
                        "scenario_expectancies_R": [x["expectancy_R"] for x in s["scenarios"]]}
                       for s in report["strategies"]],
        "pdf": str(pdf_path), "json": str(json_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
