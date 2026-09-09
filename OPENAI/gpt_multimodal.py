"""GPT multimodal analyzer for SQAO chart images.

Read-only analysis layer. Requires OPENAI_API_KEY in the environment.
Does not place trades or access Deriv account functions.
"""
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
Analyze all supplied trading charts jointly using the MTF order D1 > H1 > M15 > M5 > M1.
Do not invent prices, indicators, levels, timestamps, or values that are not legible.
Separate OBSERVED facts from INFERRED scenarios.
Identify stale, missing, or contradictory timeframes.
Return a conservative decision: LONG, SHORT, WAIT, or NO_TRADE.
Confidence values are MODEL_ESTIMATE only, not historical win rates.
Never claim guaranteed profitability.
"""


def _image_part(path: Path) -> dict:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime};base64,{data}"}


def analyze(images: Iterable[str | Path], live_analysis_path: str | Path | None = None,
            model: str = DEFAULT_MODEL) -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    image_paths = [Path(p) for p in images]
    missing = [str(p) for p in image_paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))

    context = "No SQAO live snapshot supplied."
    if live_analysis_path:
        p = Path(live_analysis_path)
        if p.is_file():
            context = p.read_text(encoding="utf-8")[:20000]

    prompt = (
        "Analyze these chart images as one MTF set. Preserve any visible timeframe labels.\n\n"
        "SQAO live quantitative snapshot:\n" + context + "\n\n"
        "Return sections: DECISION, CONFIDENCE, OBSERVED, SCENARIOS_60M, RISKS, "
        "QUANT_VS_VISION, INVALIDATION, MISSING_DATA."
    )

    content = [{"type": "input_text", "text": prompt}]
    content.extend(_image_part(p) for p in image_paths)

    client = OpenAI(api_key=key)
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {"role": "user", "content": content},
        ],
    )
    return response.output_text


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+", help="Chart image paths")
    parser.add_argument("--live", default="DATA/live_analysis.json")
    parser.add_argument("--output", default="DATA/gpt_analysis.md")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    result = analyze(args.images, args.live, args.model)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result, encoding="utf-8")
    print(result)


if __name__ == "__main__":
    main()
