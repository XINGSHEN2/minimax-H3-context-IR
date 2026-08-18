import json

from backend.perception import PERCEPTION_PROVIDERS, PerceptionProviderConfig

config = PerceptionProviderConfig(
    provider="local-qwen3-vl-32b",
    model="Qwen3-VL-32B-Instruct",
    options={
        "base_url": "http://127.0.0.1:9012",
        "output_dir": "/home/mx/shenxing/minimax-H3-context-IR/outputs/qwen3-vl-32b-smoke",
        "video_fps": 0.5,
        "video_max_frames": 8,
        "max_tokens": 2048,
        "timeout_seconds": 1800,
        "poll_interval_seconds": 1,
    },
)
assets = [
    {
        "asset_id": "image_1",
        "media_type": "image",
        "uri": "/home/mx/shenxing/minimax-H3-context-IR/assets/case_001/images/merchandise.png",
    },
    {
        "asset_id": "video_1",
        "media_type": "video",
        "uri": "/home/mx/shenxing/minimax-H3-context-IR/assets/case_001/videos/reference_video.mp4",
    },
]
result = PERCEPTION_PROVIDERS.create(config).analyze(assets)
print(json.dumps({
    "schema_version": result["schema_version"],
    "provider": result["provider"],
    "assets": [
        {
            "asset_id": item["asset_id"],
            "observation_count": len(item["observations"]),
            "entity_count": len(item["entities"]),
            "event_count": len(item["events"]),
            "media_type": item["technical"].get("media_type"),
        }
        for item in result["assets"]
    ],
}, ensure_ascii=False, indent=2))
