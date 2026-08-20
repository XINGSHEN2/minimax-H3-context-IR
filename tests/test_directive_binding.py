import copy
import unittest

from backend.directive_binding import compile_directive_bindings


class DirectiveBindingCompilerTests(unittest.TestCase):
    def test_repairs_contract_and_routes_global_directives(self):
        source = {
            "assets": [{"asset_id": "image_1"}, {"asset_id": "video_1"}],
            "directives": [
                {"directive_id": "d_product", "asset_id": "image_1", "target": "product appearance", "operation": "preserve", "scope": ["shape", "color"], "priority": "hard"},
                {"directive_id": "d_motion", "asset_id": "video_1", "target": "motion and timing", "operation": "transfer", "scope": ["hand actions", "timing"], "priority": "hard"},
                {"directive_id": "d_exclude", "asset_id": "video_1", "target": "reference contamination", "operation": "exclude", "scope": ["person identity", "product appearance"], "priority": "hard"},
                {"directive_id": "d_no_text", "asset_id": "", "target": "visible extras", "operation": "exclude", "scope": ["subtitles"], "priority": "hard"},
            ],
        }
        payload = {"asset_bindings": [
            {"binding_id": "b_product", "asset_id": "image_1", "role": "product", "priority": "soft", "source_directive_ids": ["d_product"], "inherit": [], "exclude": []},
            {"binding_id": "b_fake", "asset_id": "global", "role": "scene", "priority": "hard", "source_directive_ids": ["d_no_text"], "inherit": [], "exclude": []},
        ], "isolation_rules": [], "constraints": {}, "timeline": [], "subjects": [], "creative_focus": {"primary_binding_ids": ["b_product", "b_fake"]}}
        result = compile_directive_bindings(copy.deepcopy(payload), source)
        self.assertNotIn("b_fake", {item["binding_id"] for item in result["asset_bindings"]})
        product = next(item for item in result["asset_bindings"] if item["asset_id"] == "image_1")
        self.assertEqual(product["priority"], "hard")
        self.assertEqual(product["inherit"], ["shape", "color"])
        video = next(item for item in result["asset_bindings"] if item["asset_id"] == "video_1")
        self.assertIn("hand actions", video["inherit"])
        self.assertIn("person identity", video["exclude"])
        rule = next(item for item in result["isolation_rules"] if item["binding_id"] == video["binding_id"])
        self.assertIn("person identity", rule["block"])
        self.assertIn("subtitles", result["constraints"]["prohibit"])


if __name__ == "__main__":
    unittest.main()
