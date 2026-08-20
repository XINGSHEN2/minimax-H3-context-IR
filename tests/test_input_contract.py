import copy
import json
import unittest
from pathlib import Path

try:
    from remote_source.backend.context_ir import (
        compile_context_ir,
        normalize_source_request,
        validate_context_ir,
        validate_source_request,
    )
except ModuleNotFoundError:
    from backend.context_ir import (
        compile_context_ir,
        normalize_source_request,
        validate_context_ir,
        validate_source_request,
    )

try:
    from remote_source.backend.perception import _json_object
except ModuleNotFoundError:
    from backend.perception import _json_object


ROOT = Path(__file__).resolve().parents[1]


class SourceContractTests(unittest.TestCase):
    def test_flattened_localization_boxes_are_recovered(self):
        malformed = '{"boxes":[["car tire",0,88,900,747],"car",0,0,1000,747,"air pump",640,397,875,688]}'
        parsed = _json_object(malformed)
        self.assertEqual(len(parsed["boxes"]), 3)
        self.assertEqual(parsed["boxes"][2][0], "air pump")

    def test_legacy_request_normalizes_to_direct(self):
        source = normalize_source_request(
            {
                "user_request": "Create a product video",
                "task": {"type": "t2va"},
                "assets": [],
            }
        )
        self.assertEqual(source["schema_version"], "context_request.v1")
        self.assertEqual(source["directives"], [])
        self.assertTrue(source["completion_policy"]["technical"])
        self.assertFalse(source["completion_policy"]["creative"])
        self.assertTrue(validate_source_request(source).passed)

    def test_resolved_example_is_valid(self):
        source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        self.assertTrue(validate_source_request(source).passed)

    def test_legacy_resolution_is_flattened_without_modes(self):
        source = normalize_source_request(
            {
                "user_request": "Use this reference video",
                "assets": [],
                "intent_resolution": {
                    "status": "resolved",
                    "summary": "Use the product",
                    "directives": [
                        {
                            "directive_id": "d1",
                            "asset_id": "",
                            "target": "product",
                            "operation": "preserve",
                            "scope": ["appearance"],
                            "priority": "hard",
                            "provenance": "explicit_user",
                        }
                    ],
                    "open_questions": [],
                },
            }
        )
        self.assertNotIn("intent_resolution", source)
        self.assertEqual(source["resolved_request"], "Use the product")
        self.assertEqual(source["directives"][0]["directive_id"], "d1")
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

    def test_compile_restores_authoritative_resolved_intent(self):
        source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        model_output = self._minimal_ir(source)
        model_output["intent"]["user_request"] = "mutated"
        model_output["intent"]["directives"] = []
        compiled = compile_context_ir(model_output, source)
        self.assertEqual(compiled["intent"]["user_request"], source["user_request"])
        self.assertEqual(
            compiled["intent"]["directives"],
            source["directives"],
        )

    def test_missing_directive_binding_coverage_is_rejected(self):
        source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        ir = self._minimal_ir(source)
        ir["asset_bindings"][0]["source_directive_ids"] = []
        report = validate_context_ir(ir)
        self.assertFalse(report.passed)
        self.assertIn("DIRECTIVE_BINDING_COVERAGE", {item.code for item in report.issues})

    @staticmethod
    def _minimal_ir(source):
        directives = copy.deepcopy(source["directives"])
        all_ids = [item["directive_id"] for item in directives]
        return {
            "schema_version": "0.1.0",
            "runtime": {},
            "intent": {
                "user_request": source["user_request"],
                "resolved_request": source["resolved_request"],
                "directives": directives,
                "completion_policy": copy.deepcopy(source["completion_policy"]),
                "assumptions": [],
                "uncertainties": [],
            },
            "protocol": {
                "rewrite_language": "English",
                "preserve_source_language_for": ["visible scene text"],
                "summary_task_types": ["reference generation"],
            },
            "task": copy.deepcopy(source["task"]),
            "assets": copy.deepcopy(source["assets"]),
            "perception": None,
            "asset_bindings": [
                {
                    "binding_id": "b_all",
                    "asset_id": "image_1",
                    "target": "performer manicure and execution constraints",
                    "role": "product",
                    "priority": "hard",
                    "source_directive_ids": all_ids,
                    "inherit": ["resolved product and execution directives"],
                    "exclude": ["product photo background"],
                }
            ],
            "subjects": [
                {
                    "subject_id": "subject_1",
                    "name": "product manicure",
                    "kind": "product",
                    "primary": True,
                    "description": "the product manicure worn by the performer",
                    "source_asset_ids": ["image_1"],
                    "binding_ids": ["b_all"],
                    "appearance_shot_ids": ["01"],
                    "retention_mode": "attribute_transfer",
                    "retention_description": "product appearance transfers to the performer",
                }
            ],
            "reference_relationships": [
                {
                    "asset_id": "image_1",
                    "relationship": "reference_generation",
                    "subject_refs": ["subject_1"],
                    "definition": "authoritative product appearance",
                    "retention_mode": "attribute_transfer",
                    "retention_description": "product attributes transfer to the manicure",
                },
                {
                    "asset_id": "video_1",
                    "relationship": "reference_generation",
                    "subject_refs": ["subject_1"],
                    "definition": "performer and performance reference",
                    "retention_mode": "partially_preserved",
                    "retention_description": "resolved performer and motion attributes are preserved",
                },
            ],
            "creative_focus": {
                "primary_target": "product manicure",
                "primary_subject_id": "subject_1",
                "primary_asset_id": "image_1",
                "primary_binding_ids": ["b_all"],
                "objective": "show the product manicure on the performer",
                "supporting_asset_ids": ["video_1"],
                "required_shot_ids": ["01"],
                "presentation_requirements": ["keep the manicure visible"],
            },
            "isolation_rules": [
                {
                    "binding_id": "b_all",
                    "allow": ["product appearance"],
                    "block": ["product photo background"],
                }
            ],
            "constraints": {
                "preserve": ["resolved hard attributes"],
                "allow_change": ["resolved soft attributes"],
                "prohibit": ["unsupported additions"],
            },
            "timeline": [
                {
                    "shot_id": "01",
                    "start_seconds": 0,
                    "end_seconds": 15,
                    "event": "performer displays the product manicure",
                    "action": "display hands",
                    "camera": "medium close-up",
                    "lighting": "commercial lighting",
                    "transition": "end",
                    "subject_refs": ["subject_1"],
                    "asset_refs": ["image_1", "video_1"],
                    "binding_refs": ["b_all"],
                }
            ],
            "audio_plan": {
                "voice": "",
                "music": "",
                "sound_effects": "",
                "ambient_sound": "",
                "sync_rules": [],
            },
            "generation_description": {
                "cinematography": "reference structure",
                "lighting": "commercial lighting",
                "materials": "glossy nails",
                "performance": "preserved performance",
                "continuity": "fixed manicure assignment",
            },
        }


if __name__ == "__main__":
    unittest.main()
