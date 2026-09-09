#!/usr/bin/env python3
"""Context-IR compiler runner with replaceable direct or Codex LLM runtimes."""

from __future__ import annotations

import argparse
import copy
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
    ContextIRError,
    audit_h3_prompt_contract,
    build_h3_request,
    compile_context_ir,
    normalize_h3_prompt_transport,
    normalize_source_request,
    render_h3_prompt,
    validate_source_request,
    validate_context_ir,
)
from backend.perception import PERCEPTION_PROVIDERS, PerceptionProviderConfig, sanitize_media_analysis_quality
from backend.intent_resolver import resolve_intent


ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
CORE_SKILLS = ("h3-prompt-writing", "h3-shot-planning")
OFFICIAL_SKILLS = set(CORE_SKILLS)


def reasoning_provider_config() -> dict[str, str]:
    selected = os.environ.get("CONTEXT_IR_LLM_PROVIDER", "deepseek_litellm").strip().lower()
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
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            "base_url": os.environ.get("DEEPSEEK_RESPONSES_BASE_URL", "https://api.deepseek.com"),
            "api_key_env": "DEEPSEEK_API_KEY",
            "http_host_env": "",
        }
    raise ValueError(
        "CONTEXT_IR_LLM_PROVIDER must be 'deepseek_litellm', 'deepseek', or 'glm'"
    )


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
        "stream_idle_timeout_ms": int(
            os.environ.get("CONTEXT_IR_LLM_STREAM_IDLE_TIMEOUT_MS", "600000")
        ),
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
    runtime = os.environ.get("CONTEXT_IR_LLM_RUNTIME", "direct").strip().lower()
    base_url = (
        os.environ.get(f"{reasoning['selection'].upper()}_CHAT_BASE_URL")
        or os.environ.get("CONTEXT_IR_LLM_CHAT_BASE_URL")
        or reasoning["base_url"]
    ) if runtime == "direct" else reasoning["base_url"]
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
    options.setdefault("image_base_url", os.environ.get("QWEN_IMAGE_UNDERSTAND_BASE_URL", "http://127.0.0.1:9012"))
    options.setdefault("video_base_url", os.environ.get("QWEN_VIDEO_UNDERSTAND_BASE_URL", "http://127.0.0.1:9012"))
    options.setdefault("api_key_env", os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY"))
    options.setdefault("video_frame_count", int(os.environ.get("CONTEXT_IR_VIDEO_FRAME_COUNT", "0")))
    options.setdefault("max_tokens", int(os.environ.get("CONTEXT_IR_VLM_MAX_TOKENS", "3000")))
    options.setdefault("cache_enabled", os.environ.get("CONTEXT_IR_VLM_CACHE_ENABLED", "1") not in {"0", "false", "False"})
    options.setdefault("cache_dir", os.environ.get("CONTEXT_IR_VLM_CACHE_DIR", ""))
    if not options["cache_dir"]:
        options.pop("cache_dir")
    options.setdefault("max_parallel_assets", int(os.environ.get("CONTEXT_IR_VLM_MAX_PARALLEL_ASSETS", "2")))
    options.setdefault("max_parallel_attribute_batches", int(os.environ.get("CONTEXT_IR_VLM_MAX_PARALLEL_ATTRIBUTE_BATCHES", "2")))
    options.setdefault("image_attribute_batch_size", int(os.environ.get("CONTEXT_IR_VLM_IMAGE_ATTRIBUTE_BATCH_SIZE", "3")))
    options.setdefault("single_pass_image_analysis", os.environ.get("CONTEXT_IR_VLM_SINGLE_PASS_IMAGE", "1") not in {"0", "false", "False"})
    options.setdefault("single_pass_video_analysis", os.environ.get("CONTEXT_IR_VLM_SINGLE_PASS_VIDEO", "1") not in {"0", "false", "False"})
    return PerceptionProviderConfig(
        provider=str(supplied.get("provider") or os.environ.get("CONTEXT_IR_VLM_PROVIDER", "gitee-qwen3-vl")),
        model=str(supplied.get("model") or os.environ.get("YIWU_VLM_MODEL", "Qwen3-VL-30B-A3B-Instruct")),
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
                # Direct Chat has no filesystem tool. The skill index alone
                # cannot execute its instruction to read the protocol guides.
                # Ref2VA also imports the base guide's speech/camera rules.
                for reference_name in ("base-en.txt", "ref-en.txt"):
                    reference = path.parent / "references" / reference_name
                    system_parts.append(reference.read_text(encoding="utf-8"))
        return direct_runtime_from_config(reasoning).invoke_json(
            prompt,
            system_parts=system_parts,
            log_path=log_path,
        )
    if runtime != "codex":
        raise ValueError("CONTEXT_IR_LLM_RUNTIME must be 'direct' or 'codex'")

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
        "semantic_plan": {
            "primary_focus": "subject_1 or the intended visible outcome",
            "subject_priority": {"mode": "single|co_equal|explicit_hierarchy", "subject_ids": ["subject_1"], "reason": "derived only from user intent"},
            "text_policy": {"mode": "exact|preserve|generate|omit", "allow_invention": False, "provided_text": []},
            "edit_scope": {"mode": "generate|reference_transfer|minimal_edit", "editable": [], "locked": []},
            "persistent_visual_layers": [{"source_asset_id": "asset_id", "description": "cross-shot mask, interface, overlay, or environment layer", "applies_to_shot_ids": ["01"]}],
            "exact_text": [{"source_asset_id": "asset_id", "value": "verified text or empty", "status": "verified|uncertain|reference_exactly", "instruction": "preservation behavior"}],
            "completion_authority": {"technical": True, "timeline": True, "story_continuation": False, "new_core_entities": False, "brand_claims": False},
            "shot_planning_mode": "strict|reference|adaptive",
            "shot_functions": [{"shot_id": "01", "purpose": "one unique narrative or presentation function", "audience_gain": "new information visible by the end of this shot", "cut_reason": "new_information|action_match|state_change|viewpoint_change|reference_match|user_locked|none"}],
        },
        "intent": {
            "assumptions": [],
            "uncertainties": [],
        },
        "protocol": {"rewrite_language": "English", "preserve_source_language_for": ["dialogue", "lyrics", "visible scene text"], "summary_task_types": ["reference generation"]},
        "asset_bindings": [{"asset_id": "asset_id", "target": "semantic target", "role": "identity|outfit|product|motion|voice|music|rhythm|camera|scene|style|first_frame|last_frame", "priority": "hard|soft", "source_directive_ids": ["directive_id"], "inherit": ["controlled attribute"], "exclude": ["uncontrolled attribute"]}],
        "subjects": [{"subject_id": "subject_1", "name": "stable identifiable entity", "kind": "person|product|animal|object|environment|other", "primary": True, "description": "stable visible identity and appearance", "source_asset_ids": ["asset_id"], "appearance_shot_ids": ["01"], "retention_mode": "fully_preserved|partially_preserved|attribute_transfer|weak_reference", "retention_description": "what remains or transfers"}],
        "reference_relationships": [{"asset_id": "asset_id", "relationship": "source_video_edit|reference_generation|keyframe_completion|video_continuation|audio_reuse|audio_reference", "subject_refs": ["subject_1"], "definition": "a noun phrase describing the exact role of this Picture, Video, or Audio reference; do not begin with 'is'", "retention_mode": "fully_preserved", "retention_description": "how this reference is used in the target video"}],
        "keyframe_roles": [{
            "asset_id": "image asset_id",
            "role": "appearance_source|scene_anchor|action_keyframe|product_detail|first_frame|last_frame|composition_anchor|style_reference",
            "subject_refs": ["subject_1"], "shot_refs": ["01"], "beat_refs": ["beat_01 only for action_keyframe"],
            "controls": ["visible dimension supplied by the Picture"],
            "excludes": ["motion", "camera", "editing", "music", "performance rhythm"],
            "description": "one concise explanation of how the Picture is used",
            "source": "explicit_user|reference_evidence|derived_requirement",
            "evidence_refs": [], "confidence": 1.0,
        }],
        "performance_plan": {
            "source_asset_ids": ["video asset_id used for motion/performance"],
            "transfer_scope": ["action", "expression", "performance_rhythm"],
            "excluded_scope": ["identity", "outfit", "scene", "camera", "editing"],
            "beats": [{
                "beat_id": "beat_01 in observed event order",
                "source_asset_id": "video asset_id", "source_event_id": "observed event_id",
                "action": "target action after user-requested semantic replacement",
                "action_source": "reference_evidence|explicit_user|derived_requirement",
                "subject_refs": ["subject_1"], "editorial_boundary": False,
            }],
        },
        "creative_focus": {"primary_target": "the user's intended visible outcome, including joint goals where requested", "primary_subject_id": "subject_1", "primary_asset_id": "asset_id or empty for T2VA", "objective": "the final visible outcome that matters most", "supporting_asset_ids": [], "required_shot_ids": ["01"], "presentation_requirements": ["an executable visibility, framing, material, or continuity requirement"]},
        "constraints": {"preserve": [], "allow_change": [], "prohibit": []},
        "timeline": [{
            "shot_id": "01",
            "start_seconds": 0,
            "end_seconds": task.get("duration_seconds", 15),
            "primary_change": "the single main visible change in this beat",
            "event": "one executable visible event",
            "action": "",
            "camera": "one executable static or motivated moving-camera instruction",
            "lighting": "",
            "transition": "",
            "observable_end_state": "a concrete state a viewer can point to at the end of the beat",
            "state_changes": [{"subject_id": "subject_1", "property": "one continuity-critical property", "from": "state before this beat", "to": "state after this beat"}],
            "subject_refs": ["subject_1"],
            "asset_refs": ["asset_id only when this shot uses its motion, camera, rhythm, style, audio, or scene guidance"],
            "beat_refs": ["beat_01; the compiler verifies and reattaches these deterministically"],
        }],
        "audio_plan": {"voice": "", "music": "", "sound_effects": "", "ambient_sound": "", "sync_rules": []},
        "production_policies": {
            module: {"mode": "strict|disabled|reference|enhance|auto", "source": "explicit_user|explicit_prohibition|reference_evidence|edit_base_preservation|user_soft_goal|category_prior|default_completion|inferred", "priority": "hard|soft", "allow_new_events": False, "preserve_reference": False, "constraints": {}, "events": [{"event_id": "event_1", "type": "module-specific event type", "description": "observable production event", "source": "explicit_user|reference_evidence|category_prior|default_completion", "priority": "hard|soft", "shot_refs": ["01"]}], "prohibit": [], "assumptions": []}
            for module in ("camera", "editing", "motion", "performance", "composition", "lighting", "audio", "style", "effects", "text")
        },
        "entity_constraints": {
            module: {"mode": "strict", "source": "explicit_user|reference_evidence|derived_requirement", "priority": "hard", "allow_new_events": False, "preserve_reference": True, "constraints": {}, "events": [], "prohibit": [], "assumptions": []}
            for module in ("identity", "product", "continuity")
        },
        "generation_description": {"cinematography": "", "lighting": "", "materials": "", "performance": "", "continuity": ""},
    }


def build_prompt(source: dict[str, Any]) -> str:
    return f"""
Compile the supplied user request, asset manifest, and optional provider-neutral
perception observations into Context-IR. Apply the official h3-prompt-writing
Skill semantics and the internal h3-shot-planning Skill. The shot-planning Skill
controls camera and editorial decisions only; it never overrides user directives,
asset authority, entity truth, or H3 output structure.

The selected Skill content is already supplied to this turn through SkillInput.
Do not inspect the filesystem, run shell commands, access Git, browse the web, or
call any tool. Reason from the supplied Skill, request, manifest, and perception.

Semantic decision policy:
- First form semantic_plan, then derive every downstream subject, binding,
  relationship, timeline entry, and constraint from that plan. semantic_plan is
  a compact decision record, not prose and not a second conflicting timeline.
- Treat reference_registry as immutable. Internal asset IDs, media types, and
  official labels must never be guessed, renumbered, or reassigned. A Picture
  can provide appearance, composition, scene, style, or a keyframe, but never
  observed motion, edit rhythm, or music. A Video can provide motion, camera,
  edit rhythm, or an edit base only when authorized by the user.
- Subject inventory and prominence are separate decisions. A secondary person
  who performs a requested action still needs a stable Subject definition and
  appearance source, even if a product or campaign is the primary focus.
  Do not collapse physical entities to satisfy a single primary_subject_id.
  A global overlay may be a persistent Subject; individual scene compositions
  can remain Picture anchors without manufacturing a shared product identity.
- Preserve goal-relevant distinguishing evidence during compression: component
  shape and placement, worn/held relationships, and visible material structure
  matter more than generic aesthetic adjectives. State these once in the relevant
  Subject definition; do not reduce an evidenced distinctive component to its
  generic category. Keep uncertainty local to the disputed property: uncertain
  view orientation does not invalidate a clearly observed component's shape;
  an occluded or unseen component in another view is not proof of its absence.
  Preserve explicit uncertainty in an observation even when confidence is high.
  Describe appearance as appearance: leather-like or metallic-looking does not
  establish material composition. Apply the same qualified fact in the Subject,
  binding and preservation constraint instead of hardening it while paraphrasing.
- When a reference board contains supported views of the same person or product,
  combine complementary front, side, back and detail observations before choosing
  the target Subject's appearance. Do not use only the first entity summary.
  Preserve goal-relevant hair arrangement, garment neckline/fit/length, surface
  pattern, footwear and distinctive product components in that Subject's IR
  description. Keep different subjects separate, and keep their source evidence
  traceable. Repeated views are not additional target characters; uncertain
  cross-view identity must remain uncertain rather than being force-merged.
  A main character's clothing details matter as much as product geometry when
  the user's objective includes fashion or character appearance. State stable
  details once, then express only their changes or relevant visibility in shots.
- Resolve the user's requested presentation style before selecting coverage.
  If products must be integrated naturally into character action, make their
  relevant details legible within that action instead of adding a standalone
  inspection shot by default. Product importance does not override an explicit
  prohibition on catalog, demonstration, or e-commerce presentation.
- Within user-authorized planning freedom, allocate framing and time to what
  the audience must actually see, not equally to each verb in the story.
  Keep short enabling actions together when readable, reserving coverage for
  the primary reveal, interaction, or completed use. A fashion story can reveal
  clothing through a legible body view and a carried accessory through movement;
  neither requires an isolated product insert. Name the relevant visible body
  landmarks or object surfaces in the existing shot composition. Use a wider
  view when spatial action needs it, not as an automatic safe default. Do not
  abbreviate an operation that is itself the user's demonstration goal. Preserve
  user-locked shots, timing and authorized reference structure; do not enforce
  a universal close-up quota, shot count, or duration ratio.
- Decide semantic_plan.subject_priority from the user's requested outcome. When
  the user presents several people or products in parallel, mark them co_equal
  and never make one dominant or demote another merely because the schema needs
  one primary_subject_id anchor.
- A reciprocal interaction such as handing, fighting, dancing together, or
  reacting to one another normally makes every participating character subject
  to the same authorized interaction/performance reference unless the user
  explicitly limits the reference to one participant.
- Keep reference dimensions separate. A request to transfer actions,
  expressions, or performance rhythm from a Video authorizes performance only;
  it does not authorize the Video's camera, cuts, transitions, shot count, or
  visual scene. Unless an explicit directive separately grants camera or
  editorial authority, express the complete interaction as one continuous
  full-duration shot with conservative locked framing. Put ordered performance
  beats inside that shot and let the conditioned Video control their relative
  timing. Never convert action beats into cuts merely to make the timeline look
  organized.
- Camera rhythm, shot rhythm, and performance rhythm are different controls.
  Do not infer either of the first two from a directive whose target is body
  action, facial expression, interaction, or performance rhythm.
- Decide semantic_plan.edit_scope before shots. In minimal_edit mode, change
  only the explicitly editable region or property and lock the source camera,
  action, subjects, scene elements, and effects unless the user changes them.
  In generation mode, edit_scope.locked records source-backed constraints, not
  your chosen solution. Each lock must be justified by an explicit directive,
  authorized reference preservation, or an actual continuity requirement.
  Record discretionary shot count and coverage in shot_functions instead.
  Choosing one shot does not authorize a lock forbidding additional shots;
  choosing no music does not establish a user prohibition on music. Preserve
  real one-shot and silence requests. Check that locks do not contradict the
  declared completion_authority before returning the semantic plan.
- Decide semantic_plan.text_policy by source authority before checking spelling.
  Evidence that text exists is not permission to use it. Inherit text only when
  the user's requested content, exact frame, or edit-base preservation includes
  it; a mood/style-only reference supplies no literal captions, names or telemetry,
  even as optional overlays. When creative completion is false, never invent
  titles, names, credits, brands, claims, or exact copy. When text is authorized,
  use user-supplied or reliably verified copy; otherwise preserve the reference
  typography without guessing, or record an unresolved required text value.
- User language is authoritative over perception. When perception conflicts
  with an explicit user description, preserve the user value and record the
  disagreement in intent.uncertainties; never let Qwen silently overwrite it.
- Read each image's global_analysis before its localized entities. Treat masks,
  borders, vignettes, interfaces, overlays, split screens, and frame-within-frame
  compositions as persistent_visual_layers when they recur or the user requires
  them across shots. Do not confuse the scene inside a layer with the layer.
- Text, logos, model numbers, and brand marks are high-risk evidence. For content
  already authorized by text_policy, copy literally only when supplied by the
  user or marked exact by reliable evidence. Retain its goal-relevant location
  and appearance in the appropriate subject or shot; uncertainty about spelling
  is not a reason to omit a required sign, label, or reflection altogether.
  If OCR is partial, cropped, conflicting, or uncertain, never guess missing
  characters. Use semantic_plan.exact_text status reference_exactly and instruct
  H3 to preserve the complete source Picture typography and layout without
  reconstructing or respelling it.
- A still image may supply appearance, scene, style, composition, first-frame,
  or last-frame authority, but never motion authority. Motion added from an
  implied static pose is IR completion, not motion inherited from that image.
  Absence of observed motion does not authorize a stillness lock. Decide target
  motion from user instructions and completion_authority: preserve specified
  stillness within its actual shot scope, but when continuation is authorized,
  allow a small compatible action or reveal with the same subjects. Record it
  as completion, never as evidence. Do not let an appearance-only Picture's
  static nature disable authorized performance in subsequent shots.
- Compile every conditioned Picture into keyframe_roles before planning shots.
  A shared brand, logo, campaign theme, or word does not prove physical entity
  identity across Pictures. Keep a sign, fabric banner, building, and reflection
  as distinct visible content unless the evidence actually establishes one
  physical entity. A campaign focus may span several Subjects without turning
  them into a single product. Bind each target using its explicit subject ID;
  sharing a source Picture does not give a person the product's attributes.
  For a sequence of still Pictures, use composition_anchor with shot_refs for
  intermediate frame anchors; do not interpret the word 'keyframe' as requiring
  action_keyframe. User-requested animation belongs in timeline.action and
  state_changes, with the user as its authority, not in image inherit scopes.
  performance_plan describes observed Video performance only. Without a
  motion/performance Video, emit empty performance_plan.beats and empty
  beat_refs everywhere. Do not invent Video events for still-image animation.
  An action_keyframe is specifically a Picture aligned to a real observed
  Video event; its beat must exist in that Video's performance_plan.
  Choose its semantic function independently of asset order: appearance_source
  for identity/outfit/product appearance, scene_anchor for environment,
  action_keyframe only when the user or evidence links the Picture to a specific
  performance beat, product_detail for an exact product-detail view, and
  first_frame/last_frame only when explicitly requested or required by the task.
  A Picture may have several dimension-scoped roles, but no Picture can supply
  motion, camera movement, edit rhythm, music, or performance timing. Every
  conditioned Picture must have at least one explainable role.
- Compile a motion/performance Video into performance_plan beats before writing
  timeline shots. Emit one semantic beat for each usable observed Video event,
  preserving source_asset_id and source_event_id. Write action as the requested
  target-world action: user-directed object/content replacement overrides the
  observed source object while the event's order and timing remain evidence.
  Do not copy source_range or target_range; the deterministic compiler injects
  and maps them from measured perception duration to target duration.
- A performance beat is not a Shot. Attach ordered beats to timeline[].beat_refs
  while keeping the Shot count determined only by user shot instructions,
  reliable edit/cut evidence with authorized editorial scope, or a real scene,
  time, viewpoint, or information change. For motion-only references, attach all
  beats to one continuous full-duration Shot and set editorial_boundary=false.
- Never fill uncovered Video time by looping, evenly dividing, or inventing a
  final action. The deterministic compiler emits unresolved_tail when observed
  events stop before the measured Video duration.
- Derive completion_authority from user language. An explicit statement that
  the prompt is incomplete or may be supplemented authorizes conservative
  timeline and story completion using existing subjects, but never new core
  entities, identity changes, product changes, or factual brand claims.
- When completion_policy.conservative_semantic is true because the user marks a
  storyboard incomplete or explicitly permits supplementation, set
  completion_authority.story_continuation=true for meaning-preserving
  continuation with existing authorized subjects. completion_policy.creative=false
  blocks new concepts and core entities; it does not require stretching one
  supplied opening beat across the entire duration.
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
- A source-inheritance binding must cite the correct directive asset and retain
  hard priority. Preserve/transfer scopes belong in inherit, exclusions in
  exclude. A may_change directive grants target editing permission: implement
  it in the relevant timeline action or constraints.allow_change, never as
  observed source motion or an inherited attribute. The compiler records these
  permissions separately with their original directive IDs.
- Copy supplied directives into intent.directives unchanged; do not invent IDs.
  Source-inheritance directives require binding citations. Target-change
  permissions and global instructions do not require synthetic asset bindings.
  Use explicit subject IDs in each binding target so shared Pictures do not
  spread product attributes onto unrelated people or scene elements.
- For requirements not explicitly specified, infer only the minimum conservative intent necessary to compile an executable result. Prefer the smallest change to the edit base, record the assumption, and never rely on a fixed phrase list or keyword-only matching.
- Never use media evidence to invent user intent. A visible person, outfit, scene, caption, or soundtrack is not inherited unless a directive, the user request, or an allowed conservative edit-base default requires it.
- Understanding language and rewrite language are separate. Write all generated Context-IR semantic descriptions in English. Preserve the source language only for verbatim dialogue, lyrics, and text visibly present in the requested scene, as required by the official H3 Skill.
- Return only assumptions and uncertainties inside intent. The compiler injects
  user_request, resolved_request, directives, and completion_policy from the
  authoritative input; do not reproduce those fields. Still implement every
  source directive in the semantic decisions and cite its existing ID where
  required. Express the executable task through creative_focus, constraints,
  timeline, generation_description, and audio_plan.
- For every asset, autonomously decide whether it is an edit base, an authoritative content source, or a scoped creative reference. Base the decision on how the user wants the asset used, not merely on media type.
- Determine each asset's authority and transferable dimensions. Inherit only attributes required by the resolved intent; explicitly exclude unrelated attributes that could contaminate identity, product, outfit, scene, text, logo, dialogue, voice, motion, camera, rhythm, or style.
- For an edit base, preserve all evidenced existing attributes except those the user requests or necessarily implies should change. For an authoritative content source, bind its controlled attributes as hard constraints. For a scoped reference, transfer only the requested or clearly necessary abstract dimensions.
- Resolve conflicts by following the user's intended outcome first, then hard identity/product/content sources, then evidenced reference facts, then soft creative references. Never let a soft reference overwrite a hard source.
- Independently determine creative prominence. Preservation authority does not determine narrative prominence: an asset may strongly constrain execution while remaining secondary to the subject being created, replaced, demonstrated, or promoted.
- Build subjects as a stable entity registry. A subject is an identifiable person, product, animal, object, or environment that can recur in shots. Identity, outfit, motion, camera, rhythm, lighting, style, and other attributes are not separate subjects. Assign sequential IDs subject_1, subject_2, and so on in first-appearance order.
- Treat each subjects[] entry as the one canonical profile for that entity. Reuse its exact appearance facts across all shots; do not redescribe the same face, hair, garment, product geometry, color, logo, or material differently in separate timeline entries.
- Keep each subject description to one compact appearance profile, normally 20-45 English words. Do not place camera motion, transitions, edit rhythm, lighting events, or shot actions in an appearance description.
- Attach every subject source through an explicit binding. Appearance bindings (identity, outfit, product, scene) state which visible attributes the asset controls. Structural bindings (motion, camera, rhythm, style) may guide execution but are not appearance sources. Never place a video into a subject's appearance authority merely because the video depicts a performer or product. Do not author binding_ids: the compiler derives them from source_asset_ids.
- Build one reference_relationships entry for every conditioned asset. Distinguish a directly edited source video from a video used only for reference generation. Link references to stable subjects without turning camera, motion, wardrobe, or scene attributes into subjects.
- Emit exactly one reference_relationships entry per conditioned asset. When a source video is directly edited and its original audio is also retained, use source_video_edit as the single relationship; describe audio retention in its retention_description and in audio_plan/voice or music bindings. Do not add a duplicate audio_reuse relationship for the same video asset.
- Choose reference retention modes by media type. For image and video assets use only fully_preserved, partially_preserved, attribute_transfer, or weak_reference. For audio assets use only fully_copy, partially_copy, reference, or weak_reference. Never use fully_copy or partially_copy for an image or video.
- Set protocol.summary_task_types using only official values: keyframe completion, reference generation, video editing, video continuation, audio reuse, audio reference. If a source video is directly modified, include video editing; if a reference only supplies camera, cuts, rhythm, or style, use reference generation instead.
- protocol.summary_task_types must cover every relationship in reference_relationships: source_video_edit maps to video editing, reference_generation to reference generation, keyframe_completion to keyframe completion, video_continuation to video continuation, audio_reuse to audio reuse, and audio_reference to audio reference. Do not omit a type merely because another relationship is more important.
- Fill creative_focus with one primary_subject_id as a technical registry anchor,
  not an instruction to choose a unique commercial or narrative priority. Derive
  its rationale and visibility requirements from semantic_plan.subject_priority:
  when the user requests a joint outcome, describe that joint outcome and the
  relevant co-equal subjects in these existing fields. Supporting assets are
  those the user actually assigns supporting roles, not every non-anchor subject.
  Do not author primary_binding_ids: the compiler derives them.
- Allocate detail according to the user's outcome and semantic_plan.subject_priority,
  not the number of bindings or the single creative_focus registry anchor.
  Describe stable appearance once in subjects; bindings identify controlled
  dimensions and shots describe their visibility or changes, rather than
  independently paraphrasing the same appearance into competing profiles.
- In every creative_focus.required_shot_id, make the primary subject visually meaningful rather than merely present. The shot event or action must explain how it is shown; the compiler attaches its primary bindings.
- Every timeline shot must list stable subject_refs. Use asset_refs only for assets that provide shot-specific structural or scene guidance. Do not author binding_refs; the compiler derives them from subject_refs, asset_refs, and creative focus. Every subject appearance_shot_id must agree with the corresponding timeline subject_refs.
- Timeline entries are editorial Shots, not action containers. List beat_refs for
  the performance beats executed inside each Shot; do not repeat the same action
  sequence as several shots merely because perception returned several events.
- Apply h3-shot-planning to produce an executable, compact beat sheet. Every shot
  must have one unique editorial function, one primary visible change, one
  observable end state, and one non-conflicting camera instruction. Preserve
  continuity-critical state changes and user-locked shot decisions exactly.
- A motion or performance reference does not authorize a new edit structure.
  When one continuous interaction can be captured coherently and the user did
  not request cuts, prefer one continuous shot over dividing each action into a
  separate shot. Use multiple shots only for a real viewpoint, information,
  scene, time, or explicitly referenced edit change.
- If the user requests a reference video's cuts or pacing, use its valid event
  timeline and measured scene-cut candidates. Never replace missing or invalid
  reference timing with uniformly divided shots while claiming strict reference.
  If timing evidence is unavailable, record uncertainty and use the smallest
  conservative visual plan without claiming exact replication.
- Obey completion_policy strictly. technical permits format, timing, attachment, geometry, and continuity completion. conservative_semantic permits only meaning-preserving expansion of an explicit directive. creative permits new creative content; it is false by default.
- `may_change` is permission, not an instruction to change. When no replacement is specified, preserve the evidenced edit-base value by default.
- Complete omitted production details only within completion_policy. Keep them consistent with supplied assets and target format, and do not invent factual claims or identity-bearing content.
- Record every IR-added inference or default in intent.assumptions and identify it as IR completion. A conflict with an explicit requirement or hard directive is an input error; do not silently choose another interpretation. Ask for clarification only when requirements conflict or no safe conservative interpretation exists. Do not ask which asset is primary when exactly one compatible supplied asset can safely serve the requested operation; record the implicit unique choice as an assumption instead.
- Put evidenced attributes that must remain unchanged in constraints.preserve. Put only requested changes and necessary production completion in constraints.allow_change. Put forbidden contamination and unsupported additions in constraints.prohibit.
- Every preserved attribute originating from an asset must be backed by a corresponding hard asset binding. Do not preserve characters from a creative reference unless that character is explicitly requested.
- Every binding must state only its semantic source, target, role, priority, directive provenance, inherit scope, and exclude scope. Do not author binding_id or isolation_rules; the compiler creates one canonical ID and one isolation mirror per binding.
- Before writing timeline details, resolve production_policies as the permission matrix for camera, editing, motion, performance, composition, lighting, audio, style, effects, and text. Choose strict for an explicit specification, disabled for an explicit prohibition, reference only for authorized observable reference behavior, enhance only when the user authorizes visual or commercial enhancement, and auto otherwise. Do not choose a mode merely from the Case name or product category.
- For every production policy, record source, priority, allow_new_events, preserve_reference, constraints, events, prohibit, and assumptions. Explicit user requirements and prohibitions are hard. Reference evidence may control only the dimensions assigned to that reference. Category priors and default completion are always soft and cannot override a hard requirement, edit-base preservation, product truth, identity, or continuity.
- A positive requirement is not an exhaustive whitelist. A strict policy locks
  the specified property and its stated temporal scope, not every unspecified
  property of that module. Do not label planner-added exclusions explicit_user.
  For example, required slight frame shake may coexist with an authorized
  tracking move; it does not itself mean 'no tracking'. Required music does not
  forbid Foley. Preserve genuine 'only', 'fixed', 'no movement', and minimal-edit
  locks. Unspecified compatible details remain governed by completion_policy,
  not automatically permitted and not automatically prohibited. Keep any
  discretionary simplification as a planner choice rather than a user command.
- Apply minimum-new-content behavior in auto mode. Camera and editing add no new events unless execution requires them. Lighting preserves stable natural exposure and adds no dynamic light event without evidence or authorized enhancement. Effects and new text are disabled by default. Audio may use restrained technical completion when enabled, but never unsupported voice. Every dynamic policy event must cite the affected timeline shot_ids.
- Treat source video editing as preservation by default: camera, editing, motion, lighting, and original audio use reference mode with hard priority unless the user explicitly requests changes. A video used only for structure or motion does not grant permission to inherit its scene, identity, outfit, lighting, text, effects, or audio.
- Emit entity_constraints for identity, product, and continuity as strict hard policies. Product geometry, material, color, count, label/logo, identity, and cross-shot state may change only when the user explicitly requests the corresponding change. Sensory or stylistic enhancement must never reduce entity correctness.
- asset_bindings[].role must be exactly one of: identity, outfit, product, motion, voice, music, rhythm, camera, scene, style, first_frame, last_frame. Never emit aliases or new role values such as content, text, prop, character, or wardrobe. Bind visible text overlays, props, and other visible scene content under scene; use outfit for wardrobe and identity for character identity.
- Motion/video references do not inherit performer identity, outfit, or scene unless explicitly requested.
- Style references do not inherit identity, product geometry, or logo.
- User instruction has highest priority, then hard identity/product bindings, then confirmed reference facts, then soft style/motion.
- Timeline starts at 0, has no gaps/overlaps, and ends exactly at the requested duration.
- A change from live action to a separate logo slate is an editorial cut with
  its own Shot and start time. Budget that hold before distributing the action
  duration. Do not bury a second shot inside 'then cut to' within one timeline
  item. Consecutive supplied frame anchors map explicitly to shot_refs and
  keyframe_completion relationships; they are not one morphing physical object.
- Do not add unsupported brand claims, dialogue, logo text, identity facts, or asset content.
- Preserve causal hand/prop continuity inside each shot. If an actor receives
  an object and next needs that hand for another action, state the necessary
  placement, release or hand transfer before the next action. Show where a
  thrown or applied material comes from. Add only the minimum bridge needed
  by authorized actions and available scene evidence, not a new story beat.
- For audio retention, fully_copy means the source is the entire final audio
  track with no other layers. Replacing only dialogue while preserving ambience
  or adding other sounds is partially_copy even if the entire supplied speech
  clip is used. Referencing words or delivery without copying the signal is
  reference. User-provided transcripts are authoritative text, not proof of
  measured audio duration, timbre, or any unanalysed sound characteristics.
- Separate source-audio preservation from newly designed sound. Visual evidence
  cannot establish what the source soundtrack contains. For an unanalysed edit
  base, request preservation of its existing non-replaced audio without naming
  hypothetical traffic, birds, hum, music, timbre, or beat as observed facts.
  New scene-consistent sound is a generation instruction, not a source claim;
  add it only where completion permissions and edit scope allow it.
- Treat audio as part of the finished video, not as optional decoration. When task.generate_audio is true, produce a complete, restrained audio_plan and never leave overall soundscape intent empty. Scene-consistent ambience, physically motivated Foley, product sounds, non-vocal commercial music, and audio-visual synchronization are technical completion under completion_policy.technical; they do not require completion_policy.creative. Describe scene-appropriate ambient sound, action-synchronized Foley or product sounds, and at least one useful sync_rule; add non-diegetic music when it supports the requested commercial style. Keep the primary product and visual objective dominant rather than over-designing the soundtrack.
- When a directly edited source video supplies an original soundtrack, preserve or reuse that soundtrack to the extent required by the user and edit-base policy, keeping speech and actions synchronized. When an audio reference is supplied, follow only its authorized voice, music, rhythm, or full-copy scope.
- Design sound at its actual temporal scope. Put each action-synchronized sound
  in its corresponding timeline event, including its onset and stop cue. Keep
  continuous ambience in audio_plan.ambient_sound; it should follow the scene
  rather than reset at every cut. Describe any audience-only score in
  audio_plan.music with instrumentation, tempo/pace, and dynamic development
  through the ending. Respect requested silence, absent music, and quiet holds.
  Do not invent a measured reference BPM or a heard instrument from visual
  evidence. Distinguish newly designed target audio from observed source audio.
  For user-supplied speech, preserve exact words and language, identify the
  actual speaker, reserve plausible speaking time, and lower music beneath it.
  Do not add narration merely because the requested output is an advertisement.
- Plan audio from the decisive visible beats before choosing a music bed. When
  technical completion is allowed, select only the actions or authorized edit
  events whose audible cue helps the audience read contact, operation, focus,
  transition, or resolution. Record each selected cue in that timeline event
  and its sync rule; music accents alone do not replace useful action sounds.
  A camera move is not inherently audible: an optical or editorial sound is
  optional designed sound, never evidence of an unheard source recording.
  Do not sonify every motion. Keep quiet beats quiet and finish any release or
  decay before the video ends, or explicitly cut the sound at the final frame.
- Never invent speech, narration, dialogue, lyrics, vocal identity, or factual audio claims without an explicit request or authoritative audio/edit-base source. A no-voice requirement still allows music, ambience, and Foley. If task.generate_audio is false because the user explicitly requested silence or disabled audio, keep every audio_plan field empty and do not add music, ambience, Foley, or voice.
- The final response must be exactly one JSON object. No Markdown fence, commentary, or explanation.
- Do not emit runtime, task, assets, or perception. These authoritative fields are
  injected deterministically from the Input after your semantic JSON is parsed.
  Refer to their asset IDs and evidence, but never copy the large perception tree
  into the response.

Required shape (replace illustrative entries rather than copying them):
{json.dumps(schema_template(source), ensure_ascii=False, indent=2)}

Input:
{json.dumps(_compact_final_editor_source(source), ensure_ascii=False, indent=2)}
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


def _clip_text(value: Any, limit: int = 320) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _reference_registry(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the immutable internal-ID to official-label registry."""
    counters = {"image": 0, "video": 0, "audio": 0}
    names = {"image": "Picture", "video": "Video", "audio": "Audio"}
    aliases: dict[str, list[str]] = {}
    for mention in source.get("asset_mentions", []):
        if not isinstance(mention, dict):
            continue
        source_text = _clip_text(mention.get("source_text"), 80)
        for asset_id in mention.get("resolved_asset_ids", []):
            if source_text:
                aliases.setdefault(str(asset_id), []).append(source_text)
    registry = []
    for asset in source.get("assets", []):
        if not isinstance(asset, dict):
            continue
        media_type = str(asset.get("media_type", ""))
        if media_type not in counters:
            continue
        counters[media_type] += 1
        asset_id = str(asset.get("asset_id", ""))
        built_aliases = aliases.get(asset_id, []) + [
            _clip_text(asset.get("label"), 80),
            _clip_text(asset.get("original_filename"), 80),
        ]
        registry.append({
            "asset_id": asset_id,
            "official_label": f"<{names[media_type]} {counters[media_type]}>",
            "media_type": media_type,
            "aliases": list(dict.fromkeys(value for value in built_aliases if value)),
        })
    return registry


def _compact_entity(entity: dict[str, Any]) -> dict[str, Any]:
    attributes: dict[str, list[dict[str, Any]]] = {}
    feature_budget = 16
    for group, raw_features in (entity.get("attributes") or {}).items():
        if feature_budget <= 0:
            break
        if not isinstance(raw_features, list):
            continue
        features = []
        for feature in raw_features:
            if feature_budget <= 0:
                break
            if not isinstance(feature, dict):
                continue
            source = str(feature.get("source", ""))
            confidence = float(feature.get("confidence", 0.0) or 0.0)
            if source == "unresolved" or confidence < 0.45:
                continue
            features.append({
                "name": _clip_text(feature.get("name"), 100),
                "value": _clip_text(feature.get("value"), 180),
                "confidence": confidence,
                "source": source,
            })
            feature_budget -= 1
        if features:
            attributes[str(group)] = features
    return {
        "entity_id": entity.get("entity_id"),
        "category": _clip_text(entity.get("category"), 80),
        "subcategory": _clip_text(entity.get("subcategory"), 80),
        "summary": _clip_text(entity.get("summary"), 260),
        "quantity": entity.get("quantity", {}),
        "attributes": attributes,
        "uncertainties": [_clip_text(value, 180) for value in entity.get("uncertainties", [])[:4]],
    }


def _compact_final_editor_source(source: dict[str, Any]) -> dict[str, Any]:
    """Keep final-editor evidence useful without resending the full perception tree."""
    assets = []
    analyses = {
        str(item.get("asset_id", "")): item
        for item in (source.get("perception") or {}).get("assets", [])
        if isinstance(item, dict)
    }
    for asset in source.get("assets", []):
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("asset_id", ""))
        analysis = analyses.get(asset_id, {})
        entities = [
            _compact_entity(entity)
            for entity in analysis.get("entities", [])
            if isinstance(entity, dict)
        ]
        events = []
        for event in analysis.get("events", []):
            if not isinstance(event, dict):
                continue
            events.append({
                "event_id": event.get("event_id"),
                "time_range": event.get("time_range", []),
                "entity_ids": event.get("entity_ids", []),
                "action": _clip_text(event.get("action"), 320),
                "transition_type": _clip_text(event.get("transition_type"), 80),
                "confidence": event.get("confidence", 0.0),
            })
        relations = []
        for relation in analysis.get("relations", []):
            if not isinstance(relation, dict):
                continue
            relations.append({
                "relation_id": relation.get("relation_id"), "type": relation.get("type"),
                "subject_id": relation.get("subject_id"), "object_id": relation.get("object_id"),
                "anchor": _clip_text(relation.get("anchor"), 180),
                "confidence": relation.get("confidence", 0.0), "source": relation.get("source"),
            })
        global_analysis = analysis.get("global_analysis", {})
        if not isinstance(global_analysis, dict):
            global_analysis = {}
        technical = analysis.get("technical", {})
        if not isinstance(technical, dict):
            technical = {}
        assets.append({
            "asset_id": asset_id, "media_type": asset.get("media_type"),
            "label": asset.get("label"), "user_role": asset.get("user_role"),
            "summary": _clip_text(analysis.get("summary", ""), 500),
            "global_analysis": {
                "scene": _clip_text(global_analysis.get("scene"), 260),
                "composition": _clip_text(global_analysis.get("composition"), 320),
                "framing_layers": global_analysis.get("framing_layers", [])[:4],
                "visible_text": global_analysis.get("visible_text", [])[:8],
            },
            "entities": entities,
            "relations": relations,
            "events": events,
            "technical": {
                "duration_seconds": technical.get("duration_seconds"),
                "camera": technical.get("camera"),
                "framing": technical.get("framing"),
                "scene_cut_candidates_seconds": technical.get("scene_cut_candidates_seconds", []),
                "analysis_status": technical.get("analysis_status", "observed"),
                "quality_warnings": technical.get("quality_warnings", []),
            },
            "evidence_coverage": analysis.get("evidence_coverage", [])[:12],
            "uncertainties": [_clip_text(value, 220) for value in analysis.get("uncertainties", [])[:8]],
        })
    return {
        "user_request": source.get("user_request", ""),
        "resolved_request": source.get("resolved_request", ""),
        "task": source.get("task", {}), "directives": source.get("directives", []),
        "completion_policy": source.get("completion_policy", {}),
        "asset_mentions": source.get("asset_mentions", []),
        "reference_registry": _reference_registry(source),
        "assets": assets,
    }


