"""Validate the versioned SQAO plugin bundle using only the Python standard library."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "visual-audit.schema.json").read_text(encoding="utf-8"))
    instructions = (ROOT / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert manifest["version"] == "3.2.1"
    assert manifest["runtime"]["mode"] == "READ_ONLY"
    assert manifest["runtime"]["research_only"] is True
    assert manifest["runtime"]["execution_enabled"] is False
    assert manifest["runtime"]["decision_default"] == "NO_TRADE"
    assert manifest["runtime"]["execution_eligible_default"] is False
    assert manifest["api"]["service_version"] == "2.6.0"
    assert manifest["api"]["openapi_file"] == "GPT/openapi.yaml"
    assert manifest["timeframes"] == ["D1", "H4", "H1", "M15", "M5", "M1"]
    assert schema["properties"]["schema_version"]["const"] == "3.2.1"
    assert schema["properties"]["ohlc"]["type"] == "null"
    assert schema["properties"]["decision"]["const"] == "NO_TRADE"
    assert schema["properties"]["execution_eligible"]["const"] is False
    for indicator in ("ema", "bollinger", "rsi", "macd", "adx", "plus_di", "minus_di", "stochastic"):
        assert indicator in schema["properties"]["indicator_observations"]["properties"]
    assert "No reconstruir OHLC" in instructions
    assert "READ_ONLY" in readme and "NO_TRADE" in readme
    print("SQAO_PLUGIN_V3_2_1_PACKAGE_OK")

if __name__ == "__main__":
    main()
