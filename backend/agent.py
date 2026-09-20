#!/usr/bin/env python3
"""v20 orchestration: intent, perception, then one Prompt compilation call."""
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
from backend.perception import PERCEPTION_PROVIDERS, PerceptionProviderConfig, sanitize_media_analysis_quality
from backend.intent_resolver import resolve_intent
ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
CORE_SKILLS = ("h3-prompt-writing", "h3-shot-planning")
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
    options.setdefault("base_url", os.environ.get("YIWU_VLM_BASE_URL", "https://ai.gitee.com/v1"))
    options.setdefault("image_base_url", os.environ.get("QWEN_IMAGE_UNDERSTAND_BASE_URL", "http://10.6.157.43:9012"))
    options.setdefault("video_base_url", os.environ.get("QWEN_VIDEO_UNDERSTAND_BASE_URL", "http://10.6.157.43:9012"))
    options.setdefault("asset_upload_base_url", os.environ.get("QWEN_ASSET_UPLOAD_BASE_URL", "http://10.0.96.114:30100"))
    options.setdefault("video_fps", float(os.environ.get("CONTEXT_IR_VIDEO_FPS", "2")))
    options.setdefault("video_max_frames", int(os.environ.get("CONTEXT_IR_VIDEO_MAX_FRAMES", "256")))
    options.setdefault("output_dir", os.environ.get("CONTEXT_IR_VLM_OUTPUT_DIR", str(ROOT / "outputs/qwen3.8-27b")))
    options.setdefault("api_key_env", os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY"))
    options.setdefault("video_frame_count", int(os.environ.get("CONTEXT_IR_VIDEO_FRAME_COUNT", "0")))
    options.setdefault("max_tokens", int(os.environ.get("CONTEXT_IR_VLM_MAX_TOKENS", "3000")))
    options.setdefault("cache_enabled", os.environ.get("CONTEXT_IR_VLM_CACHE_ENABLED", "1") not in {"0", "false", "False"})
    options.setdefault("cache_dir", os.environ.get("CONTEXT_IR_VLM_CACHE_DIR", ""))
    if not options["cache_dir"]:
        options.pop("cache_dir")
    options.setdefault("max_parallel_assets", int(os.environ.get("CONTEXT_IR_VLM_MAX_PARALLEL_ASSETS", "0")))
    options.setdefault("max_parallel_attribute_batches", int(os.environ.get("CONTEXT_IR_VLM_MAX_PARALLEL_ATTRIBUTE_BATCHES", "2")))
    options.setdefault("image_attribute_batch_size", int(os.environ.get("CONTEXT_IR_VLM_IMAGE_ATTRIBUTE_BATCH_SIZE", "3")))
    options.setdefault("single_pass_image_analysis", os.environ.get("CONTEXT_IR_VLM_SINGLE_PASS_IMAGE", "1") not in {"0", "false", "False"})
    options.setdefault("single_pass_video_analysis", os.environ.get("CONTEXT_IR_VLM_SINGLE_PASS_VIDEO", "1") not in {"0", "false", "False"})
    return PerceptionProviderConfig(
        provider=str(supplied.get("provider") or os.environ.get("CONTEXT_IR_VLM_PROVIDER", "local-qwen3-vl-32b")),
        model=str(supplied.get("model") or os.environ.get("YIWU_VLM_MODEL", "Qwen3.8-27B")),
        options=options,
    )

def ensure_perception(source: dict[str, Any], perception_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    if source.get("perception") is not None:
        enriched = dict(source)
        enriched["perception"] = sanitize_media_analysis_quality(source["perception"])
        return enriched
    config = perception_config(source)
    provider = PERCEPTION_PROVIDERS.create(config)
    enriched = dict(source)
    enriched["perception"] = provider.analyze(source.get("assets", []), perception_plan)
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
                for reference_name in ("shared-en.txt", f"{prompt_profile}-en.txt"):
                    reference = path.parent / "references" / reference_name
                    guide = reference.read_text(encoding="utf-8")
                    if reference_name == "ref2va-en.txt":
                        # The protocol rules are sufficient at runtime. The long
                        # worked example repeats appearance in shots and can
                        # override the project's single-definition convention.
                        guide = guide.split("## 7. Complete Example", 1)[0].rstrip()
                    system_parts.append(guide)
        return direct_runtime_from_config(reasoning).invoke_json(
            prompt,
            system_parts=system_parts,
            log_path=log_path,
        )
    raise ValueError("v20 supports only the direct Chat Completions runtime")

def _perception_input_origin(source: dict[str, Any], perception_from: Path | None) -> str:
    """Describe the selected input route, not the provider's internal cache hits."""
    if perception_from is not None:
        return "file"
    return "supplied_analysis" if source.get("perception") is not None else "perception_pipeline"

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
            "style_skill has been retired; h3-shot-planning is now always enabled "
            "and creative style stays governed by the user request and production policies"
        )
    run_started = time.perf_counter()
    stage_timings: dict[str, Any] = {
        "schema_version": "context_ir_stage_timings.v1",
        "perception_reused": perception_from is not None,
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
    if progress_callback:
        progress_callback("intent")
    stage_started = time.perf_counter()
    if intent_resolved:
        if not str(source.get("resolved_request", "")).strip():
            raise ValueError("intent_resolved=True requires source.resolved_request")
        resolution = {
            "source": source,
            "asset_mentions": copy.deepcopy(source.get("asset_mentions", [])),
            "perception_plan": {
                "assets": [
                    {
                        "asset_id": str(asset.get("asset_id", "")),
                        "role": str(asset.get("user_role", "reference")),
                        "user_claimed_category": "",
                        "analyze": [],
                        "do_not_infer": [],
                    }
                    for asset in source.get("assets", []) if isinstance(asset, dict)
                ]
            },
        }
    else:
        resolution = resolve_intent(
            source,
            lambda prompt: invoke_reasoning_json(prompt, reasoning, output_dir / "intent_resolver.log"),
        )
    finish_stage("intent_resolver", stage_started)
    source = resolution["source"]
    perception_plan = resolution["perception_plan"]
    (output_dir / "intent_resolution.json").write_text(
        json.dumps({
            "resolved_request": source["resolved_request"],
            "directives": source["directives"],
            "completion_policy": source["completion_policy"],
            "open_questions": source.get("open_questions", []),
            "asset_mentions": resolution.get("asset_mentions", source.get("asset_mentions", [])),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "perception_plan.json").write_text(json.dumps(perception_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "resolved_input.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if progress_callback:
        progress_callback("perception")
    stage_started = time.perf_counter()
    perception_origin = _perception_input_origin(source, perception_from)
    stage_timings["perception_input_origin"] = perception_origin
    stage_timings["perception_reused"] = perception_origin != "perception_pipeline"
    if perception_from is not None:
        perception = json.loads(perception_from.resolve().read_text(encoding="utf-8"))
        if not isinstance(perception, dict):
            raise ValueError("--perception-from must contain one media analysis JSON object")
        perception = sanitize_media_analysis_quality(perception)
        source = dict(source)
        source["perception"] = perception
    else:
        source = ensure_perception(source, perception_plan)
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
