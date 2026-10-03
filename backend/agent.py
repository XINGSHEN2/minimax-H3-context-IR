#!/usr/bin/env python3
"""Qwen material analysis followed by one prompt compilation call."""
from __future__ import annotations
import argparse
import copy
import json
import os
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from backend.contracts import normalize_source_request, validate_source_request
from backend.perception import PerceptionProviderConfig, sanitize_media_analysis_quality
from backend.intent_resolver import resolve_intent
ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
CORE_SKILLS = ("h3-outline-planning", "h3-shot-planning", "h3-sound-planning", "h3-prompt-writing")
OFFICIAL_SKILLS = set(CORE_SKILLS)

def prompt_profile_for_source(source: Mapping[str, Any]) -> str:
    """Resolve the protocol guide set from an explicit override or task type."""
    task = source.get("task") if isinstance(source, Mapping) else None
    task = task if isinstance(task, Mapping) else {}
    profile = str(task.get("prompt_profile", "auto")).strip().lower()
    if profile == "auto":
        return "ref2va" if task.get("type") == "ref2va" else "base"
    if profile not in {"ref2va", "base"}:
        raise ValueError("prompt_profile must be auto, ref2va, or base")
    return profile

def reasoning_provider_config() -> dict[str, str]:
    selected = os.environ.get("CONTEXT_IR_LLM_PROVIDER", "deepseek").strip().lower()
    if selected in {"deepseek_litellm", "deepseek-litellm", "litellm"}:
        return {
            "selection": "deepseek_litellm",
            "name": "DeepSeek via LiteLLM",
            "provider_id": os.environ.get("DEEPSEEK_LITELLM_PROVIDER_ID", "deepseek_litellm"),
            "model": os.environ.get("DEEPSEEK_LITELLM_MODEL", "deepseek-v4-flash"),
            "base_url": os.environ.get(
                "DEEPSEEK_LITELLM_RESPONSES_BASE_URL",
                "http://litellm-poc.pgw.metax-tech.com/v1",
            ),
            "api_key_env": "LITELLM_API_KEY",
            "http_host_env": "DEEPSEEK_LITELLM_HTTP_HOST",
        }
    if selected == "glm":
        return {
            "selection": "glm",
            "name": "GLM",
            "provider_id": os.environ.get("GLM_PROVIDER_ID", "glm"),
            "model": os.environ.get("GLM_MODEL", "GLM-5.2"),
            "base_url": os.environ.get("GLM_RESPONSES_BASE_URL", "http://127.0.0.1:38041/v1"),
            "api_key_env": "OPENAI_API_KEY",
            "http_host_env": "GLM_HTTP_HOST",
        }
    if selected == "deepseek":
        return {
            "selection": "deepseek",
            "name": "DeepSeek",
            "provider_id": os.environ.get("DEEPSEEK_PROVIDER_ID", "deepseek"),
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
            "base_url": os.environ.get("DEEPSEEK_RESPONSES_BASE_URL", "https://api.deepseek.com"),
            "api_key_env": "DEEPSEEK_API_KEY",
            "http_host_env": "",
        }
    raise ValueError(
        "CONTEXT_IR_LLM_PROVIDER must be 'deepseek_litellm', 'deepseek', or 'glm'"
    )

def preflight_reasoning_provider(reasoning: dict[str, str], timeout: float = 3.0) -> dict[str, Any]:
    base_url = (
        os.environ.get(f"{reasoning['selection'].upper()}_CHAT_BASE_URL")
        or os.environ.get("CONTEXT_IR_LLM_CHAT_BASE_URL")
        or reasoning["base_url"]
    )
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"invalid {reasoning['name']} LLM base URL: {base_url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            pass
    except OSError as exc:
        raise RuntimeError(
            f"{reasoning['name']} LLM API is unreachable at {parsed.hostname}:{port}: {exc}"
        ) from exc
    return {"passed": True, "selection": reasoning["selection"], "provider_id": reasoning["provider_id"], "model": reasoning["model"], "base_url": base_url, "host": parsed.hostname, "port": port}

def perception_config(source: dict[str, Any]) -> PerceptionProviderConfig:
    supplied = source.get("perception_provider") or {}
    options = dict(supplied.get("options") or {})
    options.setdefault("image_base_url", os.getenv("QWEN_IMAGE_UNDERSTAND_BASE_URL", "http://10.42.1.1:9012"))
    options.setdefault("omni_base_url", os.getenv("QWEN_OMNI_BASE_URL", "http://10.42.1.1:9013"))
    options.setdefault("asset_upload_base_url", os.getenv("QWEN_ASSET_UPLOAD_BASE_URL", "http://10.42.1.1:30100"))
    options.setdefault("output_dir", str(ROOT / "outputs/perception"))
    return PerceptionProviderConfig(options=options)


