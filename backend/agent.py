#!/usr/bin/env python3
"""Codex SDK Context-IR agent runner with switchable reasoning providers."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from backend.context_ir import (
    audit_h3_prompt,
    build_h3_request,
    compile_context_ir,
    normalize_source_request,
    render_h3_prompt,
    validate_source_request,
    validate_context_ir,
)
from backend.perception import PERCEPTION_PROVIDERS, PerceptionProviderConfig
from backend.intent_resolver import resolve_intent


ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
OFFICIAL_SKILLS = {
    "h3-prompt-writing",
    "brand-promo-video-generator",
    "minimalist-product-ad-generator",
    "3d-animation-short-generator",
    "co-op-game-intro-generator",
    "handdrawn-live-video-generator",
    "music-video-subtitle-generator",
    "paper-collage-explainer-generator",
    "papercraft-stop-motion-explainer",
}


def reasoning_provider_config() -> dict[str, str]:
    selected = os.environ.get("CONTEXT_IR_LLM_PROVIDER", "glm").strip().lower()
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
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            "base_url": os.environ.get("DEEPSEEK_RESPONSES_BASE_URL", "https://api.deepseek.com"),
            "api_key_env": "DEEPSEEK_API_KEY",
            "http_host_env": "",
        }
    raise ValueError("CONTEXT_IR_LLM_PROVIDER must be 'glm' or 'deepseek'")


def build_config(reasoning: dict[str, str]) -> dict[str, Any]:
    provider: dict[str, Any] = {
        "name": reasoning["name"],
        "base_url": reasoning["base_url"],
        "env_key": reasoning["api_key_env"],
        "wire_api": "responses",
        "requires_openai_auth": False,
        "supports_websockets": False,
        "request_max_retries": 1,
        "stream_max_retries": 1,
        "stream_idle_timeout_ms": 180_000,
    }
    http_host_env = reasoning.get("http_host_env", "")
    if http_host_env and os.environ.get(http_host_env):
        provider["env_http_headers"] = {"Host": http_host_env}
    return {
        "model_reasoning_effort": "low",
        "model_context_window": 120_000,
        "model_auto_compact_token_limit": 90_000,
        "tool_output_token_limit": 12_000,
        "include_apps_instructions": False,
        "features": {"apps": False},
        "model_providers": {reasoning["provider_id"]: provider},
    }


def preflight_reasoning_provider(reasoning: dict[str, str], timeout: float = 3.0) -> dict[str, Any]:
    base_url = reasoning["base_url"]
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"invalid {reasoning['name']} Responses base URL: {base_url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            pass
    except OSError as exc:
        raise RuntimeError(
            f"{reasoning['name']} Responses API is unreachable at {parsed.hostname}:{port}: {exc}"
        ) from exc
    return {"passed": True, "selection": reasoning["selection"], "provider_id": reasoning["provider_id"], "model": reasoning["model"], "base_url": base_url, "host": parsed.hostname, "port": port}


def perception_config(source: dict[str, Any]) -> PerceptionProviderConfig:
    supplied = source.get("perception_provider") or {}
    options = dict(supplied.get("options") or {})
    options.setdefault("base_url", os.environ.get("YIWU_VLM_BASE_URL", "https://ai.gitee.com/v1"))
    options.setdefault("api_key_env", os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY"))
    options.setdefault("video_frame_count", int(os.environ.get("CONTEXT_IR_VIDEO_FRAME_COUNT", "0")))
    options.setdefault("max_tokens", int(os.environ.get("CONTEXT_IR_VLM_MAX_TOKENS", "3000")))
    return PerceptionProviderConfig(
        provider=str(supplied.get("provider") or os.environ.get("CONTEXT_IR_VLM_PROVIDER", "gitee-qwen3-vl")),
        model=str(supplied.get("model") or os.environ.get("YIWU_VLM_MODEL", "Qwen3-VL-30B-A3B-Instruct")),
        options=options,
    )


def ensure_perception(source: dict[str, Any], perception_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    if source.get("perception") is not None:
        return source
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
) -> dict[str, Any]:
    """Run one strict JSON turn through the currently selected Codex provider."""
    from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox, SkillInput, TextInput

    api_key_env = reasoning["api_key_env"]
    agent_env = {api_key_env: os.environ[api_key_env]}
    http_host_env = reasoning.get("http_host_env", "")
    if http_host_env and os.environ.get(http_host_env):
        agent_env[http_host_env] = os.environ[http_host_env]
    inputs: list[Any] = []
    for name in skill_names or []:
        path = SKILLS_DIR / name
        if not (path / "SKILL.md").is_file():
            raise FileNotFoundError(f"missing official Skill: {path}")
        inputs.append(SkillInput(name=name, path=str(path)))
    inputs.append(TextInput(prompt))
    config = CodexConfig(cwd=str(ROOT), client_name="minimax_h3_context_ir", client_title="MiniMax-H3 Context-IR", env=agent_env)
    with log_path.open("w", encoding="utf-8") as log_file, Codex(config=config) as codex:
        log_file.write(json.dumps({"model": reasoning["model"], "provider_id": reasoning["provider_id"], "base_url": reasoning["base_url"], "skills": skill_names or []}, ensure_ascii=False) + "\n")
        thread = codex.thread_start(
            cwd=str(ROOT), developer_instructions=(ROOT / "AGENTS.md").read_text(encoding="utf-8"),
            model=reasoning["model"], model_provider=reasoning["provider_id"],
            approval_mode=ApprovalMode.deny_all, sandbox=Sandbox.workspace_write,
            config=build_config(reasoning),
        )
        raw = collect_turn(thread.turn(inputs, approval_mode=ApprovalMode.deny_all, sandbox=Sandbox.workspace_write), log_file)
    log_path.with_suffix(".raw.txt").write_text(raw, encoding="utf-8")
    return extract_json(raw)


def schema_template(source: dict[str, Any]) -> dict[str, Any]:
    task = source.get("task", {})
    reasoning = reasoning_provider_config()
    return {
        "schema_version": "0.1.0",
        "intent": {
            "user_request": source.get("user_request", ""),
            "resolved_request": source.get("resolved_request", ""),
            "directives": source.get("directives", []),
            "completion_policy": source.get("completion_policy", {}),
            "assumptions": [],
            "uncertainties": [],
        },
        "protocol": {"rewrite_language": "English", "preserve_source_language_for": ["dialogue", "lyrics", "visible scene text"], "summary_task_types": ["reference generation"]},
        "asset_bindings": [{"binding_id": "b_example", "asset_id": "asset_id", "target": "semantic target", "role": "identity|outfit|product|motion|voice|music|rhythm|camera|scene|style|first_frame|last_frame", "priority": "hard|soft", "source_directive_ids": ["directive_id"], "inherit": ["controlled attribute"], "exclude": ["uncontrolled attribute"]}],
        "subjects": [{"subject_id": "subject_1", "name": "stable identifiable entity", "kind": "person|product|animal|object|environment|other", "primary": True, "description": "stable visible identity and appearance", "source_asset_ids": ["asset_id"], "binding_ids": ["b_example"], "appearance_shot_ids": ["01"], "retention_mode": "fully_preserved|partially_preserved|attribute_transfer|weak_reference", "retention_description": "what remains or transfers"}],
        "reference_relationships": [{"asset_id": "asset_id", "relationship": "source_video_edit|reference_generation|keyframe_completion|video_continuation|audio_reuse|audio_reference", "subject_refs": ["subject_1"], "definition": "a noun phrase describing the exact role of this Picture, Video, or Audio reference; do not begin with 'is'", "retention_mode": "fully_preserved", "retention_description": "how this reference is used in the target video"}],
        "creative_focus": {"primary_target": "the subject or outcome that must dominate the finished video", "primary_subject_id": "subject_1", "primary_asset_id": "asset_id or empty for T2VA", "primary_binding_ids": ["b_example"], "objective": "the final visible outcome that matters most", "supporting_asset_ids": [], "required_shot_ids": ["01"], "presentation_requirements": ["an executable visibility, framing, material, or continuity requirement"]},
        "isolation_rules": [{"binding_id": "b_example", "allow": ["controlled attribute"], "block": ["uncontrolled attribute"]}],
        "constraints": {"preserve": [], "allow_change": [], "prohibit": []},
        "timeline": [{
            "shot_id": "01",
            "start_seconds": 0,
            "end_seconds": task.get("duration_seconds", 15),
            "primary_change": "the single main visible change in this beat",
            "event": "one executable visible event",
            "action": "",
            "camera": "Static Shot; the frame never moves, with no pan, push-in, zoom, or reframing, or name exactly one intended camera move",
            "lighting": "",
            "transition": "",
            "observable_end_state": "a concrete state a viewer can point to at the end of the beat",
            "state_changes": [{"subject_id": "subject_1", "property": "one continuity-critical property", "from": "state before this beat", "to": "state after this beat"}],
            "subject_refs": ["subject_1"],
            "asset_refs": [],
            "binding_refs": [],
        }],
        "audio_plan": {"voice": "", "music": "", "sound_effects": "", "ambient_sound": "", "sync_rules": []},
        "generation_description": {"cinematography": "", "lighting": "", "materials": "", "performance": "", "continuity": ""},
    }


def build_prompt(source: dict[str, Any], style_skill: str | None) -> str:
    return f"""
