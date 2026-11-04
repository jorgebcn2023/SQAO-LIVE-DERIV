"""Multimodal chart-image audit for SQAO. Research-only; image-derived OHLC is ESTIMATED.

Images are never silently promoted to broker OHLC. Exact backtests must use timestamped
Deriv candles. This module extracts metadata/OCR, optionally detects candle-colour
components, and maps pixels to price only when the operator supplies two axis anchors.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def linear_price_calibration(y_top: float, price_top: float,
                             y_bottom: float, price_bottom: float) -> dict[str, float]:
    """Map image y pixels to prices. Image y increases downwards."""
    if y_top == y_bottom:
        raise ValueError("Calibration anchors must have different y coordinates")
    slope = (price_bottom - price_top) / (y_bottom - y_top)
    return {"slope_price_per_pixel": slope, "intercept": price_top - slope * y_top}


def pixel_y_to_price(y: float, calibration: dict[str, float]) -> float:
    return calibration["slope_price_per_pixel"] * y + calibration["intercept"]


def monetary_scenario(price_distance: float, lots: float,
                      usd_per_0_1_at_0_10_lots: float = 0.10) -> float:
    """User-declared provisional conversion; not broker tick-value verification."""
    if not all(math.isfinite(float(v)) for v in
               (price_distance, lots, usd_per_0_1_at_0_10_lots)):
        raise ValueError("Monetary inputs must be finite")
    if price_distance < 0 or lots <= 0 or usd_per_0_1_at_0_10_lots <= 0:
        raise ValueError("Distance, volume and conversion must be positive")
    return (price_distance / 0.1) * usd_per_0_1_at_0_10_lots * (lots / 0.10)


def _optional_ocr(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image
        import pytesseract
        text = pytesseract.image_to_data(Image.open(path), output_type=pytesseract.Output.DICT)
        tokens = []
        for i, token in enumerate(text.get("text", [])):
            token = str(token).strip()
            if token:
                tokens.append({"text": token, "confidence": text["conf"][i],
                               "box": [text["left"][i], text["top"][i],
                                       text["width"][i], text["height"][i]]})
        return {"available": True, "tokens": tokens}
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__, "tokens": []}


def _detect_coloured_components(path: Path, chart_roi: list[int] | None) -> dict[str, Any]:
    """Detect red/green image components; this is not a full candle reconstruction."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return {"available": False, "reason": "opencv-python/numpy not installed",
                "components": [], "ohlc": None}
    image = cv2.imread(str(path))
    if image is None:
        return {"available": False, "reason": "image unreadable", "components": [], "ohlc": None}
    h, w = image.shape[:2]
    if chart_roi is None:
        return {"available": True, "reason": "chart_roi_required_to_avoid_axes_and_indicators",
                "components": [], "ohlc": None, "image_size": [w, h]}
    x, y, rw, rh = [int(v) for v in chart_roi]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + rw), min(h, y + rh)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("chart_roi is outside the image")
    crop = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Common MT5 red/green candle palettes; theme-dependent, so outputs stay estimates.
    green = cv2.inRange(hsv, np.array([35, 45, 45]), np.array([95, 255, 255]))
    red1 = cv2.inRange(hsv, np.array([0, 55, 45]), np.array([12, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([168, 55, 45]), np.array([180, 255, 255]))
    mask = cv2.bitwise_or(green, cv2.bitwise_or(red1, red2))
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    comps = []
    for i in range(1, count):
        bx, by, bw, bh, area = [int(v) for v in stats[i]]
        if area >= 3 and bh >= 2 and bw <= 12:
            comps.append({"x": x0 + bx, "y": y0 + by, "width": bw,
                          "height": bh, "area": area,
                          "centroid": [float(centroids[i][0] + x0),
                                       float(centroids[i][1] + y0)]})
    return {"available": True, "image_size": [w, h], "chart_roi": [x0, y0, x1-x0, y1-y0],
            "components": comps, "component_count": len(comps),
            "ohlc": None,
            "reason": "components are not reliably separable into candle bodies and wicks without chart-specific calibration"}


def analyze_chart_image(path: str | Path, *, timeframe: str | None = None,
                        chart_roi: list[int] | None = None,
                        price_axis_anchors: list[dict[str, float]] | None = None) -> dict[str, Any]:
    """Audit one screenshot; optional two anchors map detected pixel levels to price."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    try:
        from PIL import Image
        with Image.open(p) as im:
            width, height = im.size
            image_format = im.format
    except Exception as exc:
        raise ValueError(f"Unsupported or unreadable image: {exc}") from exc

    result: dict[str, Any] = {
        "source_file": p.name, "image_size": [width, height], "format": image_format,
        "timeframe": timeframe, "source_type": "SCREENSHOT",
        "extraction_status": "PARTIAL_VISUAL_EXTRACTION",
        "ocr": _optional_ocr(p),
        "chart_components": _detect_coloured_components(p, chart_roi),
        "price_calibration": None,
        "reconstructed_ohlc": None,
        "evidence_labels": {
            "ocr_values": "IMAGE_READ_ESTIMATE_REQUIRES_REVIEW",
            "pixel_components": "IMAGE_DERIVED_ESTIMATE",
            "ohlc": "NOT_RECONSTRUCTED",
        },
        "backtest_eligible": False,
        "limitations": [
            "A screenshot has no complete candle timestamps or guaranteed pixel-to-price calibration.",
            "Indicator values not legible in OCR are not inferred from line pixels.",
            "Image-derived estimates must never be merged into exact Deriv OHLC or OOS backtests.",
        ],
    }
    if price_axis_anchors:
        if len(price_axis_anchors) != 2:
            raise ValueError("Exactly two price_axis_anchors are required")
        a, b = price_axis_anchors
        result["price_calibration"] = linear_price_calibration(
            a["y"], a["price"], b["y"], b["price"])
        result["evidence_labels"]["price_calibration"] = "OPERATOR_CALIBRATED_PIXEL_ESTIMATE"
    return result


def analyze_batch(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze images independently; retain per-image failures and provenance."""
    reports = []
    for item in items:
        try:
            reports.append(analyze_chart_image(
                item["path"], timeframe=item.get("timeframe"),
                chart_roi=item.get("chart_roi"),
                price_axis_anchors=item.get("price_axis_anchors")))
        except Exception as exc:
            reports.append({"source_file": str(item.get("path")),
                            "extraction_status": "FAILED",
                            "error": f"{type(exc).__name__}: {exc}",
                            "backtest_eligible": False})
    return {"module": "SQAO_IMAGE_INTELLIGENCE", "version": "1.0.0",
            "read_only": True, "images_processed": len(reports), "images": reports,
            "policy": "No screenshot-derived OHLC is eligible for chronological backtesting."}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+")
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--output", default="DATA/step_index_image_audit.json")
    args = parser.parse_args()
    report = analyze_batch([{"path": p, "timeframe": args.timeframe} for p in args.images])
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"images_processed": report["images_processed"],
                      "output": str(out)}, indent=2))
