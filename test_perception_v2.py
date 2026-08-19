#!/usr/bin/env python3
"""Run only the visual perception stage for a Context-IR request."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.perception import PERCEPTION_PROVIDERS, PerceptionProviderConfig


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = json.loads(args.request.read_text(encoding="utf-8"))
    config = PerceptionProviderConfig(
        provider="local-qwen3-vl-32b",
        model="Qwen3-VL-32B-Instruct",
        options={
            "base_url": "http://127.0.0.1:9012",
            "video_fps": 2.0,
            "video_max_frames": 256,
            "max_tokens": 3000,
            "temperature": 0.0,
            "top_p": 0.9,
            "timeout_seconds": 1800,
            "poll_interval_seconds": 1.0,
        },
    )
    result = PERCEPTION_PROVIDERS.create(config).analyze(source.get("assets", []))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": True, "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
