from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Iterable

from openai import OpenAI

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")

SYSTEM_PROMPT = """You are the visual analysis layer of SQAO-LIVE-DERIV.
Analyze all uploaded Step Index trading charts jointly using MTF order D1 > H1 > M15 > M5 > M1.
Do not invent prices, indicators, levels, timestamps, or values that are not legible.
Separate OBSERVED facts from INFERRED scenarios.
Identify stale, missing, or contradictory timeframes.
Return a conservative decision: LONG, SHORT, WAIT, or NO_TRADE.
Confidence values are MODEL_ESTIMATE only, never historical win rates unless supplied by valid backtest data.
Never claim certainty or guaranteed profitability.
Return sections: TIMEFRAMES, OBSERVED, STRUCTURE, SUPPORT_RESISTANCE, MOMENTUM_VOLATILITY,
60M_SCENARIOS, QUANT_VS_VISION, INVALIDATION, RISKS, FINAL_DECISION, MISSING_DATA.
"""


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def analyze_images(paths: Iterable[str | Path], market_snapshot: dict | None = None,
                   model: str | None = None) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    image_paths = [Path(p) for p in paths]
    if not image_paths:
        raise ValueError("At least one chart image is required")
    for path in image_paths:
        if not path.is_file():
            raise FileNotFoundError(path)

    client = OpenAI(api_key=api_key)
    content = [{
        "type": "input_text",
        "text": (
            "Analyze these Step Index charts as one MTF set. Use visible timeframe labels. "
            "If a timeframe is missing or unreadable, state it explicitly.\n\n"
            f"SQAO live quantitative snapshot:\n{json.dumps(market_snapshot or {}, ensure_ascii=False, indent=2)[:30000]}"
        ),
    }]
    for path in image_paths:
        content.append({"type": "input_image", "image_url": _data_uri(path)})

    response = client.responses.create(
        model=model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        instructions=SYSTEM_PROMPT,
        input=[{"role": "user", "content": content}],
    )
    return response.output_text
