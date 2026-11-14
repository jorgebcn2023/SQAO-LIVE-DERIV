from __future__ import annotations

import unittest

from ENGINE.deriv_symbols import select_step_index_symbol


class StepIndexSymbolSelectionTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"symbol": "stpRNG", "display_name": "Step Index 100"},
            {"symbol": "stpRNG2", "display_name": "Step Index 200"},
        ]

    def test_single_candidate_is_selected_without_override(self):
        result = select_step_index_symbol(self.candidates[:1], requested="")
        self.assertEqual(result["symbol"], "stpRNG")
        self.assertEqual(result["selection_reason"], "only active Step Index candidate")
        self.assertEqual(len(result["active_symbols_candidates"]), 1)

    def test_multiple_candidates_fail_closed_without_override(self):
        with self.assertRaisesRegex(RuntimeError, "AMBIGUOUS_STEP_INDEX_SYMBOL"):
            select_step_index_symbol(self.candidates, requested="")

    def test_exact_symbol_override_selects_one_candidate(self):
        result = select_step_index_symbol(self.candidates, requested="stpRNG2")
        self.assertEqual(result["symbol"], "stpRNG2")

    def test_exact_display_name_override_is_case_insensitive(self):
        result = select_step_index_symbol(self.candidates, requested="step index 100")
        self.assertEqual(result["symbol"], "stpRNG")

    def test_partial_override_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "STEP_INDEX_SYMBOL_SELECTION_FAILED"):
            select_step_index_symbol(self.candidates, requested="Step Index")

    def test_missing_candidate_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "STEP_INDEX_SYMBOL_NOT_FOUND"):
            select_step_index_symbol(
                [{"symbol": "R_100", "display_name": "Volatility 100 Index"}],
                requested="",
            )


if __name__ == "__main__":
    unittest.main()
