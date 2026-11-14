from __future__ import annotations

import pytest

from ENGINE.deriv_symbols import select_step_index_symbol


def test_single_candidate_is_selected_without_override():
    result = select_step_index_symbol([
        {"symbol": "stpRNG", "display_name": "Step Index 100"}
    ], requested="")
    assert result["symbol"] == "stpRNG"
    assert result["selection_reason"] == "only active Step Index candidate"
    assert result["active_symbols_candidates"] == [
        {"symbol": "stpRNG", "display_name": "Step Index 100"}
    ]


def test_multiple_candidates_fail_closed_without_override():
    with pytest.raises(RuntimeError, match="AMBIGUOUS_STEP_INDEX_SYMBOL"):
        select_step_index_symbol([
            {"symbol": "stpRNG", "display_name": "Step Index 100"},
            {"symbol": "stpRNG2", "display_name": "Step Index 200"},
        ], requested="")


def test_exact_symbol_override_selects_one_candidate():
    result = select_step_index_symbol([
        {"symbol": "stpRNG", "display_name": "Step Index 100"},
        {"symbol": "stpRNG2", "display_name": "Step Index 200"},
    ], requested="stpRNG2")
    assert result["symbol"] == "stpRNG2"
    assert result["selection_reason"] == "exact DERIV_STEP_NAME match"


def test_exact_display_name_override_is_case_insensitive():
    result = select_step_index_symbol([
        {"symbol": "stpRNG", "display_name": "Step Index 100"},
        {"symbol": "stpRNG2", "display_name": "Step Index 200"},
    ], requested="step index 100")
    assert result["symbol"] == "stpRNG"


def test_partial_or_ambiguous_override_is_rejected():
    with pytest.raises(RuntimeError, match="STEP_INDEX_SYMBOL_SELECTION_FAILED"):
        select_step_index_symbol([
            {"symbol": "stpRNG", "display_name": "Step Index 100"},
            {"symbol": "stpRNG2", "display_name": "Step Index 200"},
        ], requested="Step Index")


def test_missing_candidate_is_rejected():
    with pytest.raises(RuntimeError, match="STEP_INDEX_SYMBOL_NOT_FOUND"):
        select_step_index_symbol([
            {"symbol": "R_100", "display_name": "Volatility 100 Index"}
        ], requested="")
