import copy
import json
import re
import unittest
from pathlib import Path

try:
    from remote_source.backend.context_ir import (
        ContextIRError,
        compile_context_ir,
        normalize_source_request,
        render_h3_prompt,
        audit_h3_prompt,
        audit_h3_prompt_contract,
        validate_context_ir,
        validate_source_request,
    )
except ModuleNotFoundError:
    from backend.context_ir import (
        ContextIRError,
        compile_context_ir,
        normalize_source_request,
        render_h3_prompt,
        audit_h3_prompt,
        audit_h3_prompt_contract,
        validate_context_ir,
        validate_source_request,
    )

try:
    from remote_source.backend.perception import _json_object, _canonical_entity_reference, _analysis_profile, _evidence_coverage, _required_supplements
except ModuleNotFoundError:
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
        self.assertIn("Scoped requirements:", prompt)
        self.assertIn("For <Video 1>.performer.identity:", prompt)
        self.assertNotIn("Production permissions:", prompt)
        self.assertNotIn("mode=disabled", prompt)
        self.assertNotRegex(prompt.split("summary:", 1)[0], r"(?m)^<Picture 1> is ")
        self.assertTrue(audit_h3_prompt(ir, prompt).passed)

    def test_renderer_projects_internal_asset_ids_to_official_labels(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["subjects"][0]["retention_description"] = "Preserve image_1 and follow video_1 only for motion."
        ir = compile_context_ir(model_ir, source)
        prompt = render_h3_prompt(ir)
        self.assertIn("Preserve <Picture 1> and follow <Video 1> only for motion.", prompt)
        self.assertNotRegex(prompt, r"\b(?:image|video|audio)_\d+\b")
        self.assertTrue(audit_h3_prompt(ir, prompt).passed)

    def test_audit_rejects_raw_asset_id_leak(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = compile_context_ir(self._minimal_ir(source), source)
        prompt = render_h3_prompt(ir) + "\nInternal source image_1.\n"
        report = audit_h3_prompt(ir, prompt)
        self.assertIn("RAW_ASSET_ID_LEAK", {item.code for item in report.issues})

    def test_contract_audit_rejects_nonofficial_heading_and_shot_label(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = compile_context_ir(self._minimal_ir(source), source)
        prompt = render_h3_prompt(ir)
        broken = prompt.replace("subject_definitions:", "Subject Definitions:", 1)
        broken = re.sub(r"(?m)^\[Shot 1\]", "[Shot 1, 0-15s]", broken, count=1)
        report = audit_h3_prompt_contract(ir, broken)
        codes = {item.code for item in report.issues}
        self.assertIn("PROMPT_SECTION_MISSING", codes)
        self.assertIn("PROMPT_SHOT_LABEL_INVALID", codes)

    def test_contract_audit_warns_for_camera_contradiction(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = compile_context_ir(self._minimal_ir(source), source)
        prompt = re.sub(
            r"(?m)^\[Shot 1\]",
            "[Shot 1] Static camera while the camera pans left.",
            render_h3_prompt(ir),
            count=1,
        )
        report = audit_h3_prompt_contract(ir, prompt)
        self.assertTrue(report.passed)
        warning_codes = {item.code for item in report.issues if item.severity == "warning"}
        self.assertIn("PROMPT_CAMERA_CONTRADICTION", warning_codes)

    def test_context_ir_warns_for_camera_contradiction_and_internal_cut_before_lock(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["timeline"][0]["camera"] = "Static camera, then slowly pushes in"
        model_ir["timeline"][0]["event"] = "Medium shot, quick cut to a close-up, then back to a two-shot"
        ir = compile_context_ir(model_ir, source)
        report = validate_context_ir(ir)
        self.assertTrue(report.passed)
        warning_codes = {item.code for item in report.issues if item.severity == "warning"}
        self.assertIn("SHOT_CAMERA_CONTRADICTION", warning_codes)
        self.assertIn("SHOT_INTERNAL_CUT", warning_codes)

    def test_motion_only_camera_prohibition_is_not_a_blocking_violation(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        source["user_request"] = "Transfer only actions, expressions, and performance rhythm from Video 1."
        source["resolved_request"] = source["user_request"]
        source["directives"] = [item for item in source["directives"] if item["directive_id"] in {"d_product_replace", "d_motion_preserve"}]
        model_ir = self._minimal_ir(source)
        for binding in model_ir["asset_bindings"]:
            if binding["asset_id"] == "video_1" and binding["role"] in {"identity", "scene"}:
                binding["priority"] = "soft"
                binding["source_directive_ids"] = []
        model_ir["timeline"][0]["camera"] = "Static locked medium-wide shot; no camera movement, zoom, or cut."
        model_ir["timeline"][0]["transition"] = "none"
        ir = compile_context_ir(model_ir, source)
        report = validate_context_ir(ir)
        self.assertTrue(report.passed)
        self.assertTrue(any(item.code == "MOTION_REFERENCE_CAMERA_SCOPE_VIOLATION" and item.severity == "warning" for item in report.issues))

    def test_motion_only_reference_cannot_author_camera_cuts_or_transitions(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        source["user_request"] = "Use the people in Picture 1 and strictly transfer only their actions, expressions, and performance rhythm from Video 1."
        source["resolved_request"] = source["user_request"]
        source["directives"] = [
            item for item in source["directives"]
            if item["directive_id"] in {"d_product_replace", "d_motion_preserve"}
        ]
        model_ir = self._minimal_ir(source)
        model_ir["semantic_plan"] = {
            "completion_authority": {"story_continuation": True}
        }
        for binding in model_ir["asset_bindings"]:
            if binding["asset_id"] == "video_1" and binding["role"] in {"identity", "scene"}:
                binding["priority"] = "soft"
                binding["source_directive_ids"] = []
        first = copy.deepcopy(model_ir["timeline"][0])
        first.update({
            "shot_id": "01", "start_seconds": 0.0, "end_seconds": 7.0,
            "camera": "Handheld medium shot following the action",
            "transition": "Hard cut",
        })
        second = copy.deepcopy(first)
        second.update({"shot_id": "02", "start_seconds": 7.0, "end_seconds": 15.0})
        model_ir["timeline"] = [first, second]
        model_ir["creative_focus"]["required_shot_ids"] = ["01", "02"]
        with self.assertRaises(ContextIRError) as caught:
            compile_context_ir(model_ir, source)
        message = str(caught.exception)
        self.assertIn("MOTION_REFERENCE_CUT_SCOPE_VIOLATION", message)
        self.assertIn("MOTION_REFERENCE_CAMERA_SCOPE_VIOLATION", message)
        self.assertIn("MOTION_REFERENCE_TRANSITION_SCOPE_VIOLATION", message)
        self.assertIn("MOTION_REFERENCE_STORY_CONTINUATION_VIOLATION", message)

    def test_performance_compiler_maps_observed_events_and_preserves_unresolved_tail(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        source["perception"] = {
            "schema_version": "media_analysis.v2",
            "assets": [{
                "asset_id": "video_1",
                "technical": {"media_type": "video", "analysis_status": "observed", "duration_seconds": 10.0},
                "entities": [], "relations": [],
                "events": [
                    {"event_id": "event_1", "time_range": [0.0, 2.0], "action": "a hand lifts a sponge", "transition_type": "continuous"},
                    {"event_id": "event_2", "time_range": [3.0, 8.0], "action": "the sponge is passed to another hand", "transition_type": "continuous"},
                ],
            }],
        }
        model_ir = self._minimal_ir(source)
        model_ir["performance_plan"] = {
            "source_asset_ids": ["video_1"],
            "transfer_scope": ["action", "expression", "performance_rhythm"],
            "excluded_scope": ["identity", "scene", "camera", "editing"],
            "beats": [
                {"source_asset_id": "video_1", "source_event_id": "event_1", "action": "a hand lifts a handful of foam", "action_source": "explicit_user", "subject_refs": ["subject_1"], "editorial_boundary": False},
                {"source_asset_id": "video_1", "source_event_id": "event_2", "action": "the foam is tossed to the other performer", "action_source": "explicit_user", "subject_refs": ["subject_1"], "editorial_boundary": False},
            ],
        }
        ir = compile_context_ir(model_ir, source)
        beats = ir["performance_plan"]["beats"]
        self.assertEqual([item["beat_id"] for item in beats], ["beat_01", "beat_02", "beat_03"])
        self.assertEqual(beats[0]["source_action"], "a hand lifts a sponge")
        self.assertEqual(beats[0]["action"], "a hand lifts a handful of foam")
        self.assertEqual(beats[1]["target_range"], [4.5, 12.0])
        self.assertEqual(beats[-1]["status"], "unresolved_tail")
        self.assertEqual(beats[-1]["target_range"], [12.0, 15.0])
        self.assertEqual(ir["timeline"][0]["beat_refs"], ["beat_01", "beat_02", "beat_03"])
        self.assertTrue(validate_context_ir(ir).passed)
        broken = copy.deepcopy(ir)
        broken["performance_plan"]["beats"][0]["target_range"] = [0.0, 7.0]
        self.assertIn(
            "PERFORMANCE_BEAT_TIME_MAPPING_MISMATCH",
            {item.code for item in validate_context_ir(broken).issues},
        )

    def test_action_keyframe_is_bound_to_a_performance_beat_and_rendered_as_pose(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        source["perception"] = {
            "schema_version": "media_analysis.v2",
            "assets": [{
                "asset_id": "video_1",
                "technical": {"media_type": "video", "analysis_status": "observed", "duration_seconds": 15.0},
                "entities": [], "relations": [],
                "events": [{"event_id": "event_1", "time_range": [2.0, 5.0], "action": "the performer presents both hands", "transition_type": "continuous"}],
            }],
        }
        model_ir = self._minimal_ir(source)
        model_ir["performance_plan"] = {
            "source_asset_ids": ["video_1"], "beats": [{
                "source_asset_id": "video_1", "source_event_id": "event_1",
                "action": "the performer presents both hands", "action_source": "reference_evidence",
                "subject_refs": ["subject_1"], "editorial_boundary": False,
            }],
        }
        model_ir["keyframe_roles"] = [{
            "asset_id": "image_1", "role": "action_keyframe",
            "subject_refs": ["subject_1"], "shot_refs": ["01"], "beat_refs": ["beat_01"],
            "controls": ["exact hand pose"], "excludes": ["motion", "camera", "editing"],
            "description": "Exact pose anchor for the hand presentation.",
            "source": "explicit_user", "evidence_refs": [], "confidence": 1.0,
        }]
        ir = compile_context_ir(model_ir, source)
        self.assertEqual(ir["performance_plan"]["beats"][0]["keyframe_refs"], ["keyframe_role_001"])
        prompt = render_h3_prompt(ir)
        self.assertIn("anchors its exact action pose at 00:02.000", prompt)
        self.assertIn("Performance sequence: At 00:02.000", prompt)
        self.assertNotIn("beat_01", prompt)
        self.assertTrue(audit_h3_prompt(ir, prompt).passed)

    def test_action_keyframe_without_a_known_beat_is_rejected(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["keyframe_roles"] = [{
            "asset_id": "image_1", "role": "action_keyframe",
            "subject_refs": ["subject_1"], "shot_refs": ["01"], "beat_refs": [],
            "controls": ["exact pose"], "excludes": ["motion", "camera", "editing"],
            "description": "Pose anchor.", "source": "explicit_user", "confidence": 1.0,
        }]
        with self.assertRaises(ContextIRError) as caught:
            compile_context_ir(model_ir, source)
        self.assertIn("ACTION_KEYFRAME_BEAT_REQUIRED", str(caught.exception))

    def test_context_ir_collapses_uniform_timing_claim_from_invalid_video_evidence(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        source["perception"] = {
            "schema_version": "media_analysis.v2",
            "assets": [{
                "asset_id": "video_1",
                "technical": {"media_type": "video", "analysis_status": "invalid_placeholder"},
                "entities": [], "events": [], "relations": [],
            }],
        }
        model_ir = self._minimal_ir(source)
        model_ir["intent"]["uncertainties"] = ["Equal-duration shots are assumed because timing is unavailable."]
        first = copy.deepcopy(model_ir["timeline"][0])
        first.update({"shot_id": "01", "start_seconds": 0.0, "end_seconds": 7.5})
        second = copy.deepcopy(first)
        second.update({"shot_id": "02", "start_seconds": 7.5, "end_seconds": 15.0})
        model_ir["timeline"] = [first, second]
        model_ir["creative_focus"]["required_shot_ids"] = ["01", "02"]
        ir = compile_context_ir(model_ir, source)
        self.assertEqual(len(ir["timeline"]), 1)
        self.assertEqual(ir["timeline"][0]["start_seconds"], 0.0)
        self.assertEqual(ir["timeline"][0]["end_seconds"], 15.0)
        self.assertIn("conditioned video", ir["timeline"][0]["camera"])
        self.assertEqual(ir["creative_focus"]["required_shot_ids"], ["01"])

    def test_transport_normalizer_repairs_heading_colon_and_timestamp_shot_order(self):
        from backend.context_ir import normalize_h3_prompt_transport

        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = compile_context_ir(self._minimal_ir(source), source)
        broken = render_h3_prompt(ir).replace("subject_definitions:", "Subject Definitions", 1)
        broken = re.sub(r"(?m)^\[Shot 1\]", "At 00:00.000, [Shot 1]", broken, count=1)
        repaired = normalize_h3_prompt_transport(ir, broken)
        self.assertIn("subject_definitions:\n", repaired)
        self.assertIn("[Shot 1]", repaired)
        self.assertNotIn("[Shot 1] At 00:00.000", repaired)
        self.assertTrue(audit_h3_prompt_contract(ir, repaired).passed)

        embedded = re.sub(
            r"(?m)^\[Shot 1\]",
            "[Shot 1] <Subject 1> is visible. At 00:00.000,",
            render_h3_prompt(ir),
            count=1,
        )
        embedded_repaired = normalize_h3_prompt_transport(ir, embedded)
        self.assertNotIn("00:00.000", embedded_repaired)
        self.assertTrue(audit_h3_prompt_contract(ir, embedded_repaired).passed)

    def test_transport_normalizer_restores_official_video_editing_summary_opening(self):
        from backend.context_ir import normalize_h3_prompt_transport

        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["reference_relationships"][1]["relationship"] = "source_video_edit"
        model_ir["protocol"]["summary_task_types"] = ["reference generation", "video editing"]
        ir = compile_context_ir(model_ir, source)
        prompt = render_h3_prompt(ir).replace(
            "[reference generation + video editing] The target video is an edited version of <Video 1>.",
            "[video editing] This is a video editing task:",
            1,
        )
        repaired = normalize_h3_prompt_transport(ir, prompt)
        self.assertIn(
            "summary:\n[reference generation + video editing] The target video is an edited version of <Video 1>.",
            repaired,
        )
        self.assertTrue(audit_h3_prompt_contract(ir, repaired).passed)

    def test_contract_audit_requires_each_subject_appearance_source_in_definition(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = compile_context_ir(self._minimal_ir(source), source)
        prompt = render_h3_prompt(ir)
        definitions, remainder = prompt.split("summary:", 1)
        definitions = definitions.replace("<Picture 1>", "the supplied product reference", 1)
        report = audit_h3_prompt_contract(ir, definitions + "summary:" + remainder)
        self.assertIn("SUBJECT_APPEARANCE_SOURCE_MISSING", {item.code for item in report.issues})

    def test_contract_audit_rejects_multiple_exclusive_whole_appearance_sources(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        second = copy.deepcopy(source["assets"][0])
        second.update({"asset_id": "image_2", "label": "图片2"})
        source["assets"].append(second)
        model_ir = self._minimal_ir(source)
        model_ir["asset_bindings"].append({
            "binding_id": "b_product_2",
            "asset_id": "image_2",
            "target": "product manicure detail",
            "role": "product",
            "priority": "hard",
            "source_directive_ids": [],
            "inherit": ["decoration"],
            "exclude": ["background"],
        })
        model_ir["reference_relationships"].append({
            "asset_id": "image_2",
            "relationship": "reference_generation",
            "subject_refs": ["subject_1"],
            "definition": "secondary product detail reference",
            "retention_mode": "attribute_transfer",
            "retention_description": "decoration transfers to the product",
        })
        model_ir["subjects"][0]["source_asset_ids"] = ["image_1", "image_2"]
        ir = compile_context_ir(model_ir, source)
        prompt = render_h3_prompt(ir)
        prompt = prompt.replace(
            "<Subject 1> is ",
            "<Subject 1> is its appearance comes exclusively from <Picture 1>; its appearance comes exclusively from <Picture 2>; ",
            1,
        )
        report = audit_h3_prompt_contract(ir, prompt)
        self.assertIn("SUBJECT_APPEARANCE_AUTHORITY_CONTRADICTION", {item.code for item in report.issues})

    def test_coequal_audit_does_not_misread_shared_focus_grammar(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        ir = compile_context_ir(self._minimal_ir(source), source)
        ir["semantic_plan"] = {
            "subject_priority": {"mode": "co_equal", "subject_ids": ["subject_1", "subject_2"]}
        }
        prompt = render_h3_prompt(ir)
        shared = "[reference generation] The interaction between <Subject 1> and <Subject 2> is the primary creative focus."
        prompt = re.sub(r"(?ms)(^summary:\s*).*?(?=^retention_analysis:)", rf"\g<1>{shared}\n\n", prompt)
        report = audit_h3_prompt_contract(ir, prompt)
        self.assertNotIn("PROMPT_COEQUAL_PRIORITY_CONTRADICTION", {item.code for item in report.issues})

    def test_renderer_keeps_policy_metadata_internal_and_deduplicates_prohibitions(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["constraints"]["prohibit"] = ["repeated flashing", "repeated flashing"]
        model_ir["production_policies"]["effects"]["prohibit"] = ["repeated flashing"]
        model_ir["production_policies"]["effects"]["events"] = [{
            "event_id": "event_flash",
            "type": "transition",
            "description": "one brief transition fluctuation",
            "source": "explicit_user",
            "priority": "hard",
            "shot_refs": ["01"],
        }]
        ir = compile_context_ir(model_ir, source)
        prompt = render_h3_prompt(ir)
        self.assertNotIn("repeated flashing", prompt)
        self.assertNotIn("event_flash", prompt)
        self.assertNotIn("one brief transition fluctuation", prompt)
        self.assertNotIn("priority=hard", prompt)
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

    def test_renderer_guards_structural_binding_omitted_from_subject_sources(self):
        source = json.loads((ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8"))
        model_ir = self._minimal_ir(source)
        model_ir["subjects"][0]["binding_ids"] = ["b_product", "b_motion"]
        model_ir["subjects"][0]["source_asset_ids"] = ["image_1"]
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
