import copy, json, unittest
from pathlib import Path
from backend.contracts import normalize_source_request, validate_source_request
ROOT = Path(__file__).resolve().parents[1]

class SourceContractTests(unittest.TestCase):







    def test_resolved_example_is_valid(self):
        source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        self.assertTrue(validate_source_request(source).passed)

    def test_unknown_directive_asset_is_rejected(self):
        source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        source["directives"][0]["asset_id"] = "missing"
        report = validate_source_request(source)
        self.assertFalse(report.passed)
        self.assertIn("DIRECTIVE_ASSET_UNKNOWN", {item.code for item in report.issues})

    def test_conflicting_hard_directives_are_rejected(self):
        source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        conflict = copy.deepcopy(source["directives"][1])
        conflict["directive_id"] = "d_identity_replace_conflict"
        conflict["operation"] = "replace"
        source["directives"].append(conflict)
        report = validate_source_request(source)
        self.assertFalse(report.passed)
        self.assertIn("DIRECTIVE_CONFLICT", {item.code for item in report.issues})
