"""SQAO LIVE DERIV V2.1 — chart screenshot visual extraction.

Research-only OCR/geometry layer. It extracts text, visible numeric labels, chart
metadata, axis calibration and a possible horizontal quote line from supplied
screenshots. It does NOT reconstruct OHLC candles or claim unreadable indicator
values. Exact backtests and executable levels still require timestamped OHLC.
Optional dependencies: Pillow, pytesseract, numpy.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

VERSION = "2.1.0"
TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")
INDICATORS = ("EMA 9", "EMA 20", "EMA 50", "Bollinger 20,2",
              "MACD 12,26,9", "RSI 14", "ATR 14", "ADX 14",
              "+DI 14", "-DI 14", "Stochastic 14,3,3")

NUM_RE = re.compile(r"(?<![A-Za-z])[-+]?\d{1,7}(?:[.,]\d+)?")
TF_RE = re.compile(r"\b(D1|H4|H1|M15|M5|M1)\b", re.I)
MACD_RE = re.compile(r"MACD\s*\(\s*12\s*,\s*26\s*,\s*9\s*\)\s*([-+]?\d+[.,]\d+)\s*([-+]?\d+[.,]\d+)", re.I)


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _ocr(path: str | Path) -> dict[str, Any]:
    try:
        from PIL import Image
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        return {"status": "OCR_DEPENDENCY_MISSING", "error": str(exc),
                "text": "", "tokens": [], "image_size": None}
    image = Image.open(path).convert("RGB")
    data = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 11")
    tokens = []
    for i, raw in enumerate(data.get("text", [])):
        value = str(raw).strip()
        if not value:
            continue
        tokens.append({
            "text": value,
            "confidence": _num(str(data.get("conf", ["-1"])[i])),
            "x": int(data["left"][i]), "y": int(data["top"][i]),
            "width": int(data["width"][i]), "height": int(data["height"][i]),
        })
    return {"status": "OCR_OK", "text": " ".join(x["text"] for x in tokens),
            "tokens": tokens, "image_size": list(image.size)}


def _axis_calibration(tokens: list[dict[str, Any]], width: int) -> dict[str, Any]:
    # Right-side axis labels are selected by position, then a linear price/pixel
    # mapping is fitted. At least two distinct labels are required.
    points = []
    for t in tokens:
        if t["x"] < width * 0.82:
            continue
        value = _num(t["text"])
        if value is None or abs(value) < 100:
            continue
        points.append({"price": value, "y": t["y"] + t["height"] / 2,
                       "confidence": t.get("confidence")})
    # Keep plausible axis values and remove duplicate y/value detections.
    unique = []
    for p in points:
        if not any(abs(p["y"] - q["y"]) < 3 and abs(p["price"] - q["price"]) < 0.05 for q in unique):
            unique.append(p)
    if len(unique) < 2:
        return {"status": "NOT_CALIBRATED", "axis_labels": unique,
                "price_per_pixel": None, "intercept": None}
    ys = [p["y"] for p in unique]
    ps = [p["price"] for p in unique]
    ym, pm = sum(ys) / len(ys), sum(ps) / len(ps)
    denom = sum((y - ym) ** 2 for y in ys)
    if denom == 0:
        return {"status": "NOT_CALIBRATED", "axis_labels": unique,
                "price_per_pixel": None, "intercept": None}
    slope = sum((y - ym) * (p - pm) for y, p in zip(ys, ps)) / denom
    intercept = pm - slope * ym
    errors = [abs((slope * y + intercept) - p) for y, p in zip(ys, ps)]
    return {"status": "CALIBRATED" if len(unique) >= 3 else "LOW_CONFIDENCE",
            "axis_labels": unique, "price_per_pixel": slope, "intercept": intercept,
            "mean_abs_fit_error": sum(errors) / len(errors)}


def _horizontal_quote(path: str | Path, calibration: dict[str, Any]) -> dict[str, Any]:
    if calibration.get("status") not in {"CALIBRATED", "LOW_CONFIDENCE"}:
        return {"status": "NOT_AVAILABLE", "price": None}
    try:
        import numpy as np
        from PIL import Image
        arr = np.asarray(Image.open(path).convert("RGB"))
    except ImportError:
        return {"status": "IMAGE_ARRAY_DEPENDENCY_MISSING", "price": None}
    h, w, _ = arr.shape
    # Cyan/turquoise dashed quote line; count matching pixels by row in chart
    # body and ignore the right-side quote badge/text.
    crop = arr[:int(h * 0.78), :int(w * 0.91), :]
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    mask = (g > 115) & (b > 105) & (g > r * 1.20) & (b > r * 1.10)
    counts = mask.sum(axis=1)
    if len(counts) == 0:
        return {"status": "NOT_DETECTED", "price": None}
    y = int(counts.argmax())
    if counts[y] < max(20, int(w * 0.08)):
        return {"status": "NOT_DETECTED", "price": None, "pixel_count": int(counts[y])}
    price = calibration["price_per_pixel"] * (y + 0.5) + calibration["intercept"]
    return {"status": "VISUAL_ESTIMATE", "price": round(float(price), 3),
            "pixel_y": y, "pixel_count": int(counts[y]),
            "warning": "Approximate screenshot-derived quote; not an executable/live quote."}


def _extract_indicator_readings(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    macd = MACD_RE.search(text)
    result["macd_12_26_9_visible_pair"] = (
        [_num(macd.group(1)), _num(macd.group(2))] if macd else None)
    # Generic indicator values are not guessed from unnamed panes.
    for name in ("RSI 14", "ATR 14", "ADX 14", "+DI 14", "-DI 14",
                 "Stochastic 14,3,3", "EMA 9", "EMA 20", "EMA 50"):
        result[name] = {"value": None, "status": "NOT_LABELLED_OR_NOT_PRINTED"}
    return result


def audit_chart(path: str | Path, timeframe: str | None = None) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"source": str(p), "status": "FILE_NOT_FOUND"}
    raw = _ocr(p)
    text = raw.get("text", "")
    detected = [x.upper() for x in TF_RE.findall(text)]
    tf = timeframe.upper() if timeframe else (detected[0] if detected else None)
    size = raw.get("image_size") or [0, 0]
    calibration = _axis_calibration(raw.get("tokens", []), size[0]) if size else {
        "status": "NOT_CALIBRATED", "axis_labels": [], "price_per_pixel": None, "intercept": None}
    quote = _horizontal_quote(p, calibration) if size else {"status": "NOT_AVAILABLE", "price": None}
    return {
        "version": VERSION, "source_file": p.name, "timeframe": tf,
        "detected_timeframes": detected, "status": raw["status"],
        "image_size": raw.get("image_size"), "ocr_text": text,
        "numeric_tokens": [{"text": t["text"], "value": _num(t["text"]),
                            "confidence": t.get("confidence"), "x": t["x"], "y": t["y"]}
                           for t in raw.get("tokens", []) if NUM_RE.fullmatch(t["text"])],
        "axis_calibration": calibration, "horizontal_quote": quote,
        "indicator_readings": _extract_indicator_readings(text),
        "visible_macd_label": MACD_RE.search(text).group(0) if MACD_RE.search(text) else None,
        "limitations": [
            "Screenshot pixels are not OHLC candles and cannot establish exact open/high/low/close.",
            "OCR values are visual transcriptions; confidence and source coordinates must be retained.",
            "Unlabelled indicator panes are not assigned RSI/ATR/ADX/Stochastic values.",
            "A screenshot quote estimate is not a live executable quote.",
            "Different screenshot timestamps must not be treated as simultaneous MTF confirmation."
        ],
    }


def table18_template(reference_price: float | None = None) -> dict[str, Any]:
    """Full numeric schema; unknown values remain None, never fabricated."""
    fields = (
        "reference_price", "entry_price", "stop_loss", "take_profit",
        "stop_distance_points", "target_distance_points", "risk_reward",
        "risk_points", "reward_points", "ema9", "ema20", "ema50",
        "bollinger_lower", "bollinger_middle", "bollinger_upper",
        "macd_line", "macd_signal", "macd_histogram", "rsi14", "atr14",
        "adx14", "plus_di14", "minus_di14", "stochastic_k", "stochastic_d",
        "mtf_confluence_score", "oos_trades", "wins", "losses", "win_rate_pct",
        "wilson_95_lower_pct", "expectancy_r", "profit_factor",
        "max_drawdown_pct", "spread_points", "commission_points",
        "slippage_points", "total_cost_points", "net_expectancy_r"
    )
    def side(direction: str) -> dict[str, Any]:
        row = {key: None for key in fields}
        row.update({"direction": direction, "price_source": "NOT_AVAILABLE",
                    "entry_source": "NOT_AVAILABLE", "decision": "NO_TRADE"})
        if reference_price is not None and math.isfinite(float(reference_price)):
            row["reference_price"] = float(reference_price)
            row["price_source"] = "SCREENSHOT_VISUAL_ESTIMATE"
        return row
    return {"schema_version": "2.1", "LONG": side("LONG"), "SHORT": side("SHORT"),
            "numeric_policy": "Unknown values are null; never replace missing data with zero or estimates."}


def build_visual_audit(images: dict[str, str | Path], output: str | Path | None = None) -> dict[str, Any]:
    charts = {tf.upper(): audit_chart(path, tf) for tf, path in images.items()}
    # No artificial synchronization: preserve each chart's own source and time labels.
    report = {
        "version": VERSION, "mode": "READ_ONLY_RESEARCH_ONLY",
        "charts": charts, "table18": table18_template(),
        "mtf_synchronization": "NOT_VERIFIED_FROM_SCREENSHOTS",
        "decision": "NO_TRADE",
        "reason": "Visual extraction is contextual evidence only; no closed OHLC, timestamp alignment, verified costs or OOS statistics supplied.",
    }
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
