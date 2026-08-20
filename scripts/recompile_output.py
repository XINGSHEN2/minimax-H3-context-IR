#!/usr/bin/env python3
"""Recompile prompt artifacts from a stored Context-IR without calling VLM/LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.context_ir import audit_h3_prompt, build_h3_request, render_h3_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="Agent output directory containing context_ir.json")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    context_path = output_dir / "context_ir.json"
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    prompt = render_h3_prompt(payload)
    audit = audit_h3_prompt(payload, prompt)
    if not audit.passed:
        raise SystemExit(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2))

    prompt_path = output_dir / "h3_prompt.txt"
    audit_path = output_dir / "h3_prompt_audit.json"
    request_path = output_dir / "h3_request.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    audit_path.write_text(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    existing_request = {}
    if request_path.is_file():
        existing_request = json.loads(request_path.read_text(encoding="utf-8"))
    output_path = str(existing_request.get("output_path") or output_dir / "h3_outputs")
    request = build_h3_request(payload, str(prompt_path), output_path)
    for key in ("seed", "n", "num_inference_steps", "output_mode"):
        if key in existing_request:
            request[key] = existing_request[key]
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "passed": True,
        "context_ir": str(context_path),
        "h3_prompt": str(prompt_path),
        "h3_prompt_audit": str(audit_path),
        "h3_request": str(request_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
