"""Regression tests for the read-only V3.2.1-ALT statistical package."""
import unittest
from ENGINE.stochastic.audit import run_stochastic_audit
from ENGINE.stochastic.integration import audit_mtf_closed_frames

class StochasticAltTests(unittest.TestCase):
    def test_audit_is_research_only(self):
        closes=[1000.0 + (i%7)*0.1 + i*0.01 for i in range(500)]
        result=run_stochastic_audit(closes)
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["status"], "COMPLETED_RESEARCH_ONLY")

    def test_missing_frames_fail_closed(self):
        result=audit_mtf_closed_frames({},symbol="TEST",generated_at_utc="2026-11-18T00:00:00Z")
        self.assertEqual(result["decision"],"NO_TRADE")
        self.assertFalse(result["execution_eligible"])
        self.assertEqual(result["status"],"PARTIAL_OR_BLOCKED")

    def test_sample_shortfall_is_reported_as_partial(self):
        rows=[{"epoch":1000000+i*60,"open":100+i,"high":101+i,"low":99+i,"close":100.5+i} for i in range(120)]
        result=audit_mtf_closed_frames({"M1":rows},symbol="TEST",generated_at_utc="2026-11-18T00:00:00Z",expected_count=500)
        self.assertEqual(result["status"],"PARTIAL_OR_BLOCKED")
        self.assertFalse(result["sample_coverage_complete"])
        self.assertEqual(result["timeframes"]["M1"]["sample_shortfall"],380)

    def test_gap_blocks_frame(self):
        rows=[{"epoch":1000000+i*60+(60 if i>5 else 0),"open":100+i,"high":101+i,"low":99+i,"close":100.5+i} for i in range(120)]
        result=audit_mtf_closed_frames({"M1":rows},symbol="TEST",generated_at_utc="2026-11-18T00:00:00Z")
        self.assertEqual(result["timeframes"]["M1"]["status"],"GAP_BLOCK")

if __name__ == "__main__":
    unittest.main()
