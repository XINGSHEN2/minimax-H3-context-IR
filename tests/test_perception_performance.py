import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from backend.perception import ATTRIBUTE_CROP_PROMPT, LocalQwen3VL32BProvider, PerceptionProviderConfig


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
    def test_local_provider_routes_images_and_videos_to_separate_services(self):
        provider = LocalQwen3VL32BProvider(PerceptionProviderConfig(options={
            "base_url": "http://legacy:9000",
            "image_base_url": "http://image:9012",
            "video_base_url": "http://video:9015",
        }))
        self.assertEqual(provider._service_base_url("image"), "http://image:9012")
        self.assertEqual(provider._service_base_url("video"), "http://video:9015")

    def test_local_provider_reads_split_service_environment(self):
        with patch.dict("os.environ", {
            "QWEN_IMAGE_UNDERSTAND_BASE_URL": "http://env-image:9012",
            "QWEN_VIDEO_UNDERSTAND_BASE_URL": "http://env-video:9015",
        }):
            provider = LocalQwen3VL32BProvider(PerceptionProviderConfig(options={}))
            self.assertEqual(provider._service_base_url("image"), "http://env-image:9012")
            self.assertEqual(provider._service_base_url("video"), "http://env-video:9015")

    def test_attribute_prompt_requires_one_valid_group(self):
        self.assertIn("must be exactly one of", ATTRIBUTE_CROP_PROMPT)
        self.assertIn('[["color","name","value"', ATTRIBUTE_CROP_PROMPT)

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
