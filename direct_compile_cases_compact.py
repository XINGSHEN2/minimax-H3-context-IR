#!/usr/bin/env python3
import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from backend.agent import audit_or_raise, build_prompt, ensure_perception, extract_json
from backend.context_ir import (
    audit_h3_prompt,
    build_h3_request,
    compile_context_ir,
    render_h3_prompt,
)


def call_glm(prompt: str) -> str:
    base_url = os.environ.get("GLM_RESPONSES_BASE_URL", "http://127.0.0.1:38041/v1")
    skill = Path("skills/h3-prompt-writing/SKILL.md").read_text(encoding="utf-8")
    payload = {
        "model": os.environ.get("GLM_MODEL", "GLM-5.2"),
        "instructions": "Apply this MiniMax H3 Skill. Return the final Context-IR JSON object immediately. Output no analysis, reasoning, preface, Markdown, or code fences. Call no tools. The first character must be { and the last character must be }.\n\n" + skill,
        "input": prompt,
        "max_output_tokens": 16384,
    }
    headers = {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        "Content-Type": "application/json",
    }
    if os.environ.get("GLM_HTTP_HOST"):
        headers["Host"] = os.environ["GLM_HTTP_HOST"]
    request = urllib.request.Request(
        base_url.rstrip("/") + "/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:3000]
        raise RuntimeError(f"GLM HTTP {exc.code}: {body}") from exc
    parts = []
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(str(content["text"]))
    if not parts:
        raise RuntimeError(f"GLM Responses returned no output text: {json.dumps(result, ensure_ascii=False)[:2000]}")
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    source = json.loads(args.request.read_text(encoding="utf-8"))
    source["perception_provider"] = {
        "provider": os.environ.get("CONTEXT_IR_VLM_PROVIDER", "local-qwen3-vl-32b"),
        "model": os.environ.get("YIWU_VLM_MODEL", "Qwen3-VL-32B-Instruct"),
        "options": {
            "base_url": os.environ.get("YIWU_VLM_BASE_URL", "http://127.0.0.1:9012"),
            "video_fps": float(os.environ.get("CONTEXT_IR_VIDEO_FPS", "2")),
            "video_max_frames": int(os.environ.get("CONTEXT_IR_VIDEO_MAX_FRAMES", "256")),
            "timeout_seconds": float(os.environ.get("CONTEXT_IR_VLM_TIMEOUT_SECONDS", "1800")),
            "output_dir": os.environ.get(
                "CONTEXT_IR_VLM_OUTPUT_DIR",
                "/home/mx/shenxing/minimax-H3-context-IR/outputs/qwen3-vl-32b",
            ),
        },
    }
    (output_dir / "input.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    media_path = output_dir / "media_analysis.json"
    if media_path.is_file():
        source["perception"] = json.loads(media_path.read_text(encoding="utf-8"))
    else:
        source = ensure_perception(source)
        media_path.write_text(json.dumps(source["perception"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    compact_rules = """

Output-size requirements:
- Return compact but complete JSON, preferably under 14000 characters.
- Use at most 5 timeline shots.
- Keep each description concise and avoid repeating the same attributes across fields.
- Do not omit any required schema field.
""".strip()
    raw = call_glm(build_prompt(source, None) + "\n\n" + compact_rules)
    (output_dir / "glm_raw_response.txt").write_text(raw, encoding="utf-8")
    ir = compile_context_ir(extract_json(raw))
    (output_dir / "context_ir.json").write_text(json.dumps(ir, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt = render_h3_prompt(ir)
    audit_or_raise(ir, prompt)
    prompt_path = output_dir / "h3_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    (output_dir / "h3_prompt_audit.json").write_text(
        json.dumps(audit_h3_prompt(ir, prompt).to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    request = build_h3_request(ir, str(prompt_path), str(output_dir / "h3_outputs"))
    (output_dir / "h3_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "output_dir": str(output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
