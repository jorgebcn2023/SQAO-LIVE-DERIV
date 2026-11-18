"""SQAO V3.2.0 visual evidence intake.

Records screenshot evidence without converting pixels into OHLC or unverified
indicator values. Indicator curves remain unidentified until a validated
legend/parameter association exists.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from pathlib import Path
from typing import Any

TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")
NUMERIC = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
LABELS = {
    "ema": re.compile(r"\bEMA\s*\d+\b", re.I),
    "bollinger": re.compile(r"\b(BB|BOLLINGER)\b", re.I),
    "rsi": re.compile(r"\bRSI\s*\(?\s*\d+", re.I),
    "macd": re.compile(r"\bMACD\s*\(?\s*\d+", re.I),
    "adx": re.compile(r"\bADX\s*\(?\s*\d+", re.I),
    "plus_di": re.compile(r"\+DI\s*\(?\s*\d+", re.I),
    "minus_di": re.compile(r"-DI\s*\(?\s*\d+", re.I),
    "stochastic": re.compile(r"\b(STOCH|STOCHASTIC)\b", re.I),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timeframe(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    aliases = {"1D": "D1", "DAILY": "D1", "4H": "H4", "1H": "H1",
               "60M": "H1", "15M": "M15", "5M": "M5", "1M": "M1"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in TIMEFRAMES else None


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse only explicit ISO-8601 timestamps that include a UTC offset."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def audit_image(path: str | Path, timeframe: str | None = None,
                capture_timestamp: str | None = None) -> dict[str, Any]:
    """Extract OCR evidence with coordinates and explicit unknown indicator states."""
    source = Path(path)
    if not source.is_file():
        return {"status": "FILE_NOT_FOUND", "source_file": source.name}
    result: dict[str, Any] = {
        "schema_version": "3.2.0",
        "source_file": source.name,
        "sha256": _sha256(source),
        "timeframe": _timeframe(timeframe),
        "capture_timestamp": capture_timestamp,
        "timestamp_source": "USER_METADATA" if capture_timestamp else "NOT_PROVIDED",
        "provenance": "VISUAL_RAW",
        "mode": "READ_ONLY_RESEARCH_ONLY",
        "ocr_status": "NOT_RUN",
        "image_size": None,
        "tokens": [],
        "indicator_observations": {
            key: {"status": "NOT_AVAILABLE", "value": None, "label_seen": False,
                  "curve_geometry": None}
            for key in LABELS
        },
        "ohlc": None,
        "decision": "NO_TRADE",
        "execution_eligible": False,
    }
    try:
        from PIL import Image
        import pytesseract
        from pytesseract import Output
        with Image.open(source) as image:
            result["image_size"] = list(image.size)
            data = pytesseract.image_to_data(image.convert("RGB"),
                                             output_type=Output.DICT, config="--psm 11")
        result["ocr_status"] = "OCR_OK"
        texts = []
        for index, raw in enumerate(data.get("text", [])):
            token_text = str(raw).strip()
            if not token_text:
                continue
            try:
                confidence = float(data["conf"][index])
            except (ValueError, TypeError, IndexError):
                confidence = None
            token = {
                "text": token_text,
                "confidence": confidence,
                "bbox": {
                    "x": int(data["left"][index]), "y": int(data["top"][index]),
                    "width": int(data["width"][index]), "height": int(data["height"][index]),
                },
                "numeric": bool(NUMERIC.fullmatch(token_text)),
            }
            result["tokens"].append(token)
            texts.append(token_text)
        joined = " ".join(texts)
        for key, pattern in LABELS.items():
            seen = bool(pattern.search(joined))
            result["indicator_observations"][key]["label_seen"] = seen
            if seen:
                result["indicator_observations"][key]["status"] = "LOW_CONFIDENCE"
                result["indicator_observations"][key]["note"] = (
                    "Label detected; numeric value and curve identity require panel-level association."
                )
    except ImportError as exc:
        result["ocr_status"] = "DEPENDENCY_MISSING"
        result["error"] = str(exc)
    except Exception as exc:  # OCR binary, corrupt image, or decoder failures
        result["ocr_status"] = "OCR_ENGINE_ERROR"
        result["error"] = str(exc)
    result["limitations"] = [
        "Screenshot pixels are not API OHLC and are never reconstructed as exact candles.",
        "A detected indicator label does not prove that an adjacent number belongs to it.",
        "Curve geometry is not assigned to EMA/Bollinger/oscillators without validated legend mapping.",
        "No valid capture timestamp means MTF simultaneity cannot be established.",
    ]
    return result


def audit_mtf(images: dict[str, dict[str, Any]],
              max_skew_seconds: float = 60.0) -> dict[str, Any]:
    """Validate six-frame coverage and timestamp skew; never infer missing times.

    A PASS means only that supplied metadata is complete, parseable and within
    the configured capture-time tolerance. It does not prove candle alignment.
    """
    if max_skew_seconds < 0:
        raise ValueError("max_skew_seconds must be non-negative")
    normalized = {}
    for key, value in images.items():
        tf = _timeframe(key)
        if tf and isinstance(value, dict):
            normalized[tf] = value
    missing = [tf for tf in TIMEFRAMES if tf not in normalized]
    timestamps = {tf: normalized[tf].get("capture_timestamp") for tf in normalized}
    parsed = {tf: _parse_timestamp(value) for tf, value in timestamps.items()}
    invalid = [tf for tf, stamp in parsed.items() if stamp is None]
    valid = [stamp for stamp in parsed.values() if stamp is not None]
    skew = (max((stamp.timestamp() for stamp in valid)) -
            min((stamp.timestamp() for stamp in valid))) if len(valid) == len(TIMEFRAMES) else None
    aligned = (not missing and not invalid and skew is not None
               and skew <= float(max_skew_seconds))
    return {
        "required_timeframes": list(TIMEFRAMES),
        "observed_timeframes": [tf for tf in TIMEFRAMES if tf in normalized],
        "missing_timeframes": missing,
        "capture_timestamps": timestamps,
        "invalid_timestamps": invalid,
        "timestamp_skew_seconds": round(skew, 3) if skew is not None else None,
        "max_skew_seconds": float(max_skew_seconds),
        "timestamp_alignment": "PASS" if aligned else "BLOCKED",
        "status": "PASS" if aligned else "BLOCKED",
        "alignment_scope": "CAPTURE_METADATA_ONLY_NOT_CANDLE_ALIGNMENT",
        "decision": "NO_TRADE",
        "execution_eligible": False,
    }
