from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Iterable

from openai import OpenAI

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

SYSTEM_PROMPT = """You are the visual analysis layer of SQAO-LIVE-DERIV.
Analyze uploaded Step Index trading charts conservatively and never invent values that are not visible.
Respect the MTF hierarchy D1 > H1 > M15 > M5 > M1.
Separate visual observations from inferences. Do not claim a historical win rate unless supplied by backtest data.
Return: timeframe identification, visible structure, trend, support/resistance, momentum/volatility clues,
conflicts between timeframes, 60-minute scenarios with probabilities that are MODEL_ESTIMATE only,
and a final LONG/SHORT/WAIT/NO_TRADE assessment. State uncertainty explicitly.
"""


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def analyze_images(paths: Iterable[str | Path], market_snapshot: dict | None = None) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=api_key)
    content = [
        {
            "type": "input_text",
            "text": (
                "Analyze these Step Index charts as one MTF set. "
                "Use the chart labels/timeframes visible in the images. "
                "If a timeframe is missing, say so.\n\n"
                f"SQAO live snapshot:\n{json.dumps(market_snapshot or {}, ensure_ascii=False, indent=2)}"
            ),
        }
    ]

    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise FileNotFoundError(path)
        content.append({"type": "input_image", "image_url": _data_uri(path)})

    response = client.responses.create(
        model=DEFAULT_MODEL,
        instructions=SYSTEM_PROMPT,
        input=[{"role": "user", "content": content}],
    )
    return response.output_text