def build_final_optimization_prompt(
    source: dict[str, Any],
    draft_ir: dict[str, Any],
    draft_prompt: str,
    preparation_note: str = "",
    semantic_warnings: list[dict[str, Any]] | None = None,
) -> str:
    semantic_draft = {
        key: value
        for key, value in draft_ir.items()
        if key not in {"task", "assets", "perception", "runtime"}
    }
    return f"""
Act as a constrained MiniMax H3 Prompt compiler. The canonical Context-IR below
is already approved and is immutable. Improve only the surface realization of
the supplied draft instead of returning a pass/fail verdict. Author the final
H3 Prompt directly; do not rewrite or return Context-IR.

The official h3-prompt-writing and h3-shot-planning Skills are authoritative for
format, reference labels, shot purpose, camera movement, cuts, timing, and
continuity. This is the final optimization turn; do not call tools, inspect files,
or ask questions.

Advisory semantic warnings are supplied below. They are not permission to alter
the locked semantics. Judge each warning in context: when it is a real surface
wording conflict, repair the wording without changing the Shot, event order,
asset authority, or timing; when it is a false positive, leave the authorized
meaning intact. Report the disposition of every warning in warning_resolutions.

Locked semantic boundary:
- Do not add, remove, merge, split, reorder, or retime shots.
- Do not add, remove, reorder, retime, or semantically rewrite
  performance_plan beats or keyframe_roles. These two compiler outputs are as
  immutable as the Shot timeline.
- Do not change subject priority, identities, products, asset roles, bindings,
  preservation scope, edit scope, state transitions, text policy, audio choice,
  or any explicit user requirement or prohibition.
- Do not introduce a new action, entity, product claim, title, name, dialogue,
  visible text, scene, effect, or camera event that is absent from Context-IR.
- If wording in the draft conflicts with Context-IR, Context-IR wins. If a
  desired semantic improvement would require changing Context-IR, leave the
  semantics unchanged and mention it only in optimization_notes.

Allowed realization work:
- Preserve every explicit user requirement, prohibition, directive, authoritative
  asset role, subject identity, product fact, exact supported text, duration,
  aspect ratio, and audio choice.
- Resolve camera contradictions, including static framing combined with handheld,
  pan, push, track, zoom, or reframing. Choose one executable interpretation.
- Give every existing shot a distinct, compact expression without changing its
  purpose, action, viewpoint, timing, or end state.
- Respect explicitly requested fast cuts or long takes. Do not reduce pace merely
  to minimize shot count, and do not create cuts that add no new information.
- Share unchanged style, shake, grain, lighting and overlays only across the
  shots where Context-IR authorizes them. A shot-specific preservation or exact
  frame-anchor instruction takes precedence over a generic global treatment:
  do not extend a scene's grain, grading, motion or effects onto an independently
  preserved card, insert or reference frame. State that scope once, not per shot.
- For moving cameras, specify start framing, cue, path, restrained speed/amplitude,
  end framing, and newly revealed information. Use a locked camera only when it
  better serves the shot's function.
- Preserve physical state across cuts. Do not hide wearing, removal, attachment,
  activation, hand-off, appearance, disappearance, or completion inside a cut.
- Retain every supplied shot as a locked beat. Do not add a consequence or
  resolution that is not already represented in Context-IR.
- Keep the primary subject or product visually meaningful and allocate detail by
  creative importance rather than by number of references.
- Keep the final Prompt compact. Describe stable appearance and global production
  choices once, then write only shot-specific changes in each shot.
- Allocate information by section instead of serializing the internal schema:
  subject_definitions identifies reusable content and its source authority;
  summary states the task and dramatic progression, not a second binding list;
  retention_analysis states what is retained or transferred within that role;
  detailed_description carries the actual audiovisual execution. Do not repeat
  full source inventories or lists of prohibited inheritance in every section.
  A Picture used only as provenance needs no standalone definition or retention
  line. A concrete frame anchor does need one, but describe its composition
  once instead of duplicating the complete scene as both Subject and Picture.
  Every conditioned asset must remain traceable through these source citations.
  Keep Subject definitions normally 20-45 words and retention entries one short
  sentence. Follow the official 350-500-word guidance for generation-task
  detailed_description when feasible; preserve explicit details and complete
  dialogue even when they require more. This is not a truncation limit.
  State a shared transition or annotation cycle once and name its occurrence
  at subsequent boundaries; do not expand the same mechanics again at every
  cut. Retain a brief continuity reminder only where it prevents ambiguity.
- Treat reference_registry as immutable. Preserve every asset's media type and
  official label. A Picture must not become a motion, camera-rhythm, or music
  source; never cite evidence whose technical.analysis_status is
  invalid_placeholder.
- Preserve co-equal subjects as co-equal. Do not create a dominant model,
  supporting person, or product hierarchy unless the user explicitly requests it.
- In each Subject definition, cite every appearance source and state its distinct
  attribute authority (for example identity/face, outfit, or worn product).
  When several Pictures contribute to one Subject, never claim that more than
  one of them exclusively controls the Subject's entire appearance.
- For a reciprocal interaction, apply its authorized performance reference to
  all participating subjects unless the user explicitly scopes it to one. A
  schema anchor named primary_subject_id must never leak into h3_prompt as a
  dominance claim when semantic_plan.subject_priority.mode is co_equal.
- In minimal_edit mode, modify only semantic_plan.edit_scope.editable and keep
  every locked element unchanged. Do not add a new camera move, cut, subject,
  effect, text event, or visual environment outside that scope.
- When completion_policy.creative is false, do not invent titles, names, credits,
  brands, claims, dialogue, or exact on-screen copy. Omit unsupported exact text
  and record it as unresolved instead of fabricating a plausible value.
- For reference pacing, use validated video events and measured cut candidates.
  Never replace unavailable timing with uniformly divided shots while claiming
  strict replication.
- Treat validated Video event ranges as evidence for ordered action beats, not
  automatically as edit boundaries. Only scene-cut candidates, observed cut
  transitions, or explicit user shot instructions authorize additional H3
  content shots. Do not invent handheld coverage, reaction close-ups, cutaways,
  or end-state consequences that are absent from the user request and evidence.
- Realize each timeline[].beat_refs sequence inside its existing Shot in target
  time order. Do not expose internal beat IDs in the Prompt. Express each
  observed target action once; keep unresolved_tail explicitly unresolved and
  never convert it into a hold, loop, repeat, new ending, or extra Shot.
- Realize action_keyframe roles inside the relevant Subject definition as exact
  pose anchors at their mapped beat time. Realize appearance, scene, product
  detail, composition, and style Picture roles only within their authorized
  dimensions. Do not promote a Picture to motion or editorial authority.
- When story_continuation is false, observable_end_state must only restate the
  last explicit user-requested or visibly evidenced action/state. Physical
  plausibility is not evidence: repeated contact does not prove accumulated
  coverage, damage, depletion, completion, disappearance, or transformation.
  Do not turn a continuing action into an inferred result.
- An invalid_placeholder reference is still passed to H3 when the user requested
  it, but it provides no describable internal evidence. Do not invent its cut
  type, shot count, timing, camera path, transition, action, or music. Express
  the unresolved structural transfer as one full-duration timeline shot and let
  H3 consume the conditioned reference directly.

Official H3 output contract:
- For ref2va, h3_prompt contains exactly these six lowercase headings in order:
  subject_definitions, summary, retention_analysis, detailed_description,
  overall_soundscape, non_diegetic_music.
- Every actual human speaker needs a stable (S1), (S2), etc. beside the Subject
  label at the speech event, including a single-speaker scene. Bind any voice
  reference to that same speaker ID in subject_definitions. Speech replacement
  mixed with retained ambience is partially_copy, not fully_copy. Preserve
  exact user words; do not claim unobserved delivery comparisons with the source.
- Render audio as natural production directions, never Python lists or an
  internal audio_plan dump. Place synchronized Foley and complete authorized
  dialogue in detailed_description at the corresponding action; put continuous
  ambience and physical sound beds in overall_soundscape, and audience-only
  score in non_diegetic_music. Preserve the locked audio choices and silence.
  Before returning, reconcile audio_plan.sound_effects and every sync_rule with
  the shot prose: realize each already-planned cue at its specified action or
  boundary even if the draft text omitted it. A populated audio_plan is binding
  content, not optional background metadata. Moving a cue into its correct shot
  is realization, not a new semantic event. A global music or ambience paragraph
  cannot substitute for the planned focus click, contact, motor, transition,
  speech, or other synchronized cue. Shared cues may be defined once with an
  explicit scope covering every authorized occurrence. Preserve explicit silence
  and source-copy restrictions; do not create sounds absent from the locked IR.
  Use stable speaker IDs and the official <d>[Language] ...</d> notation for
  supplied dialogue. Do not repeat full speech in the two global sound sections.
  Preserve established target-time anchors for synchronized events: when the
  IR assigns a title reveal and hit to approximately 12 seconds, retain that
  approximate time together with their causal synchronization, not merely
  'around the midpoint'. Never make approximate timing falsely exact. Keep
  each designed sound's onset, stop, and any tail within the target duration;
  a final-frame hit cannot be followed by an audible tail beyond that frame.
- Preserve evidential certainty as well as meaning. A direction to retain
  existing source ambience does not authorize naming its unheard contents.
  Never turn 'any', 'if present', or an unresolved source-audio description into
  a confirmed sound. Keep source preservation generic; describe new sounds only
  when the locked IR explicitly authorizes generating those sounds.
- Start every content shot with exactly [Shot N]. Put its start time in prose as
  "At 00:SS.mmm," for shots after the first. Never write [0-3s], [Shot 1, 0-3s],
  title-case headings, or additional top-level headings.
- Use only labels present in reference_registry and sequential <Subject N> labels.
  Every conditioned reference must be described with its authorized scope.
- Source directives remain verbatim inside context_ir for traceability, but their
  meaning must be translated into English when projected into h3_prompt. Never
  copy a Chinese directive scope into Global constraints or another rewrite section
  unless it is verbatim visible scene text or tagged dialogue/lyrics.
- Timeline boundaries must be monotonic, non-overlapping, and consistent with all
  timing claims. Never call a camera static or locked in the same shot where it
  pans, tilts, tracks, pushes, zooms, or reframes.
- Give each shot exactly one camera execution. Never offer alternatives such as
  "handheld or tracking" or "static or push-in".
- A motion/performance reference alone does not authorize new cuts. Prefer one
  continuous shot for a continuous interaction unless the user or validated
  reference evidence requires a cut or viewpoint change.
- Keep camera rhythm, shot rhythm, and performance rhythm separate. A Video
  authorized only for actions, expressions, or performance timing must not
  contribute camera movement, cuts, transitions, shot count, or scene design.

Output one JSON object with exactly these top-level keys:
{{
  "h3_prompt": "the complete final official-format H3 Prompt as plain text",
  "optimization_notes": [
    {{"type": "concise_change_type", "location": "semantic path or shot id", "change": "what was improved", "reason": "why it improves execution or user intent"}}
  ],
  "warning_resolutions": [
    {{"code": "warning code", "path": "warning path", "status": "resolved|not_applicable|unresolved", "action": "what was changed or why no change was needed"}}
  ]
}}

Do not output Markdown fences, commentary, Context-IR, a score, passed, failed,
violations, or an audit report. Use only official
<Picture N>, <Video N>, <Audio N>, and <Subject N> labels in h3_prompt. Generated
rewrite descriptions are English except verbatim dialogue, lyrics, and visible
scene text. The h3_prompt must be ready to submit without programmatic rewriting.
Return at most five optimization_notes.

Advisory semantic warnings (an empty array means none):
{json.dumps(semantic_warnings or [], ensure_ascii=False, separators=(',', ':'))}

Authoritative source and compact media evidence:
{json.dumps(_compact_final_editor_source(source), ensure_ascii=False, separators=(',', ':'))}

Draft preparation note (empty means canonical preparation succeeded):
{preparation_note}

Canonical semantic draft:
{json.dumps(semantic_draft, ensure_ascii=False, separators=(',', ':'))}

Draft H3 Prompt for editing; do not copy defects blindly:
{draft_prompt}
""".strip()


