import copy
import unittest

from backend.intent_resolver import _scope_dimension, build_intent_prompt, resolve_intent, validate_intent_resolution


class IntentResolverTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "schema_version": "context_request.v1",
            "user_request": "Use image 1 as the product and follow video 1 camera structure.",
            "resolved_request": "",
            "directives": [],
            "completion_policy": {"technical": True, "conservative_semantic": True, "creative": False},
            "task": {"type": "ref2va", "duration_seconds": 15, "aspect_ratio": "9:16", "generate_audio": False},
            "assets": [
                {"asset_id": "image_1", "media_type": "image", "label": "product"},
                {"asset_id": "video_1", "media_type": "video", "label": "camera reference"},
            ],
        }

    def response(self):
        return {
            "resolved_request": "Present the claimed product while following only the reference camera structure.",
            "asset_mentions": [
                {"source_text": "image 1", "resolved_asset_ids": ["image_1"], "expected_media_type": "image", "cardinality": "singular", "resolution": "exact", "confidence": 1.0, "candidates": []},
                {"source_text": "video 1", "resolved_asset_ids": ["video_1"], "expected_media_type": "video", "cardinality": "singular", "resolution": "exact", "confidence": 1.0, "candidates": []},
            ],
            "directives": [
                {"directive_id": "d_product", "asset_id": "image_1", "target": "product", "operation": "preserve", "scope": ["appearance"], "priority": "hard", "provenance": "explicit_user"},
                {"directive_id": "d_camera", "asset_id": "video_1", "target": "camera structure", "operation": "transfer", "scope": ["camera structure"], "priority": "hard", "provenance": "explicit_user"},
            ],
            "completion_policy": copy.deepcopy(self.source["completion_policy"]),
            "perception_plan": {"assets": [
                {"asset_id": "image_1", "role": "authoritative_product_appearance", "user_claimed_category": "portable pump", "analyze": ["body geometry", "controls"], "do_not_infer": ["category from screen digits alone"]},
                {"asset_id": "video_1", "role": "camera_structure_reference", "user_claimed_category": "", "analyze": ["cuts", "camera movement"], "do_not_infer": ["performer identity"]},
            ]},
            "open_questions": [],
        }

    def test_dynamic_expression_is_a_motion_dimension(self):
        self.assertEqual(_scope_dimension("facial expression timing"), "motion")
        self.assertEqual(_scope_dimension("人物表情"), "motion")

    def test_empty_directives_are_resolved_and_plan_is_returned(self):
        result = resolve_intent(self.source, lambda _: self.response())
        self.assertEqual(len(result["source"]["directives"]), 2)
        self.assertEqual(result["perception_plan"]["assets"][0]["user_claimed_category"], "portable pump")

    def test_model_added_mixed_dimension_directive_is_atomized(self):
        response = self.response()
        response["directives"] = [{
            "directive_id": "d_mixed",
            "asset_id": "video_1",
            "target": "base video",
            "operation": "preserve",
            "scope": ["female identity", "staff clothing", "walking path", "store shelves"],
            "priority": "hard",
            "provenance": "explicit_user",
        }]
        result = resolve_intent(self.source, lambda _: response)
        directives = result["source"]["directives"]
        self.assertEqual(len(directives), 4)
        self.assertEqual(
            {tuple(item["scope"]) for item in directives},
            {("female identity",), ("staff clothing",), ("walking path",), ("store shelves",)},
        )
        self.assertEqual(len({item["directive_id"] for item in directives}), 4)

    def test_supplied_mixed_dimension_directive_remains_immutable(self):
        source = copy.deepcopy(self.source)
        supplied = {
            "directive_id": "d_supplied",
            "asset_id": "video_1",
            "target": "base video",
            "operation": "preserve",
            "scope": ["female identity", "staff clothing"],
            "priority": "hard",
            "provenance": "explicit_user",
        }
        source["directives"] = [supplied]
        response = self.response()
        response["directives"] = [copy.deepcopy(supplied)]
        result = resolve_intent(source, lambda _: response)
        self.assertEqual(result["source"]["directives"], [supplied])

    def test_existing_directives_cannot_be_changed(self):
        source = copy.deepcopy(self.source)
        source["directives"] = [self.response()["directives"][0]]
        bad = self.response()
        bad["directives"] = [self.response()["directives"][1]]
        with self.assertRaisesRegex(ValueError, "changed or reordered"):
            validate_intent_resolution(bad, source)

    def test_unknown_plan_asset_is_rejected(self):
        bad = self.response()
        bad["perception_plan"]["assets"][0]["asset_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "asset_id"):
            validate_intent_resolution(bad, self.source)

    def test_unknown_mention_asset_is_rejected(self):
        bad = self.response()
        bad["asset_mentions"][0]["resolved_asset_ids"] = ["image_99"]
        with self.assertRaisesRegex(ValueError, "unknown assets"):
            validate_intent_resolution(bad, self.source)

    def test_typed_mention_must_match_media_type(self):
        bad = self.response()
        bad["asset_mentions"][0]["resolved_asset_ids"] = ["video_1"]
        with self.assertRaisesRegex(ValueError, "media type mismatch"):
            validate_intent_resolution(bad, self.source)

    def test_resolved_singular_mention_must_be_unique(self):
        bad = self.response()
        bad["asset_mentions"][0]["resolved_asset_ids"] = ["image_1", "video_1"]
        bad["asset_mentions"][0]["expected_media_type"] = ""
        with self.assertRaisesRegex(ValueError, "exactly one asset"):
            validate_intent_resolution(bad, self.source)

    def test_ambiguous_mention_does_not_guess(self):
        source = copy.deepcopy(self.source)
        source["assets"].append({"asset_id": "image_2", "media_type": "image", "label": "alternate product"})
        response = self.response()
        response["asset_mentions"][0] = {
            "source_text": "the product image", "resolved_asset_ids": [],
            "expected_media_type": "image", "resolution": "ambiguous",
            "confidence": 0.4, "candidates": ["image_1", "image_2"],
        }
        result = validate_intent_resolution(response, source)
        self.assertEqual(result["asset_mentions"][0]["resolution"], "ambiguous")

    def test_duplicate_plan_asset_questions_are_merged(self):
        response = self.response()
        response["perception_plan"]["assets"].append({
            "asset_id": "video_1",
            "role": "motion_reference",
            "user_claimed_category": "",
            "analyze": ["hand motion", "cuts"],
            "do_not_infer": ["performer identity", "scene identity"],
        })
        result = validate_intent_resolution(response, self.source)
        video_plans = [
            item for item in result["perception_plan"]["assets"]
            if item["asset_id"] == "video_1"
        ]
        self.assertEqual(len(video_plans), 1)
        self.assertEqual(video_plans[0]["analyze"], ["cuts", "camera movement", "hand motion"])
        self.assertEqual(video_plans[0]["do_not_infer"], ["performer identity", "scene identity"])

    def test_claim_is_separate_and_guard_enters_qwen_prompt(self):
        prompt = build_intent_prompt(self.source)
        self.assertIn("user_claimed_category", prompt)
        from backend.perception import _analysis_prompt
        qwen_prompt = _analysis_prompt(self.source["assets"][0], [], plan=self.response()["perception_plan"]["assets"][0])
        self.assertIn("portable pump", qwen_prompt)
        self.assertIn("category from screen digits alone", qwen_prompt)
        self.assertIn("only as a search hypothesis", qwen_prompt)

    def test_audio_evidence_never_triggers_visual_provider_retry(self):
        response = self.response()
        response["directives"].append({
            "directive_id": "d_music", "asset_id": "video_1", "target": "music",
            "operation": "transfer", "scope": ["music tempo"], "priority": "hard",
            "provenance": "explicit_user",
        })
        response["perception_plan"]["assets"][1]["evidence_requirements"] = [{
            "claim": "music tempo", "priority": "required", "region_or_time": "",
        }]
        result = validate_intent_resolution(response, self.source)
        video_plan = next(
            item for item in result["perception_plan"]["assets"]
            if item["asset_id"] == "video_1"
        )
        requirement = video_plan["evidence_requirements"][0]
        self.assertEqual(requirement["priority"], "optional")
        self.assertEqual(requirement["max_retries"], 0)

    def test_resolver_failure_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            resolve_intent(self.source, lambda _: {})


if __name__ == "__main__":
    unittest.main()
