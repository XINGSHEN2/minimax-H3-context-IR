import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.capabilities import _prepare_asset_descriptions, h3_prompt_generate, video_generate
from backend.api import BUSINESS_API_ROUTES, OPTIONAL_GENERAL_API_ROUTES
from backend.perception import PerceptionProviderConfig


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



    def test_input_type_and_structure_must_match(self):
        with self.assertRaisesRegex(ValueError, "input_type must be"):
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


    def test_public_routes_separate_business_and_general_capabilities(self):
        self.assertEqual(BUSINESS_API_ROUTES["/api/h3/prompt"], "prompt")
        self.assertEqual(BUSINESS_API_ROUTES["/api/h3/videos"], "video")
        self.assertEqual(BUSINESS_API_ROUTES["/api/context-ir/generate"], "workflow")
        self.assertEqual(OPTIONAL_GENERAL_API_ROUTES["/api/understand/image"], "image")
        self.assertNotIn("normalize", BUSINESS_API_ROUTES.values())
        self.assertNotIn("normalize", OPTIONAL_GENERAL_API_ROUTES.values())



if __name__ == "__main__":
    unittest.main()


def test_single_asset_endpoints_use_current_multimodal_pipeline():
    import tempfile
    from unittest.mock import patch
    from backend.capabilities import image_understand, video_understand, audio_understand
    with tempfile.TemporaryDirectory() as directory:
        config = PerceptionProviderConfig(options={"output_dir": directory, "omni_base_url": "http://omni"})
        with patch("backend.capabilities.MultimodalPerception") as provider:
            provider.return_value.analyze.return_value = {"schema_version": "media_analysis.v3"}
            paths = []
            for kind, call in [("image", image_understand), ("video", video_understand), ("audio", audio_understand)]:
                asset = {"asset_id": kind + "_1", "media_type": kind, "uri": "http://asset"}
                result = call(asset, config, {"focus": "保留动作和对白"})
                assert result["schema_version"] == "media_analysis.v3"
                source, output = provider.return_value.analyze.call_args.args
                assert source["assets"] == [asset]
                assert "保留动作和对白" in source["user_request"]
                assert str(output).startswith(directory)
                paths.append(output)
            assert len(set(paths)) == 3
            assert provider.call_args.args[0]["omni_base_url"] == "http://omni"
