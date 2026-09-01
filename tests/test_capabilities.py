import copy
import json
import unittest
from pathlib import Path

from backend.capabilities import _prepare_asset_descriptions, h3_prompt_generate, video_generate
from backend.api import BUSINESS_API_ROUTES, OPTIONAL_GENERAL_API_ROUTES
from backend.perception import PerceptionProviderConfig
from backend.context_ir import audit_h3_prompt, compile_context_ir, render_h3_prompt
import tests.test_input_contract as input_contract_fixtures


ROOT = Path(__file__).resolve().parents[1]


class _FakeH3Client:
    def __init__(self):
        self.request = None

    def submit(self, request):
        self.request = copy.deepcopy(dict(request))
        return {"task_id": "task_1", "status": "queued"}

    def wait(self, task_id):
        return {"task_id": task_id, "status": "completed", "outputs": ["video.mp4"]}


class CapabilityContractTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(
            (ROOT / "examples" / "resolved_request.case6.json").read_text(encoding="utf-8")
        )
        self.ir = compile_context_ir(
            input_contract_fixtures.SourceContractTests._minimal_ir(self.source),
            self.source,
        )

    def test_context_ir_start_is_deterministic_and_needs_no_llm(self):
        result = h3_prompt_generate({"input_type": "context_ir", "context_ir": self.ir})
        self.assertEqual(result["schema_version"], "h3_prompt_generate.v1")
        self.assertEqual(result["sources"]["context_ir"], "caller_supplied")
        self.assertTrue(result["h3_prompt_audit"]["passed"])
        self.assertEqual(result["h3_request"]["num_inference_steps"], 20)

    def test_input_type_and_structure_must_match(self):
        with self.assertRaisesRegex(ValueError, "requires context_ir"):
            h3_prompt_generate({"input_type": "context_ir", "source": self.source})
        with self.assertRaisesRegex(ValueError, "requires media_analysis"):
            h3_prompt_generate({"input_type": "media_analysis", "source": self.source})

    def test_asset_descriptions_are_normalized_without_perception(self):
        source = copy.deepcopy(self.source)
        descriptions = [
            {
                "asset_id": asset["asset_id"],
                "description": f"Caller description for {asset['asset_id']}",
            }
            for asset in source["assets"]
        ]
        prepared, analysis = _prepare_asset_descriptions(
            source,
            descriptions,
            PerceptionProviderConfig(provider="test", model="none", options={}),
        )
        self.assertEqual(analysis["schema_version"], "media_analysis.v2")
        self.assertEqual(analysis["source"], "caller_supplied_asset_descriptions")
        self.assertEqual(prepared["perception"], analysis)
        self.assertEqual(
            {item["asset_id"] for item in analysis["assets"]},
            {item["asset_id"] for item in source["assets"]},
        )
        self.assertTrue(all(item["summary"] for item in analysis["assets"]))

    def test_asset_descriptions_can_build_source_assets(self):
        source = copy.deepcopy(self.source)
        source.pop("assets")
        prepared, analysis = _prepare_asset_descriptions(
            source,
            [{
                "asset_id": "image_1",
                "media_type": "image",
                "uri": "/shared/product.png",
                "description": "A transparent perfume bottle with an asymmetric black cap.",
            }],
            PerceptionProviderConfig(provider="test", model="none", options={}),
        )
        self.assertEqual(prepared["assets"][0]["uri"], "/shared/product.png")
        self.assertEqual(analysis["assets"][0]["asset_id"], "image_1")

    def test_asset_description_ids_must_match_source_assets(self):
        with self.assertRaisesRegex(ValueError, "do not match source.assets"):
            _prepare_asset_descriptions(
                self.source,
                [{"asset_id": "unknown", "description": "unknown asset"}],
                PerceptionProviderConfig(provider="test", model="none", options={}),
            )

    def test_video_generation_is_a_separate_capability(self):
        compiled = h3_prompt_generate({"input_type": "context_ir", "context_ir": self.ir})
        client = _FakeH3Client()
        result = video_generate(compiled, client=client, wait=True)
        self.assertEqual(result["result"]["status"], "completed")
        self.assertEqual(client.request["task"], self.ir["task"]["type"])

    def test_public_routes_separate_business_and_general_capabilities(self):
        self.assertEqual(BUSINESS_API_ROUTES["/api/h3/prompt"], "prompt")
        self.assertEqual(BUSINESS_API_ROUTES["/api/h3/videos"], "video")
        self.assertEqual(BUSINESS_API_ROUTES["/api/context-ir/generate"], "workflow")
        self.assertEqual(OPTIONAL_GENERAL_API_ROUTES["/api/understand/image"], "image")
        self.assertNotIn("normalize", BUSINESS_API_ROUTES.values())
        self.assertNotIn("normalize", OPTIONAL_GENERAL_API_ROUTES.values())

    def test_language_audit_allows_tagged_dialogue_but_rejects_cjk_prose(self):
        prompt = render_h3_prompt(self.ir)
        tagged = prompt.replace(
            "[Shot 1]",
            "[Shot 1] The presenter says <d>[Chinese] 给你们看新入的这双鞋</d>.",
            1,
        )
        self.assertNotIn(
            "PROMPT_REWRITE_LANGUAGE_VIOLATION",
            {item["code"] for item in audit_h3_prompt(self.ir, tagged).to_dict()["errors"]},
        )
        untagged = prompt.replace("[Shot 1]", "[Shot 1] 中文制作说明。", 1)
        self.assertIn(
            "PROMPT_REWRITE_LANGUAGE_VIOLATION",
            {item["code"] for item in audit_h3_prompt(self.ir, untagged).to_dict()["errors"]},
        )


if __name__ == "__main__":
    unittest.main()
