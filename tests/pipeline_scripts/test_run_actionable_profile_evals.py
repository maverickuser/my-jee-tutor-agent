import json
import unittest
from pathlib import Path

from scripts.run_actionable_profile_evals import evaluate


class ActionableProfileEvalTest(unittest.TestCase):
    def test_versioned_fixture_passes_contract_gate(self):
        document = json.loads(Path("evals/actionable_profile_v1.json").read_text())
        result = evaluate(document)
        self.assertTrue(result["gate_passed"])
        self.assertEqual(result["source_inventory"]["structured_reports"], 18)
        self.assertEqual(result["source_inventory"]["matching_manual_embeddings"], 105)

    def test_generic_or_unsupported_advice_fails(self):
        document = {
            "schema_version": "1.0",
            "source_inventory": {"structured_reports": 18, "matching_manual_embeddings": 105},
            "cases": [
                {
                    "id": "bad",
                    "subject": "Maths",
                    "supported": True,
                    "independent_questions": 1,
                    "heading": "Be careful",
                    "do": "Revise more",
                    "ask_this_when_you_see": "",
                }
            ],
        }
        result = evaluate(document)
        self.assertFalse(result["gate_passed"])
        self.assertIn("bad:not_recurring", result["failed_assertions"])


if __name__ == "__main__":
    unittest.main()
