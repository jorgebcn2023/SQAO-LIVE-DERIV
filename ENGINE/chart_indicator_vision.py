"""SQAO chart indicator vision: trace geometry only, no synthetic OHLC.
A pane must be explicitly mapped to an indicator (or label-confirmed); otherwise
traces remain unclassified. Pixel trends are normalized image-space observations.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import math
import re

VERSION = "1.1.0"
SUPPORTED = ("EMA", "BOLLINGER", "RSI", "MACD", "ADX", "STOCHASTIC")


def _load_cv():
    try:
        import cv2
        import numpy as np
        return cv2, np
    except Exception as exc:
        raise RuntimeError("opencv-python-headless and numpy are required for color-trace analysis") from exc


def _trend(points: list[dict[str, Any]]) -> dict[str, Any]:
    if len(points) < 4:
        return {"status": "INSUFFICIENT_TRACE", "direction": "NOT_ASSESSED",
                "net_change_normalized": None, "slope_normalized": None}
    n = len(points)
    first = sum(p["y_norm"] for p in points[:max(1, n // 5)]) / max(1, n // 5)
    last_slice = points[-max(1, n // 5):]
    last = sum(p["y_norm"] for p in last_slice) / len(last_slice)
    delta = last - first
    # Screen y grows downwards: negative delta means visually rising.
    direction = "RISING" if delta < -0.025 else "FALLING" if delta > 0.025 else "FLAT"
    xs = [p["x_norm"] for p in points]
    ys = [p["y_norm"] for p in points]
    xm, ym = sum(xs) / n, sum(ys) / n
    denom = sum((x - xm) ** 2 for x in xs)
    slope = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / denom if denom else 0.0
    return {"status": "TRACE_OBSERVED", "direction": direction,
            "net_change_normalized": round(delta, 5),
            "slope_normalized": round(slope, 5),
            "interpretation": "IMAGE_SPACE_ONLY; RISING/FALLING refers to pixel geometry, not price or oscillator value"}


def _trace_colors(crop, min_saturation: int = 65, min_value: int = 55):
    cv2, np = _load_cv()
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, w = crop.shape[:2]
    # Ignore near-white text and low-saturation chart grids. Hue bins separate
    # colored overlays; hue names are deliberately not mapped to indicator names.
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    eligible = (sat >= min_saturation) & (val >= min_value)
    hue = hsv[:, :, 0]
    groups = []
    for center in range(0, 180, 15):
        lo, hi = max(0, center - 7), min(179, center + 7)
        mask = (eligible & (hue >= lo) & (hue <= hi)).astype("uint8") * 255
        # Remove isolated pixels; preserve narrow continuous traces.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        counts = (mask > 0).sum(axis=0)
        active = [x for x, count in enumerate(counts) if count > 0]
        if len(active) < max(8, int(w * 0.08)):
            continue
        # A robust per-column median y traces the line without inventing gaps.
        pts = []
        for x in active:
            ys = np.where(mask[:, x] > 0)[0]
            if len(ys):
                pts.append({"x_norm": round(x / max(1, w - 1), 5),
                            "y_norm": round(float(np.median(ys)) / max(1, h - 1), 5),
                            "pixel_count": int(len(ys))})
        if len(pts) >= max(8, int(w * 0.08)):
            groups.append({"hue_center_hsv": center, "coverage": round(len(pts) / w, 4),
                           "points": pts, "evolution": _trend(pts)})
    groups.sort(key=lambda x: x["coverage"], reverse=True)
    # Hue windows overlap slightly; retain strongest non-nearby hue groups.
    selected = []
    for group in groups:
        if all(abs(group["hue_center_hsv"] - x["hue_center_hsv"]) > 8 for x in selected):
            selected.append(group)
    return selected[:8]


def analyze_indicator_panes(path: str | Path, timeframe: str | None,
                            pane_rois: dict[str, list[int]] | None = None,
                            legend_roi: list[int] | None = None) -> dict[str, Any]:
    """Analyze named pane ROIs: {EMA:[x,y,w,h], RSI:[...], ...}, pixel coordinates."""
    cv2, np = _load_cv()
    p = Path(path)
    image = cv2.imread(str(p))
    if image is None:
        return {"status": "IMAGE_UNREADABLE", "timeframe": timeframe, "panes": {}}
    height, width = image.shape[:2]
    legend = _ocr_legend_colors(p, legend_roi)
    panes: dict[str, Any] = {}
    for raw_name, roi in (pane_rois or {}).items():
        name = str(raw_name).upper()
        if name not in SUPPORTED:
            panes[name] = {"status": "UNSUPPORTED_PANE_LABEL", "traces": []}
            continue
        if len(roi) != 4:
            panes[name] = {"status": "INVALID_ROI", "traces": []}
            continue
        x, y, rw, rh = [int(v) for v in roi]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(width, x + rw), min(height, y + rh)
        if x1 <= x0 or y1 <= y0:
            panes[name] = {"status": "ROI_OUT_OF_BOUNDS", "traces": []}
            continue
        crop = image[y0:y1, x0:x1]
        traces = _trace_colors(crop)
        _attach_legend_identity(traces, legend)
        try:
            scale = _axis_scale(image, [x0, y0, x1-x0, y1-y0])
        except Exception as exc:
            scale = {"status": "AXIS_OCR_FAILED", "reason": type(exc).__name__}
        if scale.get("status") in ("CALIBRATED", "LOW_CONFIDENCE"):
            for trace in traces:
                for point in trace["points"]:
                    py = y0 + point["y_norm"] * max(1, y1-y0-1)
                    point["axis_value_estimate"] = round(scale["value_per_pixel"]*py+scale["intercept"], 4)
                    point["axis_value_provenance"] = "VISUAL_ESTIMATE_FROM_OCR_AXIS"
        panes[name] = {
            "status": "TRACES_FOUND" if traces else "NO_COLOR_TRACE",
            "roi_xywh": [x0, y0, x1 - x0, y1 - y0],
            "association": "OPERATOR_CONFIGURED_PANE; indicator identity is not inferred from color",
            "trace_count": len(traces),
            "axis_calibration": scale,
            "traces": traces,
            "indicator_specific_observations": _indicator_observations(name, traces),
        }
    return {
        "module": "SQAO_CHART_INDICATOR_VISION", "version": VERSION,
        "timeframe": timeframe, "image_size": [width, height],
        "legend_color_mapping": legend,
        "status": "ANALYZED" if panes else "PANE_ROIS_REQUIRED",
        "panes": panes,
        "limitations": [
            "Color traces are image-space observations, not exact indicator values.",
            "Indicator-to-pane association requires configured ROI or independently verified label.",
            "Legend-color matches are OCR/pixel estimates; ambiguous hue matches remain unmapped.",
            "Axis calibration is accepted only from at least two OCR numeric labels and remains a visual estimate.",
            "No price/oscillator values, OHLC candles, timestamps or trade levels are reconstructed.",
            "Color themes, anti-aliasing, overlapping traces and chart zoom can reduce detection reliability.",
        ],
    }


def _indicator_observations(name: str, traces: list[dict[str, Any]]) -> dict[str, Any]:
    evolutions = [t["evolution"] for t in traces]
    observed = [e for e in evolutions if e.get("status") == "TRACE_OBSERVED"]
    if name == "EMA":
        return {"ema_line_geometry": [e["direction"] for e in observed],
                "stack_order": "NOT_ASSESSED",
                "crossovers": "NOT_ASSESSED",
                "note": "Line direction is tracked; EMA9/20/50 identity needs legend-color mapping."}
    if name == "BOLLINGER":
        if len(traces) < 2:
            return {"band_width_evolution": "NOT_ASSESSED", "upper_lower_identity": "NOT_ASSESSED"}
        top = min(traces, key=lambda t: sum(p["y_norm"] for p in t["points"]) / len(t["points"]))
        bottom = max(traces, key=lambda t: sum(p["y_norm"] for p in t["points"]) / len(t["points"]))
        top_map = {round(p["x_norm"], 3): p["y_norm"] for p in top["points"]}
        bot_map = {round(p["x_norm"], 3): p["y_norm"] for p in bottom["points"]}
        common = sorted(set(top_map) & set(bot_map))
        widths = [bot_map[x] - top_map[x] for x in common]
        if len(widths) < 4:
            change = "NOT_ASSESSED"
        else:
            change = "EXPANDING" if sum(widths[-max(1,len(widths)//5):])/max(1,len(widths)//5) > sum(widths[:max(1,len(widths)//5)])/max(1,len(widths)//5) * 1.08 else "CONTRACTING_OR_STABLE"
        return {"band_width_evolution": change, "upper_lower_identity": "GEOMETRIC_EXTREMES_ONLY"}
    if name in ("RSI", "MACD", "ADX", "STOCHASTIC"):
        return {"line_evolution": [e["direction"] for e in observed],
                "crossovers": "NOT_ASSESSED",
                "threshold_zones": "NOT_ASSESSED",
                "note": "No numeric scale or signal-line identity is assumed from pixels."}
    return {"status": "NOT_ASSESSED"}
