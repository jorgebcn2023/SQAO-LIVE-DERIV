from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Iterable

from openai import OpenAI

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")

SYSTEM_PROMPT = """You are the visual analysis and reconciliation layer of SQAO-LIVE-DERIV.

Analyze all uploaded Step Index charts jointly using the strict MTF hierarchy D1 > H1 > M15 > M5 > M1.
The quantitative snapshot is supplied by the SQAO backend and is the live-data source when present.

Rules:
- Detect timeframe from the visible chart label first, then filename.
- Never invent prices, indicators, levels, timestamps, volatility, ATR, spread, slippage, or other values.
- Separate OBSERVED facts from INFERRED scenarios.
- Check whether uploaded charts are synchronized. Flag missing, duplicated, stale, or contradictory timeframes.
- Compare visual structure against quantitative direction, EMA, RSI, ATR and latest close when supplied.
- Report quant/vision disagreement explicitly.
- Prefer WAIT or NO_TRADE when evidence is incomplete, stale, contradictory, or materially extended.
- Return exactly one final decision: LONG, SHORT, WAIT, or NO_TRADE.
- Confidence and scenario percentages are MODEL_ESTIMATE only, never historical win rates unless valid backtest data is supplied.
- Never claim certainty or guaranteed profitability.
- For the 60-minute horizon, give conditional scenarios and invalidation conditions.

Required sections:
1. DATA_STATUS
2. TIMEFRAMES
3. OBSERVED
4. QUANTITATIVE_SNAPSHOT
5. QUANT_VS_VISION
6. STRUCTURE
7. SUPPORT_RESISTANCE
8. MOMENTUM_VOLATILITY
9. 60M_SCENARIOS
10. INVALIDATION
11. RISKS
12. FINAL_DECISION
13. MISSING_DATA
"""


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _normalize_paths(paths: Iterable[str | Path | tuple[str | Path, str]]) -> list[tuple[Path, str]]:
    normalized: list[tuple[Path, str]] = []
    for item in paths:
        if isinstance(item, tuple):
            path, label = item
            normalized.append((Path(path), str(label)))
        else:
            path = Path(item)
            normalized.append((path, path.name))
    return normalized


def analyze_images(
    paths: Iterable[str | Path | tuple[str | Path, str]],
    market_snapshot: dict | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    image_items = _normalize_paths(paths)
    if not image_items:
        raise ValueError("At least one chart image is required")
    for path, _ in image_items:
        if not path.is_file():
            raise FileNotFoundError(path)

    client = OpenAI(api_key=key)
    snapshot_text = json.dumps(market_snapshot or {}, ensure_ascii=False, indent=2)[:50000]
    image_manifest = "\n".join(f"- {label}" for _, label in image_items)
    content = [{
        "type": "input_text",
        "text": (
            "Analyze these Step Index charts as one MTF set. Use visible timeframe labels. "
            "Cross-check every available timeframe against the quantitative snapshot below. "
            "If a timeframe is missing, duplicated, unreadable, stale, or temporally inconsistent, state it explicitly.\n\n"
            f"Uploaded image manifest:\n{image_manifest}\n\n"
            f"SQAO live quantitative snapshot:\n{snapshot_text}"
        ),
    }]
    for path, label in image_items:
        content.append({"type": "input_text", "text": f"Chart filename: {label}"})
        content.append({"type": "input_image", "image_url": _data_uri(path)})

    response = client.responses.create(
        model=model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        instructions=SYSTEM_PROMPT,
        input=[{"role": "user", "content": content}],
    )
    return response.output_text