Compile the supplied user request, asset manifest, and optional provider-neutral
perception observations into Context-IR. Apply the official h3-prompt-writing
Skill semantics. {f'Use {style_skill} only as a creative planning reference; do not call unavailable MiniMax Hub tools.' if style_skill else ''}

The selected Skill content is already supplied to this turn through SkillInput.
Do not inspect the filesystem, run shell commands, access Git, browse the web, or
call any tool. Reason from the supplied Skill, request, manifest, and perception.

Semantic decision policy:
- The active reasoning model is text-only. Never claim to see or hear the raw asset URI.
- Treat only media_analysis.v2 evidence as perception evidence. Use field-level
  source and confidence: visible high-confidence evidence may support hard
  bindings; inferred evidence may only support a recorded assumption; unresolved
  evidence must never be silently promoted to fact.
- Entity attributes, relations, events, and state transitions are evidence, not
  user intent. Decide preservation, replacement, scope, and priority here.
- Perception describes facts; this turn decides asset roles and conflicts.
- This is a compiler, not an upstream conversational or creative-planning agent. Explicit user language and supplied directives are authoritative; perception only supplies facts needed to implement them.
- Treat every supplied directive as immutable. Expand it into bindings, constraints, subjects, relationships, timeline details, and continuity rules, but never override, weaken, or reinterpret it.
- A binding that cites a directive must use the directive's asset, retain hard priority when the directive is hard, and copy every directive scope item verbatim into inherit (or into exclude for an exclude directive). Use separate bindings when one asset controls different dimensions such as identity and motion.
- Copy every supplied directive into intent.directives unchanged. Never synthesize, split, rename, or assign IDs to new directives. If the supplied directives array is empty, emit intent.directives as [] and emit source_directive_ids as [] on every asset binding. Every supplied directive must be cited by at least one asset binding through source_directive_ids. A binding may cite several supplied directives, and a supplied directive may expand into several bindings.
- For requirements not explicitly specified, infer only the minimum conservative intent necessary to compile an executable result. Prefer the smallest change to the edit base, record the assumption, and never rely on a fixed phrase list or keyword-only matching.
- Never use media evidence to invent user intent. A visible person, outfit, scene, caption, or soundtrack is not inherited unless a directive, the user request, or an allowed conservative edit-base default requires it.
- Understanding language and rewrite language are separate. Write all generated Context-IR semantic descriptions in English. Preserve the source language only for verbatim dialogue, lyrics, and text visibly present in the requested scene, as required by the official H3 Skill.
- Keep intent.user_request and an upstream-supplied intent.resolved_request only as source-provenance fields. The deterministic H3 renderer does not copy them into the prompt; express the executable English task completely through creative_focus, constraints, timeline, generation_description, and audio_plan.
- For every asset, autonomously decide whether it is an edit base, an authoritative content source, or a scoped creative reference. Base the decision on how the user wants the asset used, not merely on media type.
- Determine each asset's authority and transferable dimensions. Inherit only attributes required by the resolved intent; explicitly exclude unrelated attributes that could contaminate identity, product, outfit, scene, text, logo, dialogue, voice, motion, camera, rhythm, or style.
- For an edit base, preserve all evidenced existing attributes except those the user requests or necessarily implies should change. For an authoritative content source, bind its controlled attributes as hard constraints. For a scoped reference, transfer only the requested or clearly necessary abstract dimensions.
- Resolve conflicts by following the user's intended outcome first, then hard identity/product/content sources, then evidenced reference facts, then soft creative references. Never let a soft reference overwrite a hard source.
- Independently determine creative prominence. Preservation authority does not determine narrative prominence: an asset may strongly constrain execution while remaining secondary to the subject being created, replaced, demonstrated, or promoted.
- Build subjects as a stable entity registry. A subject is an identifiable person, product, animal, object, or environment that can recur in shots. Identity, outfit, motion, camera, rhythm, lighting, style, and other attributes are not separate subjects. Assign sequential IDs subject_1, subject_2, and so on in first-appearance order.
- Treat each subjects[] entry as the one canonical profile for that entity. Reuse its exact appearance facts across all shots; do not redescribe the same face, hair, garment, product geometry, color, logo, or material differently in separate timeline entries.
- Attach every subject source through an explicit binding. Appearance bindings (identity, outfit, product, scene) state which visible attributes the asset controls. Structural bindings (motion, camera, rhythm, style) may guide execution but are not appearance sources. Never place a video into a subject's appearance authority merely because the video depicts a performer or product.
- Build one reference_relationships entry for every conditioned asset. Distinguish a directly edited source video from a video used only for reference generation. Link references to stable subjects without turning camera, motion, wardrobe, or scene attributes into subjects.
- Emit exactly one reference_relationships entry per conditioned asset. When a source video is directly edited and its original audio is also retained, use source_video_edit as the single relationship; describe audio retention in its retention_description and in audio_plan/voice or music bindings. Do not add a duplicate audio_reuse relationship for the same video asset.
- Choose reference retention modes by media type. For image and video assets use only fully_preserved, partially_preserved, attribute_transfer, or weak_reference. For audio assets use only fully_copy, partially_copy, reference, or weak_reference. Never use fully_copy or partially_copy for an image or video.
- Set protocol.summary_task_types using only official values: keyframe completion, reference generation, video editing, video continuation, audio reuse, audio reference. If a source video is directly modified, include video editing; if a reference only supplies camera, cuts, rhythm, or style, use reference generation instead.
- protocol.summary_task_types must cover every relationship in reference_relationships: source_video_edit maps to video editing, reference_generation to reference generation, keyframe_completion to keyframe completion, video_continuation to video continuation, audio_reuse to audio reuse, and audio_reference to audio reference. Do not omit a type merely because another relationship is more important.
- Fill creative_focus with exactly one primary outcome subject, its authoritative asset, and the binding(s) that control it. State why it is the final visual objective, which assets merely support its execution, the shots where it must be meaningfully presented, and concrete visibility, framing, material, or continuity requirements.
- Allocate detail according to creative_focus, not according to the number of bindings per asset. Describe a fully preserved reference relationship completely once, then avoid repeating unchanged reference details unless a shot needs them for execution. Spend the remaining detail on how the primary subject is presented.
- In every creative_focus.required_shot_id, make the primary subject visually meaningful rather than merely present. The shot event or action must explain how it is shown, and the shot must reference the primary binding.
- Every timeline shot must list stable subject_refs. Every subject appearance_shot_id must agree with the corresponding timeline subject_refs.
- Treat timeline as an executable beat sheet. Give every shot exactly one primary visible change and one observable end state. A cut must introduce new information about subject, space, state, viewpoint, time, or the primary product; otherwise prefer camera motion.
- Record continuity-critical state changes explicitly, including attachment, detachment, wearing, removal, hand-off, activation, deactivation, appearance, disappearance, or completion. When a later shot uses the same property, its starting state must follow the previous ending state. Never hide a required detach/reconnect, stop/restart, or bare-to-worn transition inside a cut.
- Budget enough time for physical state changes. If the requested duration cannot support every beat, preserve the user's locked beats and merge or remove only IR-added secondary beats.
- Always specify camera behavior. For a static shot, say that the frame never moves and explicitly reject pan, push-in, zoom, and reframing. For a moving shot, name one primary camera move and state its amplitude and speed when meaningful.
- Translate abstract mood or intent into observable behavior: gaze direction, named-hand action, posture, material response, and a visible end state.
- Obey completion_policy strictly. technical permits format, timing, attachment, geometry, and continuity completion. conservative_semantic permits only meaning-preserving expansion of an explicit directive. creative permits new creative content; it is false by default.
- `may_change` is permission, not an instruction to change. When no replacement is specified, preserve the evidenced edit-base value by default.
- Complete omitted production details only within completion_policy. Keep them consistent with supplied assets and target format, and do not invent factual claims or identity-bearing content.
- Record every IR-added inference or default in intent.assumptions and identify it as IR completion. A conflict with an explicit requirement or hard directive is an input error; do not silently choose another interpretation. Ask for clarification only when requirements conflict or no safe conservative interpretation exists.
- Put evidenced attributes that must remain unchanged in constraints.preserve. Put only requested changes and necessary production completion in constraints.allow_change. Put forbidden contamination and unsupported additions in constraints.prohibit.
- Every preserved attribute originating from an asset must be backed by a corresponding hard asset binding. Do not preserve characters from a creative reference unless that character is explicitly requested.
- Every binding must state inherit and exclude properties and have one isolation rule.
- asset_bindings[].role must be exactly one of: identity, outfit, product, motion, voice, music, rhythm, camera, scene, style, first_frame, last_frame. Never emit aliases or new role values such as content, text, prop, character, or wardrobe. Bind visible text overlays, props, and other visible scene content under scene; use outfit for wardrobe and identity for character identity.
- Motion/video references do not inherit performer identity, outfit, or scene unless explicitly requested.
- Style references do not inherit identity, product geometry, or logo.
- User instruction has highest priority, then hard identity/product bindings, then confirmed reference facts, then soft style/motion.
- Timeline starts at 0, has no gaps/overlaps, and ends exactly at the requested duration.
- Do not add unsupported brand claims, dialogue, logo text, identity facts, or asset content.
- The final response must be exactly one JSON object. No Markdown fence, commentary, or explanation.
- Do not emit runtime, task, assets, or perception. These authoritative fields are
  injected deterministically from the Input after your semantic JSON is parsed.
  Refer to their asset IDs and evidence, but never copy the large perception tree
  into the response.

