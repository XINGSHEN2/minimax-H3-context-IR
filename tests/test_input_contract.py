import copy
import json
import unittest
from pathlib import Path

try:
    from remote_source.backend.context_ir import (
        compile_context_ir,
        normalize_source_request,
        render_h3_prompt,
        audit_h3_prompt,
        validate_context_ir,
        validate_source_request,
    )
except ModuleNotFoundError:
    from backend.context_ir import (
        compile_context_ir,
        normalize_source_request,
        render_h3_prompt,
        audit_h3_prompt,
        validate_context_ir,
        validate_source_request,
    )

try:
    from remote_source.backend.perception import _json_object, _canonical_entity_reference, _analysis_profile
except ModuleNotFoundError:
    from backend.perception import _json_object, _canonical_entity_reference, _analysis_profile


ROOT = Path(__file__).resolve().parents[1]


class SourceContractTests(unittest.TestCase):
    def test_perception_profiles_follow_asset_roles(self):
        image = {"media_type": "image", "user_role": "reference"}
        video = {"media_type": "video", "user_role": "reference"}
        self.assertEqual(_analysis_profile(image, {"role": "authoritative_product_appearance"}), "staged_detail")
        self.assertEqual(_analysis_profile(image, {"role": "connection_reference"}), "relational_one_shot")
        self.assertEqual(_analysis_profile(image, {"role": "motion_reference"}), "relational_one_shot")
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
        self.assertTrue(source["task"]["generate_audio"])
        self.assertTrue(validate_source_request(source).passed)

    def test_audio_enabled_ir_requires_an_overall_soundscape(self):
        source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        ir = self._minimal_ir(source)
        ir["task"]["generate_audio"] = True
        ir["audio_plan"] = {
            "voice": "",
            "music": "",
            "sound_effects": "",
            "ambient_sound": "",
            "sync_rules": [],
        }
        report = validate_context_ir(ir)
        self.assertFalse(report.passed)
        self.assertIn("AUDIO_SOUNDSCAPE_EMPTY", {item.code for item in report.issues})

        ir["audio_plan"]["ambient_sound"] = "quiet room tone"
        ir["audio_plan"]["sound_effects"] = "soft synchronized product handling Foley"
        report = validate_context_ir(ir)
        self.assertIn("AUDIO_SYNC_RULES_EMPTY", {item.code for item in report.issues})
        ir["audio_plan"]["sync_rules"] = ["Foley follows the visible hand movement"]
        self.assertTrue(validate_context_ir(ir).passed)

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

    def test_hard_directive_cannot_bind_to_another_asset(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = self._minimal_ir(source)
        ir["asset_bindings"][0]["asset_id"] = "video_1"
        report = validate_context_ir(ir)
        self.assertFalse(report.passed)
        self.assertIn("BINDING_DIRECTIVE_ASSET_MISMATCH", {item.code for item in report.issues})

    def test_compile_repairs_model_directive_asset_mismatch(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = self._minimal_ir(source)
        wrong = copy.deepcopy(ir["asset_bindings"][0])
        wrong["binding_id"] = "b_wrong_cross_asset_reference"
        wrong["asset_id"] = "video_1"
        ir["asset_bindings"].append(wrong)
        ir["isolation_rules"].append({
            "binding_id": wrong["binding_id"],
            "allow": copy.deepcopy(wrong["inherit"]),
            "block": copy.deepcopy(wrong["exclude"]),
        })
        compiled = compile_context_ir(ir, source)
        report = validate_context_ir(compiled)
        self.assertTrue(report.passed, report.to_dict())
        directive_assets = {
            item["directive_id"]: item.get("asset_id", "")
            for item in source["directives"]
        }
        for binding in compiled["asset_bindings"]:
            for directive_id in binding["source_directive_ids"]:
                self.assertIn(directive_assets[directive_id], ("", binding["asset_id"]))

    def test_each_shot_requires_primary_change_and_observable_end_state(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = self._minimal_ir(source)
        ir["timeline"][0].pop("primary_change")
        ir["timeline"][0].pop("observable_end_state")
        codes = {item.code for item in validate_context_ir(ir).issues}
        self.assertIn("SHOT_PRIMARY_CHANGE_MISSING", codes)
        self.assertIn("SHOT_END_STATE_MISSING", codes)

    def test_compile_attaches_primary_binding_to_required_focus_shot(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = self._minimal_ir(source)
        primary_binding = ir["creative_focus"]["primary_binding_ids"][0]
        ir["timeline"][0]["binding_refs"] = [
            value for value in ir["timeline"][0]["binding_refs"]
            if value != primary_binding
        ]
        compiled = compile_context_ir(ir, source)
        self.assertIn(primary_binding, compiled["timeline"][0]["binding_refs"])

    def test_renderer_cites_appearance_picture_inside_subject(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = compile_context_ir(self._minimal_ir(source), source)
        prompt = render_h3_prompt(ir)
        self.assertIn("<Picture 1>", prompt.split("summary:", 1)[0])
        self.assertIn("Production permissions:", prompt)
        self.assertIn("text: mode=disabled", prompt)
        self.assertNotRegex(prompt.split("summary:", 1)[0], r"(?m)^<Picture 1> is ")
        self.assertTrue(audit_h3_prompt(ir, prompt).passed)

    def test_renderer_guards_structural_subject_video_from_appearance(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["subjects"][0]["binding_ids"] = ["b_product", "b_motion"]
        ir = compile_context_ir(model_ir, source)
        prompt = render_h3_prompt(ir)
        definitions = prompt.split("summary:", 1)[0]
        self.assertIn("<Video 1> is not an appearance source", definitions)
        self.assertTrue(audit_h3_prompt(ir, prompt).passed)

    def test_policy_normalization_enforces_entity_truth_and_safe_defaults(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir.pop("production_policies")
        model_ir.pop("entity_constraints")
        ir = compile_context_ir(model_ir, source)
        self.assertEqual(ir["production_policies"]["lighting"]["mode"], "auto")
        self.assertFalse(ir["production_policies"]["lighting"]["allow_new_events"])
        self.assertEqual(ir["production_policies"]["effects"]["mode"], "disabled")
        self.assertEqual(ir["production_policies"]["text"]["mode"], "disabled")
        for module in ("identity", "product", "continuity"):
            self.assertEqual(ir["entity_constraints"][module]["mode"], "strict")
            self.assertEqual(ir["entity_constraints"][module]["priority"], "hard")

    def test_source_edit_preserves_execution_modules_unless_user_overrides(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["reference_relationships"][1]["relationship"] = "source_video_edit"
        model_ir["protocol"]["summary_task_types"] = ["reference generation", "video editing"]
        model_ir["production_policies"]["lighting"].update({
            "mode": "enhance", "source": "explicit_user", "priority": "hard",
            "allow_new_events": True,
        })
        ir = compile_context_ir(model_ir, source)
        for module in ("camera", "editing", "motion", "audio"):
            self.assertEqual(ir["production_policies"][module]["mode"], "reference")
            self.assertEqual(ir["production_policies"][module]["priority"], "hard")
        self.assertEqual(ir["production_policies"]["lighting"]["mode"], "enhance")

    def test_disabled_policy_events_are_removed_deterministically(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["production_policies"]["effects"]["events"] = [{
            "event_id": "bad", "description": "unsupported sparkle", "source": "category_prior", "shot_refs": ["01"]
        }]
        ir = compile_context_ir(model_ir, source)
        self.assertEqual(ir["production_policies"]["effects"]["events"], [])

    @staticmethod
    def _minimal_ir(source):
        directives = copy.deepcopy(source["directives"])
        image_ids = [item["directive_id"] for item in directives if item.get("asset_id") == "image_1"]
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
                    "binding_id": "b_product",
                    "asset_id": "image_1",
                    "target": "product manicure",
                    "role": "product",
                    "priority": "hard",
                    "source_directive_ids": image_ids,
                    "inherit": ["shape", "color", "pattern", "decoration", "material", "gloss"],
                    "exclude": ["product photo background"],
                },
                {
                    "binding_id": "b_identity",
                    "asset_id": "video_1",
                    "target": "performer identity",
                    "role": "identity",
                    "priority": "hard",
                    "source_directive_ids": ["d_identity_preserve"],
                    "inherit": ["face", "hair", "body", "hand shape"],
                    "exclude": ["product appearance"],
                },
                {
                    "binding_id": "b_motion",
                    "asset_id": "video_1",
                    "target": "performer motion and timing",
                    "role": "motion",
                    "priority": "hard",
                    "source_directive_ids": ["d_motion_preserve"],
                    "inherit": ["body actions", "hand actions", "timing"],
                    "exclude": ["identity", "outfit", "scene", "product appearance", "product geometry", "visible text", "logo"],
                },
                {
                    "binding_id": "b_scene",
                    "asset_id": "video_1",
                    "target": "background flexibility",
                    "role": "scene",
                    "priority": "soft",
                    "source_directive_ids": ["d_background_flexible"],
                    "inherit": ["environment", "set dressing"],
                    "exclude": ["identity", "product appearance"],
                },
                {
                    "binding_id": "b_style",
                    "asset_id": "video_1",
                    "target": "style flexibility",
                    "role": "style",
                    "priority": "soft",
                    "source_directive_ids": ["d_style_flexible"],
                    "inherit": ["lighting", "color grade", "commercial polish"],
                    "exclude": ["identity", "product geometry", "logo"],
                }
            ],
            "subjects": [
                {
                    "subject_id": "subject_1",
                    "name": "product manicure",
                    "kind": "product",
                    "primary": True,
                    "description": "the product manicure worn by the performer",
                    "source_asset_ids": ["image_1", "video_1"],
                    "binding_ids": ["b_product", "b_identity", "b_motion"],
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
                "primary_binding_ids": ["b_product"],
                "objective": "show the product manicure on the performer",
                "supporting_asset_ids": ["video_1"],
                "required_shot_ids": ["01"],
                "presentation_requirements": ["keep the manicure visible"],
            },
            "isolation_rules": [
                {
                    "binding_id": "b_product",
                    "allow": ["product appearance"],
                    "block": ["product photo background"],
                },
                {
                    "binding_id": "b_identity",
                    "allow": ["face", "hair", "body", "hand shape"],
                    "block": ["product appearance"],
                },
                {
                    "binding_id": "b_motion",
                    "allow": ["performer motion and timing"],
                    "block": ["identity", "outfit", "scene", "product appearance", "product geometry", "visible text", "logo"],
                },
                {
                    "binding_id": "b_scene",
                    "allow": ["environment", "set dressing"],
                    "block": ["identity", "product appearance"],
                },
                {
                    "binding_id": "b_style",
                    "allow": ["lighting", "color grade", "commercial polish"],
                    "block": ["identity", "product geometry", "logo"],
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
                    "primary_change": "the performer presents the manicure",
                    "event": "performer displays the product manicure",
                    "action": "display hands",
                    "camera": "medium close-up",
                    "lighting": "commercial lighting",
                    "transition": "end",
                    "observable_end_state": "the manicure is held still and fully visible",
                    "state_changes": [],
                    "subject_refs": ["subject_1"],
                    "asset_refs": ["image_1", "video_1"],
                    "binding_refs": ["b_product", "b_identity", "b_motion", "b_scene", "b_style"],
                }
            ],
            "audio_plan": {
                "voice": "",
                "music": "restrained non-vocal commercial music" if source["task"].get("generate_audio") else "",
                "sound_effects": "soft synchronized product handling Foley" if source["task"].get("generate_audio") else "",
                "ambient_sound": "quiet room tone" if source["task"].get("generate_audio") else "",
                "sync_rules": ["Foley follows the visible hand movement"] if source["task"].get("generate_audio") else [],
            },
            "production_policies": {
                module: {
                    "mode": "enhance" if module == "audio" and source["task"].get("generate_audio") else ("disabled" if module in {"effects", "text"} else "auto"),
                    "source": "default_completion",
                    "priority": "soft",
                    "allow_new_events": bool(module == "audio" and source["task"].get("generate_audio")),
                    "preserve_reference": False,
                    "constraints": {}, "events": [], "prohibit": [], "assumptions": [],
                }
                for module in ("camera", "editing", "motion", "performance", "composition", "lighting", "audio", "style", "effects", "text")
            },
            "entity_constraints": {
                module: {
                    "mode": "strict", "source": "derived_requirement", "priority": "hard",
                    "allow_new_events": False, "preserve_reference": True,
                    "constraints": {}, "events": [], "prohibit": [], "assumptions": [],
                }
                for module in ("identity", "product", "continuity")
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
