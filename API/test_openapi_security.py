"""Offline OpenAPI and read-only security regression tests.

Run with: python -m API.test_openapi_security
No Deriv or Render network requests are made by this module.
"""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from API.app import _resolve_symbol, app


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = REPO_ROOT / "GPT" / "openapi.yaml"
EXPECTED_PATHS = {
    "/health",
    "/market/active-symbols",
    "/market/ohlc",
    "/analysis/snapshot",
}
MUTATING_METHODS = {"post", "put", "patch", "delete"}


def parse_openapi_path_methods(text: str) -> dict[str, dict[str, str | None]]:
    """Parse the small OpenAPI paths/operations subset used by this contract."""
    paths: dict[str, dict[str, str | None]] = {}
    in_paths = False
    current_path: str | None = None
    current_method: str | None = None

    for line in text.splitlines():
        if line == "paths:":
            in_paths = True
            continue
        if in_paths and line == "components:":
            break
        if not in_paths:
            continue

        path_match = re.match(r"^  (/[^:\s]+):\s*$", line)
        if path_match:
            current_path = path_match.group(1)
            paths[current_path] = {}
            current_method = None
            continue

        method_match = re.match(r"^    (get|post|put|patch|delete|options|head|trace):\s*$", line, re.I)
        if method_match and current_path:
            current_method = method_match.group(1).lower()
            paths[current_path][current_method] = None
            continue

        if current_method:
            operation_match = re.match(r"^\s+operationId:\s*([A-Za-z0-9_]+)\s*$", line)
            if operation_match:
                paths[current_path][current_method] = operation_match.group(1)

    return paths


class OpenAPIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = OPENAPI_PATH.read_text(encoding="utf-8")
        cls.paths = parse_openapi_path_methods(cls.text)

    def test_contract_contains_only_the_real_api_paths(self):
        self.assertEqual(set(self.paths), EXPECTED_PATHS)

    def test_every_published_operation_is_get_only(self):
        for path, methods in self.paths.items():
            with self.subTest(path=path):
                self.assertEqual(set(methods), {"get"})
                self.assertTrue(methods["get"])

    def test_operation_ids_match_the_existing_api_contract(self):
        expected = {
            "/health": "health",
            "/market/active-symbols": "getActiveStepSymbols",
            "/market/ohlc": "getStepOHLC",
            "/analysis/snapshot": "getSQAOQuantSnapshot",
        }
        for path, operation_id in expected.items():
            self.assertEqual(self.paths[path]["get"], operation_id)

    def test_only_market_and_analysis_operations_require_header_key(self):
        for path in EXPECTED_PATHS - {"/health"}:
            with self.subTest(path=path):
                block = self._path_block(path)
                self.assertRegex(block, r"(?m)^      security:\s*$")
                self.assertIn("- SQAOHeaderKey: []", block)
        self.assertNotIn("security:", self._path_block("/health"))

    def test_api_key_is_header_based_and_not_a_query_parameter(self):
        self.assertIn("name: X-SQAO-Key", self.text)
        self.assertIn("type: apiKey", self.text)
        self.assertIn("in: header", self.text)
        self.assertNotRegex(self.text, r"(?m)^\s*- name: X-SQAO-Key\s*$")

    def test_contract_declares_no_request_bodies_or_trading_paths(self):
        self.assertNotIn("requestBody:", self.text)
        self.assertFalse(any(
            re.search(r"(proposal|buy|sell|order|trade|account|balance)", path, re.I)
            for path in self.paths
        ))
        self.assertFalse(any(
            method in MUTATING_METHODS
            for methods in self.paths.values()
            for method in methods
        ))

    def test_fastapi_runtime_routes_match_contract_and_are_read_only(self):
        runtime = app.openapi()
        self.assertEqual(set(runtime["paths"]), EXPECTED_PATHS)
        for path, operations in runtime["paths"].items():
            with self.subTest(path=path):
                self.assertEqual(set(operations), {"get"})
        self.assertEqual(runtime["info"]["version"], "2.6.0")


    def _path_block(self, path: str) -> str:
        lines = self.text.splitlines()
        start = next(i for i, line in enumerate(lines) if line == f"  {path}:")
        end = next(
            (i for i in range(start + 1, len(lines))
             if re.match(r"^  /[^:\s]+:\s*$", lines[i]) or lines[i] == "components:"),
            len(lines),
        )
        return "\n".join(lines[start:end])

class SymbolResolutionFailClosedTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_resolves_single_active_candidate(self):
        candidate = [{"symbol": "STP_UNIQUE", "display_name": "Step Index"}]
        with patch("API.app._active_step_symbols", new=AsyncMock(return_value=candidate)), \
             patch.dict(os.environ, {"DERIV_STEP_NAME": ""}):
            self.assertEqual(await _resolve_symbol("AUTO"), ("STP_UNIQUE", "AUTO_UNIQUE"))

    async def test_auto_rejects_multiple_candidates_instead_of_selecting_first(self):
        candidates = [
            {"symbol": "STP_A", "display_name": "Step Index A"},
            {"symbol": "STP_B", "display_name": "Step Index B"},
        ]
        with patch("API.app._active_step_symbols", new=AsyncMock(return_value=candidates)), \
             patch.dict(os.environ, {"DERIV_STEP_NAME": ""}):
            with self.assertRaises(HTTPException) as raised:
                await _resolve_symbol("AUTO")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "AMBIGUOUS_STEP_INDEX_SYMBOL")

    async def test_preference_must_match_exactly_one_candidate(self):
        candidates = [
            {"symbol": "STP_A", "display_name": "Step Index A"},
            {"symbol": "STP_B", "display_name": "Step Index B"},
        ]
        with patch("API.app._active_step_symbols", new=AsyncMock(return_value=candidates)), \
             patch.dict(os.environ, {"DERIV_STEP_NAME": "Step Index B"}):
            self.assertEqual(await _resolve_symbol("AUTO"), ("STP_B", "AUTO_PREFERRED"))

    async def test_ambiguous_preference_is_rejected(self):
        candidates = [
            {"symbol": "STP_A", "display_name": "Step Index A"},
            {"symbol": "STP_B", "display_name": "Step Index B"},
        ]
        with patch("API.app._active_step_symbols", new=AsyncMock(return_value=candidates)), \
             patch.dict(os.environ, {"DERIV_STEP_NAME": "Step Index"}):
            with self.assertRaises(HTTPException) as raised:
                await _resolve_symbol("AUTO")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "AMBIGUOUS_STEP_INDEX_PREFERENCE")

    async def test_explicit_symbol_must_be_an_active_step_index(self):
        candidates = [{"symbol": "STP_A", "display_name": "Step Index A"}]
        with patch("API.app._active_step_symbols", new=AsyncMock(return_value=candidates)), \
             patch.dict(os.environ, {"DERIV_STEP_NAME": ""}):
            self.assertEqual(await _resolve_symbol("stp_a"), ("STP_A", "EXPLICIT"))
            with self.assertRaises(HTTPException) as raised:
                await _resolve_symbol("UNRELATED_SYMBOL")
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["code"], "STEP_INDEX_SYMBOL_NOT_VERIFIED")

    async def test_duplicate_provider_rows_do_not_create_false_ambiguity(self):
        candidates = [
            {"symbol": "STP_A", "display_name": "Step Index A"},
            {"symbol": "stp_a", "display_name": "Step Index A duplicate row"},
        ]
        with patch("API.app._active_step_symbols", new=AsyncMock(return_value=candidates)), \
             patch.dict(os.environ, {"DERIV_STEP_NAME": ""}):
            self.assertEqual(await _resolve_symbol("AUTO"), ("STP_A", "AUTO_UNIQUE"))


if __name__ == "__main__":
    unittest.main()
