#!/usr/bin/env python3
"""Read-only connectivity checks using the same v20 configuration as production."""
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.agent import perception_config, preflight_reasoning_provider, reasoning_provider_config


def main():
    if len(sys.argv) > 1:
        for line in Path(sys.argv[1]).read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    checks = {}
    reasoning = reasoning_provider_config()
    try:
        status = preflight_reasoning_provider(reasoning)
        checks["reasoning"] = {"reachable": status["passed"], "model": reasoning["model"],
                               "key_present": bool(os.environ.get(reasoning["api_key_env"]))}
    except Exception as exc:
        checks["reasoning"] = {"reachable": False, "error_type": type(exc).__name__}
    config = perception_config({})
    for name in ("image_base_url", "video_base_url", "asset_upload_base_url"):
        parsed = urlparse(str(config.options.get(name, "")))
        try:
            if not parsed.hostname: raise ValueError("No endpoint configured")
            with socket.create_connection((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)), timeout=3): pass
            checks[name] = {"reachable": True}
        except Exception as exc:
            checks[name] = {"reachable": False, "error_type": type(exc).__name__}
    print(json.dumps({"checks": checks, "scope": "TCP connectivity only; model authentication and inference not tested"}, ensure_ascii=False, indent=2))
    return 0 if all(v["reachable"] for v in checks.values()) else 1

if __name__ == "__main__":
    raise SystemExit(main())
