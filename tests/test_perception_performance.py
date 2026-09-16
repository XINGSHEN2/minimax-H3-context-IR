import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from backend.perception import ATTRIBUTE_CROP_PROMPT, COMPACT_VIDEO_SINGLE_PASS_PROMPT, LOCALIZATION_PROMPT, LocalQwen3VL32BProvider, PerceptionProviderConfig, _analysis_profile, _sanitize_analysis_quality, normalize_media_analysis


class FakeLocalProvider(LocalQwen3VL32BProvider):
    def __init__(self, config):
        super().__init__(config)
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def _analyze_visual(self, asset, plan=None):
        with self.lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.08)
        with self.lock:
            self.active -= 1
        return {
            "asset_id": asset["asset_id"],
            "summary": "visible object",
            "evidence": [], "regions": [], "entities": [],
            "relations": [], "events": [],
            "technical": {"media_type": "image"},
            "transcript": "", "uncertainties": [],
        }


class PerceptionPerformanceTests(unittest.TestCase):
    def test_local_provider_uses_chat_completions_shape(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "input.jpg"
            image.write_bytes(b"image")
            provider = LocalQwen3VL32BProvider(PerceptionProviderConfig(options={"cache_enabled": False}))
            captured = {}
            def fake_request(method, path, payload=None, timeout=30, base_url=None):
                captured.update(method=method, path=path, payload=payload, base_url=base_url)
                return {"choices": [{"message": {"content": '{"summary":"ok"}'}}], "x_task_id": "task_1"}
            provider._request_json = fake_request
            result = provider._run_task(image, "describe", Path(temporary) / "out", 512)
            self.assertEqual(captured["path"], "/v1/chat/completions")
            self.assertEqual(captured["payload"]["messages"][0]["content"][1]["type"], "image_url")
            self.assertTrue(captured["payload"]["messages"][0]["content"][1]["image_url"]["url"].startswith("file:"))
            self.assertEqual(result["_task_id"], "task_1")

    def test_local_provider_routes_images_and_videos_to_separate_services(self):
        provider = LocalQwen3VL32BProvider(PerceptionProviderConfig(options={
            "base_url": "http://legacy:9000",
            "image_base_url": "http://image:9012",
            "video_base_url": "http://video:9012",
        }))
        self.assertEqual(provider._service_base_url("image"), "http://image:9012")
        self.assertEqual(provider._service_base_url("video"), "http://video:9012")

    def test_local_provider_reads_split_service_environment(self):
        with patch.dict("os.environ", {
            "QWEN_IMAGE_UNDERSTAND_BASE_URL": "http://env-image:9012",
            "QWEN_VIDEO_UNDERSTAND_BASE_URL": "http://env-video:9012",
        }):
            provider = LocalQwen3VL32BProvider(PerceptionProviderConfig(options={}))
            self.assertEqual(provider._service_base_url("image"), "http://env-image:9012")
            self.assertEqual(provider._service_base_url("video"), "http://env-video:9012")

    def test_attribute_prompt_requires_one_valid_group(self):
        self.assertIn("must be exactly one of", ATTRIBUTE_CROP_PROMPT)
        self.assertIn('[["color","name","value"', ATTRIBUTE_CROP_PROMPT)

    def test_localization_preserves_whole_frame_layers_and_ocr_uncertainty(self):
        self.assertIn("global_analysis", LOCALIZATION_PROMPT)
        self.assertIn("framing_layers", LOCALIZATION_PROMPT)
        self.assertIn("binocular double-circle masks", LOCALIZATION_PROMPT)
        self.assertIn("never complete cropped", LOCALIZATION_PROMPT)

        config = PerceptionProviderConfig()
        normalized = normalize_media_analysis({"assets": [{
            "asset_id": "image_1", "summary": "frame",
            "global_analysis": {"framing_layers": [{"description": "fixed binocular mask"}]},
        }]}, [{"asset_id": "image_1", "media_type": "image"}], config)
        self.assertEqual(
            normalized["assets"][0]["global_analysis"]["framing_layers"][0]["description"],
            "fixed binocular mask",
        )

    def test_default_analysis_is_one_request_per_visual_asset(self):
        self.assertEqual(_analysis_profile({"media_type": "image"}, None), "single_pass")
        self.assertIn('"events"', COMPACT_VIDEO_SINGLE_PASS_PROMPT)
        self.assertIn('"entities"', COMPACT_VIDEO_SINGLE_PASS_PROMPT)
        self.assertIn("按源视频时间覆盖从开头到结尾", COMPACT_VIDEO_SINGLE_PASS_PROMPT)
        self.assertIn("不得原样输出占位内容", COMPACT_VIDEO_SINGLE_PASS_PROMPT)

    def test_placeholder_evidence_is_removed_before_reasoning(self):
        cleaned = _sanitize_analysis_quality({
            "asset_id": "video_1",
            "summary": "visible overview",
            "entities": [{
                "entity_id": "entity_1", "category": "generic visible category",
                "subcategory": "open vocabulary type", "summary": "visible facts",
                "attributes": {"color": [{"name": "name", "value": "value"}]},
            }],
            "events": [
                {"event_id": "event_1", "entity_ids": ["entity_1"], "action": "visible shot"},
                {"event_id": "event_2", "entity_ids": [], "action": "visible shot, cityscape, water, ferry"},
            ],
            "relations": [], "technical": {}, "uncertainties": [],
        })
        self.assertEqual(cleaned["entities"], [])
        self.assertEqual(cleaned["events"], [])
        self.assertEqual(cleaned["technical"]["analysis_status"], "invalid_placeholder")

    def test_unknown_relation_endpoint_is_a_warning_not_a_failure(self):
        cleaned = _sanitize_analysis_quality({
            "asset_id": "video_1", "summary": "woman speaks to camera",
            "entities": [{"entity_id": "person_1", "category": "person", "summary": "woman"}],
            "events": [],
            "relations": [{
                "relation_id": "relation_1", "subject_id": "person_1",
                "object_id": "missing_1", "type": "looks_at",
            }],
            "technical": {}, "uncertainties": [],
        })
        self.assertEqual(cleaned["relations"], [])
        self.assertEqual(cleaned["technical"]["analysis_status"], "degraded")
        self.assertTrue(cleaned["technical"]["quality_warnings"])

    def test_default_parallelism_submits_all_visual_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = []
            for index in range(4):
                image = root / f"image_{index}.jpg"
                image.write_bytes(f"image-{index}".encode())
                assets.append({"asset_id": f"image_{index}", "media_type": "image", "uri": str(image)})
            provider = FakeLocalProvider(PerceptionProviderConfig(options={
                "output_dir": str(root / "outputs"),
                "cache_enabled": False,
            }))

            result = provider.analyze(assets)

            self.assertEqual([item["asset_id"] for item in result["assets"]], [item["asset_id"] for item in assets])
            self.assertEqual(provider.calls, 4)
            self.assertEqual(provider.max_active, 4)

    def test_parallel_assets_preserve_order_and_use_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.jpg"
            second = root / "second.jpg"
            first.write_bytes(b"first-image")
            second.write_bytes(b"second-image")
            assets = [
                {"asset_id": "first", "media_type": "image", "uri": str(first)},
                {"asset_id": "second", "media_type": "image", "uri": str(second)},
            ]
            provider = FakeLocalProvider(PerceptionProviderConfig(options={
                "output_dir": str(root / "outputs"),
                "max_parallel_assets": 2,
                "cache_enabled": True,
            }))

            cold = provider.analyze(assets)
            self.assertEqual([item["asset_id"] for item in cold["assets"]], ["first", "second"])
            self.assertEqual(provider.calls, 2)
            self.assertEqual(provider.max_active, 2)
            self.assertTrue(all(not item["technical"]["cache_hit"] for item in cold["assets"]))

            warm = provider.analyze(assets)
            self.assertEqual(provider.calls, 2)
            self.assertTrue(all(item["technical"]["cache_hit"] for item in warm["assets"]))

    def test_plan_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "product.jpg"
            image.write_bytes(b"same-image")
            asset = {"asset_id": "product", "media_type": "image", "uri": str(image)}
            provider = FakeLocalProvider(PerceptionProviderConfig(options={
                "output_dir": str(root / "outputs"), "cache_enabled": True,
            }))
            provider.analyze([asset], {"assets": [{"asset_id": "product", "analyze": ["color"]}]})
            provider.analyze([asset], {"assets": [{"asset_id": "product", "analyze": ["material"]}]})
            self.assertEqual(provider.calls, 2)


if __name__ == "__main__":
    unittest.main()