def accept_final_optimization(
    optimized: dict[str, Any],
    draft_ir: dict[str, Any],
    semantic_warnings: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Accept a surface-level Prompt rewrite while keeping semantic IR locked."""
    prompt = optimized.get("h3_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("final optimizer must return a non-empty h3_prompt string")
    notes = optimized.get("optimization_notes", [])
    if not isinstance(notes, list):
        raise ValueError("final optimizer optimization_notes must be an array")
    warning_resolutions = optimized.get("warning_resolutions", [])
    if not isinstance(warning_resolutions, list):
        raise ValueError("final optimizer warning_resolutions must be an array")

    final_ir = copy.deepcopy(draft_ir)

    metadata = {
        "schema_version": "h3_llm_optimization.v1",
        "method": "llm_final_director",
        "programmatic_content_audit": False,
        "semantic_ir_locked": True,
        "ignored_context_ir_output": "context_ir" in optimized,
        "optimization_notes": copy.deepcopy(notes[:5]),
        "semantic_warnings_input": copy.deepcopy(semantic_warnings or []),
        "semantic_warning_resolutions": copy.deepcopy(warning_resolutions),
    }
    return final_ir, prompt.strip(), metadata


def _retry_log_path(log_path: Path, attempt: int) -> Path:
    return log_path if attempt == 0 else log_path.with_name(f"{log_path.stem}.retry{attempt}{log_path.suffix}")


def invoke_reasoning_json_with_retry(
    prompt: str,
    reasoning: dict[str, str],
    log_path: Path,
    skill_names: list[str] | None = None,
    retries: int = 1,
) -> dict[str, Any]:
    """Retry only malformed/truncated reasoning output, never content quality."""
    current_prompt = prompt
    last_error: Exception | None = None
    for attempt in range(max(0, retries) + 1):
        try:
            return invoke_reasoning_json(
                current_prompt,
                reasoning,
                _retry_log_path(log_path, attempt),
                skill_names,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            current_prompt = (
                prompt
                + "\n\nYour previous response could not be parsed as the required complete JSON object. "
                  "Retry from scratch, keep the semantic result compact, close every array and object, "
                  "and output JSON only. Parser error: "
                + _clip_text(exc, 500)
            )
    raise ValueError(f"reasoning model returned invalid JSON after retry: {last_error}")


def _run_final_director(
    source: dict[str, Any],
    draft_ir: dict[str, Any],
    draft_prompt: str,
    preparation_note: str,
    reasoning: dict[str, str],
    log_path: Path,
    semantic_warnings: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Run the director and one bounded contract-repair turn when necessary."""
    candidate_ir = draft_ir
    candidate_prompt = draft_prompt
    note = preparation_note
    last_report: dict[str, Any] | None = None
    for attempt in range(2):
        optimized = invoke_reasoning_json_with_retry(
            build_final_optimization_prompt(
                source,
                candidate_ir,
                candidate_prompt,
                note,
                semantic_warnings,
            ),
            reasoning,
            _retry_log_path(log_path, attempt),
            list(CORE_SKILLS),
            retries=1,
        )
        accepted_ir, accepted_prompt, metadata = accept_final_optimization(
            optimized,
            draft_ir,
            semantic_warnings,
        )
        compile_error = ""
        try:
            # ``draft_ir`` is already canonical.  Do not recompile it here:
            # even deterministic normalization can reorder derived lists and
            # would weaken the byte-for-byte semantic lock promised by this
            # stage.
            canonical_ir = copy.deepcopy(accepted_ir)
            ir_report = validate_context_ir(canonical_ir)
            if not ir_report.passed:
                raise ContextIRError(json.dumps(ir_report.to_dict(), ensure_ascii=False, indent=2))
            accepted_prompt = normalize_h3_prompt_transport(canonical_ir, accepted_prompt)
            contract = audit_h3_prompt_contract(canonical_ir, accepted_prompt)
            last_report = contract.to_dict()
        except ContextIRError as exc:
            canonical_ir = accepted_ir
            compile_error = str(exc)
            last_report = {
                "passed": False,
                "errors": [{
                    "code": "FINAL_CONTEXT_IR_INVALID",
                    "message": _clip_text(exc, 2000),
                    "path": "$.context_ir",
                    "severity": "error",
                }],
                "warnings": [],
            }
        if last_report.get("passed"):
            resolutions = metadata.get("semantic_warning_resolutions", [])
            resolved_keys = {
                (str(item.get("code", "")), str(item.get("path", "")))
                for item in resolutions
                if isinstance(item, dict)
                and item.get("status") in {"resolved", "not_applicable"}
            }
            contract_warning_codes = {
                str(item.get("code", ""))
                for item in last_report.get("warnings", [])
                if isinstance(item, dict)
            }
            prompt_warning_equivalents = {
                "SHOT_CAMERA_CONTRADICTION": "PROMPT_CAMERA_CONTRADICTION",
                "SHOT_CAMERA_ALTERNATIVE": "PROMPT_CAMERA_ALTERNATIVE",
            }
            unresolved_semantic_warnings = [
                copy.deepcopy(item)
                for item in (semantic_warnings or [])
                if (
                    (str(item.get("code", "")), str(item.get("path", "")))
                    not in resolved_keys
                    or prompt_warning_equivalents.get(str(item.get("code", "")))
                    in contract_warning_codes
                )
            ]
            metadata["unresolved_semantic_warnings"] = unresolved_semantic_warnings
            if unresolved_semantic_warnings:
                additional_warnings = [
                    item
                    for item in unresolved_semantic_warnings
                    if prompt_warning_equivalents.get(str(item.get("code", "")))
                    not in contract_warning_codes
                ]
                last_report["warnings"] = [
                    *last_report.get("warnings", []),
                    *additional_warnings,
                ]
            metadata["contract_validation"] = last_report
            metadata["repair_attempts"] = attempt
            return canonical_ir, accepted_prompt, metadata
        if attempt == 0:
            candidate_ir = draft_ir
            candidate_prompt = accepted_prompt
            note = (
                "The previous final response violated only deterministic Context-IR/H3 transport "
                "requirements. Preserve its valid creative decisions and repair every listed error. "
                "Do not add new content while repairing. Return the complete prompt using this exact "
                "six-section skeleton, with every colon present and no extra top-level section:\n"
                "subject_definitions:\n...\n\nsummary:\n...\n\nretention_analysis:\n...\n\n"
                "detailed_description:\n[Shot 1] ...\n[Shot 2] At 00:SS.mmm, ...\n\n"
                "overall_soundscape:\n...\n\nnon_diegetic_music:\n...\n"
                "Every content shot line must start with [Shot N]. Errors: "
                + json.dumps(last_report.get("errors", []), ensure_ascii=False)
                + (" Context compile error: " + compile_error if compile_error else "")
            )
    raise ContextIRError(json.dumps(last_report or {"passed": False}, ensure_ascii=False, indent=2))


def optimize_existing_context_ir(
    supplied_ir: dict[str, Any],
    log_path: Path,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Run only the LLM final-director stage for a caller-supplied Context-IR."""
    intent = supplied_ir.get("intent") if isinstance(supplied_ir.get("intent"), dict) else {}
    source = {
        "user_request": intent.get("user_request", ""),
        "resolved_request": intent.get("resolved_request", ""),
        "task": copy.deepcopy(supplied_ir.get("task", {})),
        "directives": copy.deepcopy(intent.get("directives", [])),
        "completion_policy": copy.deepcopy(intent.get("completion_policy", {})),
        "asset_mentions": copy.deepcopy(supplied_ir.get("asset_mentions", [])),
        "assets": copy.deepcopy(supplied_ir.get("assets", [])),
        "perception": copy.deepcopy(supplied_ir.get("perception")),
    }
    reasoning = reasoning_provider_config()
    api_key_env = reasoning["api_key_env"]
    if not os.environ.get(api_key_env):
        raise RuntimeError(f"Missing {reasoning['name']} API key environment variable: {api_key_env}")
    preflight_reasoning_provider(reasoning)
    canonical_ir = compile_context_ir(supplied_ir)
    semantic_report = validate_context_ir(canonical_ir)
    semantic_warnings = [
        item.to_dict()
        for item in semantic_report.issues
        if item.severity == "warning"
    ]
    preparation_note = ""
    draft_prompt = render_h3_prompt(canonical_ir)
    return _run_final_director(
        source,
        canonical_ir,
        draft_prompt,
        preparation_note,
        reasoning,
        log_path,
        semantic_warnings,
    )


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
        progress_callback("bindings")
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
        progress_callback("timeline")

    # Production generation now uses the same v19 one-response compiler as the
    # evaluated cases. Intent/perception above remain independently reusable.
    from backend.single_call_service import finish_single_call
    return finish_single_call(source, output_dir, reasoning, stage_timings,
                              run_started, progress_callback)

    skill_names = list(CORE_SKILLS)
    stage_started = time.perf_counter()
    model_output = invoke_reasoning_json_with_retry(
        build_prompt(source), reasoning, output_dir / "agent.log", skill_names, retries=1
    )
    finish_stage("semantic_agent", stage_started)

    # Canonicalize and lock semantics before Prompt realization.  If the
    # semantic planner produced an invalid graph, repair it here in the
    # semantic stage; the final Prompt compiler is never allowed to repair or
    # mutate Context-IR.
    stage_started = time.perf_counter()
    preparation_note = ""
    try:
        draft_ir = compile_context_ir(model_output, source)
        draft_prompt = render_h3_prompt(draft_ir)
    except ContextIRError as exc:
        preparation_note = _clip_text(exc, 3000)
        repair_candidate = model_output
        repair_error = preparation_note
        for repair_attempt in range(2):
            semantic_repair_prompt = f"""
You are a constrained Context-IR JSON repairer. Patch the supplied semantic
draft only enough to satisfy the deterministic compiler errors. Preserve the
authoritative request, every asset role, subject, shot purpose and event order;
do not add creative content. Return one complete replacement Context-IR JSON
object and no Markdown or commentary.

Hard repair rules:
- Do not return any field named by an error unchanged.
- POLICY_MODE_INVALID: production_policies and entity_constraints mode values
  must be exactly strict, disabled, reference, enhance, or auto. Select strict
  for an explicit specification, disabled for an explicit prohibition,
  reference for authorized reference preservation, enhance for authorized
  enhancement, and auto only when unspecified. Preserve existing constraints,
  events, prohibitions, and their scope; never discard them to pass validation.
  Text content belongs in constraints/events, not in the mode enum. The shot
  planner's adaptive mode is not a production policy mode.
- SHOT_CAMERA_CONTRADICTION: choose exactly one execution. If higher-priority
  user or verified reference evidence requires movement, remove all
  static/locked wording. If it requires a locked camera, remove pan, tilt,
  track, push, pull, zoom, orbit, handheld and reframe wording. "Static camera
  with slight pan/tilt" is always invalid.
- SHOT_INTERNAL_CUT: represent each cut as a separate timeline shot, or remove
  an unsupported internal cut while preserving the authorized event order.
- MOTION_REFERENCE_CUT_SCOPE_VIOLATION: collapse the complete interaction into
  one continuous full-duration shot. Keep every authorized action in order as
  performance beats inside that shot; do not convert beats into cuts.
- MOTION_REFERENCE_CAMERA_SCOPE_VIOLATION: replace the unsupported moving-camera
  instruction with one conservative locked framing that contains all required
  participants and actions. Do not inherit camera behavior from a motion-only
  reference.
- MOTION_REFERENCE_TRANSITION_SCOPE_VIOLATION: remove the unsupported cut or
  transition. Use continuous/no transition unless a hard user directive grants
  editorial authority.
- MOTION_REFERENCE_STORY_CONTINUATION_VIOLATION: set story_continuation=false.
  Remove end-state consequences and state changes not explicitly requested by
  the user or visibly supported by reference evidence. End on the last
  authorized action without inventing what happens afterward. Physical
  plausibility is not evidence: do not infer accumulated coverage, damage,
  depletion, completion, disappearance, or transformation from a repeated
  action. Rewrite observable_end_state as a direct restatement of the last
  authorized action.
- INVALID_REFERENCE_EVIDENCE_EVENT: remove the unsupported concrete policy
  event; retain only the user's generic request to follow the conditioned
  reference.
- UNSUPPORTED_UNIFORM_REFERENCE_TIMELINE: collapse assumed equal-duration cuts
  to one full-duration shot that requests generic structural transfer from the
  conditioned reference. Do not invent replacement cut times or types.
- Never modify task, asset IDs, source directives, or explicit prohibitions.

Authoritative compact source:
{json.dumps(_compact_final_editor_source(source), ensure_ascii=False, indent=2)}

Compiler errors:
{repair_error}

Semantic draft to repair:
{json.dumps(repair_candidate, ensure_ascii=False, indent=2)}
""".strip()
            repair_candidate = invoke_reasoning_json_with_retry(
                semantic_repair_prompt,
                reasoning,
                output_dir / f"agent.semantic_repair.{repair_attempt + 1}.log",
                None,
                retries=1,
            )
            try:
                draft_ir = compile_context_ir(repair_candidate, source)
                draft_prompt = render_h3_prompt(draft_ir)
                model_output = repair_candidate
                break
            except ContextIRError as repair_exc:
                repair_error = _clip_text(repair_exc, 3000)
        else:
            raise ContextIRError(repair_error)
    (output_dir / "context_ir_draft.json").write_text(
        json.dumps(draft_ir, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "h3_prompt_draft.txt").write_text(draft_prompt, encoding="utf-8")
    semantic_report = validate_context_ir(draft_ir)
    semantic_warnings = [
        item.to_dict()
        for item in semantic_report.issues
        if item.severity == "warning"
    ]
    finish_stage("draft_preparation", stage_started)

    if progress_callback:
        progress_callback("isolation")
    stage_started = time.perf_counter()
    ir, prompt, optimization_payload = _run_final_director(
        source,
        draft_ir,
        draft_prompt,
        preparation_note,
        reasoning,
        output_dir / "final_optimizer.log",
        semantic_warnings,
    )
    finish_stage("llm_final_optimizer", stage_started)

    stage_started = time.perf_counter()
    context_path = output_dir / "context_ir.json"
    context_path.write_text(json.dumps(ir, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if progress_callback:
        progress_callback("prompt")
    prompt_path = output_dir / "h3_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    optimization_path = output_dir / "llm_optimization.json"
    optimization_path.write_text(
        json.dumps(optimization_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Keep the legacy filename as a compatibility marker for existing clients.
    # Semantic IR is locked before realization; this marker distinguishes the
    # deterministic transport audit from a subjective programmatic score.
    audit_path = output_dir / "h3_prompt_audit.json"
    contract_validation = optimization_payload.get("contract_validation", {"passed": True, "errors": [], "warnings": []})
    audit_path.write_text(
        json.dumps({
            "schema_version": "h3_prompt_contract.v1",
            "enabled": True,
            "scope": "deterministic_transport_contract_only",
            "passed": bool(contract_validation.get("passed")),
            "errors": contract_validation.get("errors", []),
            "warnings": contract_validation.get("warnings", []),
            "semantic_warnings_input": optimization_payload.get("semantic_warnings_input", []),
            "semantic_warning_resolutions": optimization_payload.get("semantic_warning_resolutions", []),
            "unresolved_semantic_warnings": optimization_payload.get("unresolved_semantic_warnings", []),
            "subjective_content_score_enabled": False,
            "reason": "Semantic IR is locked before constrained LLM Prompt realization; only official format, reference, timing, and deterministic conflicts are checked.",
            "optimization_file": "llm_optimization.json",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    request = build_h3_request(ir, str(prompt_path), str(output_dir / "h3_outputs"))
    (output_dir / "h3_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finish_stage("final_serialization", stage_started)
    stage_timings["total_seconds"] = round(time.perf_counter() - run_started, 3)
    (output_dir / "stage_timings.json").write_text(
        json.dumps(stage_timings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": True, "output_dir": str(output_dir), "context_ir": str(context_path), "h3_prompt": str(prompt_path), "llm_optimization": str(optimization_path), "h3_prompt_audit": str(audit_path), "h3_request": str(output_dir / 'h3_request.json')}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex MiniMax-H3 Context-IR agent")
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
