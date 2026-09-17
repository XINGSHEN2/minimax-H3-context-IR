import copy, json, unittest
from pathlib import Path
from backend.contracts import normalize_source_request, validate_source_request
from backend.perception import _json_object, _canonical_entity_reference, _analysis_profile, _evidence_coverage, _required_supplements
ROOT = Path(__file__).resolve().parents[1]

class SourceContractTests(unittest.TestCase):
    def test_only_missing_required_evidence_triggers_supplement(self):
        analysis = {"asset_id": "image_1", "summary": "red bottle with a gold cap", "entities": []}
        plan = {"evidence_requirements": [
            {"claim": "label wording", "priority": "required", "max_retries": 1},
            {"claim": "logo typography", "priority": "useful", "max_retries": 0},
            {"claim": "decorative sparkle", "priority": "optional", "max_retries": 0},
            {"claim": "gold cap", "priority": "required", "max_retries": 1},
        ]}
        coverage = _evidence_coverage(analysis, plan)
        supplements = _required_supplements(coverage)
        self.assertEqual([item["claim"] for item in supplements], ["label wording"])

    def test_global_analysis_satisfies_structural_evidence_without_supplement(self):
        analysis = {
            "asset_id": "image_1",
            "summary": "street scene",
            "global_analysis": {
                "composition": "centered subject within a fixed dual circular frame",
                "framing_layers": [{"description": "binocular double-circle mask"}],
            },
            "entities": [],
        }
        plan = {"evidence_requirements": [
            {"claim": "core composition elements and their positions", "priority": "required", "max_retries": 1},
            {"claim": "fixed dual circular frame", "priority": "required", "max_retries": 1},
        ]}
        coverage = _evidence_coverage(analysis, plan)
        self.assertEqual(_required_supplements(coverage), [])

    def test_required_evidence_has_at_most_one_attempt(self):
        coverage = [{"claim": "finger mapping", "priority": "required", "status": "missing", "attempts": 1, "max_retries": 3}]
        self.assertEqual(_required_supplements(coverage), [])

    def test_perception_profiles_follow_asset_roles(self):
        image = {"media_type": "image", "user_role": "reference"}
        video = {"media_type": "video", "user_role": "reference"}
        self.assertEqual(_analysis_profile(image, {"role": "authoritative_product_appearance"}), "single_pass")
        self.assertEqual(_analysis_profile(image, {"role": "connection_reference"}), "single_pass")
        self.assertEqual(_analysis_profile(image, {"role": "motion_reference"}), "single_pass")
        self.assertEqual(_analysis_profile(video, {
            "role": "motion_reference",
            "analyze": ["action sequence", "camera framing", "shot pacing", "scene transitions"],
            "do_not_infer": ["presenter identity", "product appearance", "outfit", "scene"],
        }), "timeline_only")
        self.assertEqual(_analysis_profile(video, {
            "role": "edit_base",
            "analyze": ["identity", "outfit", "product appearance", "scene detail"],
            "do_not_infer": [],
        }), "timeline_and_entities")

    def test_truncated_json_tail_is_closed_without_semantic_reconstruction(self):
        parsed = _json_object('{"summary":"visible relation","entities":[]')
        self.assertEqual(parsed["summary"], "visible relation")
        self.assertEqual(parsed["_parse_recovery"], "closed_truncated_tail")

    def test_entity_reference_punctuation_drift_is_recovered(self):
        self.assertEqual(_canonical_entity_reference("entity3", {"entity_2", "entity_3"}), "entity_3")
        self.assertEqual(_canonical_entity_reference("unknown3", {"entity_3"}), "unknown3")

    def test_flattened_localization_boxes_are_recovered(self):
        malformed = '{"boxes":[["car tire",0,88,900,747],"car",0,0,1000,747,"air pump",640,397,875,688]}'
        parsed = _json_object(malformed)
        self.assertEqual(len(parsed["boxes"]), 3)
        self.assertEqual(parsed["boxes"][2][0], "air pump")

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