Required shape (replace illustrative entries rather than copying them):
{json.dumps(schema_template(source), ensure_ascii=False, indent=2)}

Input:
{json.dumps(source, ensure_ascii=False, indent=2)}
""".strip()


def collect_turn(turn: Any, log_file) -> str:
    from openai_codex.generated.v2_all import AgentMessageDeltaNotification, ErrorNotification, ItemCompletedNotification

    chunks: list[str] = []
    completed_items: list[Any] = []
    for event in turn.stream():
        payload = event.payload
        if isinstance(payload, AgentMessageDeltaNotification):
            chunks.append(payload.delta)
            log_file.write(payload.delta)
            log_file.flush()
        elif isinstance(payload, ErrorNotification):
            message = f"Codex error (will_retry={payload.will_retry}): {payload.error.message}"
            log_file.write("\n" + message + "\n")
            log_file.flush()
            if not payload.will_retry:
                raise RuntimeError(message)
        elif isinstance(payload, ItemCompletedNotification) and payload.turn_id == turn.id:
            completed_items.append(payload.item)
    candidates = []
    for item in completed_items:
        root = item.root if hasattr(item, "root") else item
        if root.__class__.__name__ == "AgentMessageThreadItem" and getattr(root, "text", None):
            candidates.append(root.text)
    return candidates[-1] if candidates else "".join(chunks)


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        start = stripped.find("{")
        if start < 0:
            raise ValueError("reasoning-model response did not contain a JSON object")
        value, _ = decoder.raw_decode(stripped[start:])
    if not isinstance(value, dict):
        raise ValueError("GLM response root must be an object")
    return value


def audit_or_raise(ir: dict[str, Any], prompt: str) -> None:
    report = audit_h3_prompt(ir, prompt)
    if not report.passed:
        from backend.context_ir import ContextIRError

        raise ContextIRError(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


def run_agent(
    source: dict[str, Any],
    output_dir: Path,
    style_skill: str | None,
    perception_from: Path | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> int:
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
    model = reasoning["model"]
    provider_id = reasoning["provider_id"]
    base_url = reasoning["base_url"]
    api_key_env = reasoning["api_key_env"]
    if not os.environ.get(api_key_env):
        raise RuntimeError(f"Missing {reasoning['name']} API key environment variable: {api_key_env}")
    preflight_reasoning_provider(reasoning)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "input.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if progress_callback:
        progress_callback("intent")
    stage_started = time.perf_counter()
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
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "perception_plan.json").write_text(json.dumps(perception_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "resolved_input.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if progress_callback:
        progress_callback("bindings")
    stage_started = time.perf_counter()
    if perception_from is not None:
        perception = json.loads(perception_from.resolve().read_text(encoding="utf-8"))
        if not isinstance(perception, dict):
            raise ValueError("--perception-from must contain one media analysis JSON object")
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
        progress_callback("timeline")

    skill_names = ["h3-prompt-writing"] + ([style_skill] if style_skill else [])
    stage_started = time.perf_counter()
    model_output = invoke_reasoning_json(build_prompt(source, style_skill), reasoning, output_dir / "agent.log", skill_names)
    finish_stage("semantic_agent", stage_started)
    stage_started = time.perf_counter()
    ir = compile_context_ir(model_output, source)
    if progress_callback:
        progress_callback("isolation")
    context_path = output_dir / "context_ir.json"
    context_path.write_text(json.dumps(ir, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt = render_h3_prompt(ir)
    if progress_callback:
        progress_callback("prompt")
    audit_or_raise(ir, prompt)
    prompt_path = output_dir / "h3_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    audit_path = output_dir / "h3_prompt_audit.json"
    audit_path.write_text(
        json.dumps(audit_h3_prompt(ir, prompt).to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    request = build_h3_request(ir, str(prompt_path), str(output_dir / "h3_outputs"))
    (output_dir / "h3_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finish_stage("compile_render_audit", stage_started)
    stage_timings["total_seconds"] = round(time.perf_counter() - run_started, 3)
    (output_dir / "stage_timings.json").write_text(
        json.dumps(stage_timings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": True, "output_dir": str(output_dir), "context_ir": str(context_path), "h3_prompt": str(prompt_path), "h3_prompt_audit": str(audit_path), "h3_request": str(output_dir / 'h3_request.json')}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex MiniMax-H3 Context-IR agent")
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--style-skill", choices=sorted(OFFICIAL_SKILLS - {"h3-prompt-writing"}))
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
                "vlm_provider": os.environ.get("CONTEXT_IR_VLM_PROVIDER", "gitee-qwen3-vl"),
                "vlm_model": os.environ.get("YIWU_VLM_MODEL", "Qwen3-VL-30B-A3B-Instruct"),
                "vlm_api_key_env": os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY"),
                "vlm_api_key_present": bool(os.environ.get(os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY"))),
            })
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.validate_only:
            payload = json.loads(args.validate_only.read_text(encoding="utf-8"))
            report = validate_context_ir(payload)
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
