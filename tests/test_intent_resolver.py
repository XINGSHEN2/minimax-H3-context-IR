import copy
import unittest

from backend.intent_resolver import build_intent_prompt, resolve_intent, validate_intent_resolution


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

    def test_empty_directives_are_resolved_and_plan_is_returned(self):
        result = resolve_intent(self.source, lambda _: self.response())
        self.assertEqual(len(result["source"]["directives"]), 2)
        self.assertEqual(result["perception_plan"]["assets"][0]["user_claimed_category"], "portable pump")

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

    def test_claim_is_separate_and_guard_enters_qwen_prompt(self):
        prompt = build_intent_prompt(self.source)
        self.assertIn("user_claimed_category", prompt)
        from backend.perception import _analysis_prompt
        qwen_prompt = _analysis_prompt(self.source["assets"][0], [], plan=self.response()["perception_plan"]["assets"][0])
        self.assertIn("portable pump", qwen_prompt)
        self.assertIn("category from screen digits alone", qwen_prompt)
        self.assertIn("only as a search hypothesis", qwen_prompt)

    def test_resolver_failure_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            resolve_intent(self.source, lambda _: {})


if __name__ == "__main__":
    unittest.main()