def ensure_perception(source: dict[str, Any], perception_plan: dict[str, Any] | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    from backend.perception import MultimodalPerception, validate_analysis
    enriched = dict(source)
    if source.get("perception") is not None:
        data = source["perception"]
        if data.get("schema_version") == "media_analysis.v3":
            metadata = {a["asset_id"]: a.get("technical", {}) for a in data.get("assets", [])}
            enriched["perception"] = validate_analysis(data, source.get("assets", []), metadata)
        else:
            enriched["perception"] = sanitize_media_analysis_quality(data)
        return enriched
    supplied = source.get("perception_provider") or {}
    options = dict(supplied.get("options") or {})
    directory = output_dir or ROOT / "outputs" / ("perception-v3-" + __import__("uuid").uuid4().hex)
    enriched["perception"] = MultimodalPerception(options).analyze(source, directory)
    return enriched


def invoke_reasoning_json(
    prompt: str,
    reasoning: dict[str, str],
    log_path: Path,
    skill_names: list[str] | None = None,
    prompt_profile: str = "ref2va",
) -> dict[str, Any]:
    """Run one strict JSON turn through the configured replaceable runtime."""
    runtime = os.environ.get("CONTEXT_IR_LLM_RUNTIME", "direct").strip().lower()
    if runtime == "direct":
        from backend.llm_runtime import direct_runtime_from_config

        system_parts = [(ROOT / "AGENTS.md").read_text(encoding="utf-8")]
        for name in skill_names or []:
            path = SKILLS_DIR / name / "SKILL.md"
            if not path.is_file():
                raise FileNotFoundError(f"missing official Skill: {path.parent}")
            system_parts.append(path.read_text(encoding="utf-8"))
            if name == "h3-prompt-writing":
                # Direct Chat has no filesystem tool, so inject the shared
                # protocol plus exactly one mode-specific guide.
                if prompt_profile not in {"ref2va", "base"}:
                    raise ValueError("prompt_profile must be ref2va or base")
                profile_reference = "ref2va-zh-en.txt" if prompt_profile == "ref2va" else "base-zh-en.txt"
                for reference_name in ("shared-zh-en.txt", profile_reference):
                    reference = path.parent / "references" / reference_name
                    guide = reference.read_text(encoding="utf-8")
                    system_parts.append(guide)
        return direct_runtime_from_config(reasoning).invoke_json(
            prompt,
            system_parts=system_parts,
            log_path=log_path,
        )
    raise ValueError("v20 supports only the direct Chat Completions runtime")

def run_agent(
    source: dict[str, Any],
    output_dir: Path,
    style_skill: str | None,
    perception_from: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
    intent_resolved: bool = False,
) -> int:
    if style_skill:
        raise ValueError(
            "style_skill has been retired; prompt behavior is governed by the user request, "
            "production instructions, and the active h3-prompt-writing skill"
        )
    run_started = time.perf_counter()
    stage_timings: dict[str, Any] = {
        "schema_version": "context_ir_stage_timings.v1",
        "stages_seconds": {},
    }

    def finish_stage(name: str, started: float) -> None:
        stage_timings["stages_seconds"][name] = round(time.perf_counter() - started, 3)

    source = normalize_source_request(source)
    source_report = validate_source_request(source)
    if not source_report.passed:
        raise ValueError(json.dumps(source_report.to_dict(), ensure_ascii=False, indent=2))
    reasoning = reasoning_provider_config()
    api_key_env = reasoning["api_key_env"]
    if not os.environ.get(api_key_env):
        raise RuntimeError(f"Missing {reasoning['name']} API key environment variable: {api_key_env}")
    preflight_reasoning_provider(reasoning)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "input.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Keep explicit input directives. The writer reads the original request directly.
    # No intent-resolution LLM is called before material analysis.
    (output_dir / "resolved_input.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if progress_callback:
        progress_callback("perception")
    stage_started = time.perf_counter()
    if perception_from is not None:
        perception = json.loads(perception_from.resolve().read_text(encoding="utf-8"))
        if not isinstance(perception, dict):
            raise ValueError("--perception-from must contain one media analysis JSON object")
        source = dict(source)
        source["perception"] = perception
        source = ensure_perception(source)
    else:
        source = ensure_perception(source, output_dir=output_dir / "perception")
    finish_stage("perception", stage_started)
    (output_dir / "media_analysis.json").write_text(
        json.dumps(source.get("perception"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if progress_callback:
        progress_callback("compile")

    # v20 keeps intent/perception reusable and compiles the Prompt once.
    from backend.compiler import compile_prompt
    return compile_prompt(source, output_dir, reasoning, stage_timings,
                              run_started, progress_callback)

def main() -> int:
    parser = argparse.ArgumentParser(description="H3 v20 Prompt compiler")
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--style-skill", help=argparse.SUPPRESS)
    parser.add_argument(
        "--perception-from",
        type=Path,
        help="reuse an existing media_analysis.json instead of invoking the perception provider",
    )
    parser.add_argument("--validate-only", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.preflight_only:
            reasoning = reasoning_provider_config()
            result = preflight_reasoning_provider(reasoning)
            result.update({
                "api_key_env": reasoning["api_key_env"],
                "api_key_present": bool(os.environ.get(reasoning["api_key_env"])),
                "http_host": os.environ.get(reasoning.get("http_host_env", ""), "") if reasoning.get("http_host_env") else "",
                "official_skills": len(OFFICIAL_SKILLS),
                "vlm_provider": os.environ.get("CONTEXT_IR_VLM_PROVIDER", "local-qwen3-vl-32b"),
                "vlm_model": os.environ.get("YIWU_VLM_MODEL", "Qwen3.8-27B"),
                "vlm_api_key_env": os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY"),
                "vlm_api_key_present": bool(os.environ.get(os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY"))),
            })
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.validate_only:
            payload = json.loads(args.validate_only.read_text(encoding="utf-8"))
            report = validate_source_request(normalize_source_request(payload))
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
            return 0 if report.passed else 1
        if args.input is None:
            parser.error("input JSON is required unless --validate-only is used")
        source = json.loads(args.input.resolve().read_text(encoding="utf-8"))
        if not isinstance(source, dict):
            raise ValueError("input root must be an object")
        output_dir = (args.output_dir or ROOT / "outputs" / datetime.now().strftime("%Y%m%d_%H%M%S")).resolve()
        return run_agent(source, output_dir, args.style_skill, args.perception_from)
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
