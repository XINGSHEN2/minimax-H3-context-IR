#!/usr/bin/env python3
"""Provider-neutral Context-IR contract, validator, and H3 renderer."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


IR_SCHEMA_VERSION = "0.1.0"
MEDIA_ANALYSIS_SCHEMA_VERSION = "media_analysis.v1"
SUPPORTED_TASKS = {"t2va", "i2va", "fl2va", "l2va", "ref2va"}
SUPPORTED_MEDIA_TYPES = {"image", "video", "audio"}
SUPPORTED_BINDING_ROLES = {
    "identity", "outfit", "product", "motion", "voice", "music", "rhythm",
    "camera", "scene", "style", "first_frame", "last_frame",
}
SUPPORTED_PRIORITIES = {"hard", "soft"}
ASPECT_RATIO_PATTERN = re.compile(r"^(?:auto|[1-9]\d*:[1-9]\d*)$")
EPSILON = 1e-3
BASE_SECTIONS = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)
REF_SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)
INTERNAL_MEDIA_TERMS = re.compile(
    r"\b(contact[ -]?sheet|sampled? frames?|frame sampling|thumbnail grid)\b",
    re.IGNORECASE,
)
REFERENCE_TAG_PATTERN = re.compile(r"<(Picture|Video|Audio)\s+(\d+)>")
TIMESTAMP_PATTERN = re.compile(r"\b(\d{2}):(\d{2})\.(\d{3})\b")


class ContextIRError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = "$"
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(item.severity == "error" for item in self.issues)

    def add(self, code: str, message: str, path: str = "$", severity: str = "error") -> None:
        self.issues.append(ValidationIssue(code, message, path, severity))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": [item.to_dict() for item in self.issues if item.severity == "error"],
            "warnings": [item.to_dict() for item in self.issues if item.severity == "warning"],
        }


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_context_ir(payload: Mapping[str, Any]) -> ValidationReport:
    report = ValidationReport()
    if not isinstance(payload, Mapping):
        report.add("ROOT_INVALID", "Context-IR root must be an object")
        return report
    if payload.get("schema_version") != IR_SCHEMA_VERSION:
        report.add("SCHEMA_VERSION_UNSUPPORTED", f"schema_version must be {IR_SCHEMA_VERSION}", "$.schema_version")

    intent = payload.get("intent")
    if not isinstance(intent, Mapping) or not str(intent.get("user_request", "")).strip():
        report.add("INTENT_MISSING", "intent.user_request is required", "$.intent.user_request")

    task = payload.get("task")
    duration = None
    if not isinstance(task, Mapping):
        report.add("TASK_MISSING", "task must be an object", "$.task")
    else:
        if str(task.get("type", "")).lower() not in SUPPORTED_TASKS:
            report.add("TASK_TYPE_INVALID", f"task.type must be one of {sorted(SUPPORTED_TASKS)}", "$.task.type")
        if not _number(task.get("duration_seconds")):
            report.add("DURATION_INVALID", "duration_seconds must be numeric", "$.task.duration_seconds")
        else:
            duration = float(task["duration_seconds"])
            if not 4 <= duration <= 15:
                report.add("DURATION_OUT_OF_RANGE", "duration must be between 4 and 15 seconds", "$.task.duration_seconds")
        if not ASPECT_RATIO_PATTERN.match(str(task.get("aspect_ratio", ""))):
            report.add("ASPECT_RATIO_INVALID", "aspect_ratio must be auto or W:H", "$.task.aspect_ratio")
        if not isinstance(task.get("generate_audio"), bool):
            report.add("GENERATE_AUDIO_INVALID", "generate_audio must be boolean", "$.task.generate_audio")

    assets = payload.get("assets")
    if not isinstance(assets, list):
        report.add("ASSETS_INVALID", "assets must be an array", "$.assets")
        assets = []
    asset_ids: set[str] = set()
    for index, asset in enumerate(assets):
        path = f"$.assets[{index}]"
        if not isinstance(asset, Mapping):
            report.add("ASSET_INVALID", "asset must be an object", path)
            continue
        asset_id = str(asset.get("asset_id", "")).strip()
        if not asset_id:
            report.add("ASSET_ID_MISSING", "asset_id is required", path)
        elif asset_id in asset_ids:
            report.add("ASSET_ID_DUPLICATE", f"duplicate asset_id {asset_id}", path)
        asset_ids.add(asset_id)
        if asset.get("media_type") not in SUPPORTED_MEDIA_TYPES:
            report.add("MEDIA_TYPE_INVALID", "media_type must be image, video, or audio", path)
        if not str(asset.get("uri", "")).strip():
            report.add("ASSET_URI_MISSING", "asset uri is required", path)

    perception = payload.get("perception")
    if perception is not None:
        if not isinstance(perception, Mapping) or perception.get("schema_version") != MEDIA_ANALYSIS_SCHEMA_VERSION:
            report.add("PERCEPTION_INVALID", f"perception must use {MEDIA_ANALYSIS_SCHEMA_VERSION}", "$.perception")
        else:
            seen = set()
            for index, item in enumerate(perception.get("assets", [])):
                if not isinstance(item, Mapping) or item.get("asset_id") not in asset_ids:
                    report.add("PERCEPTION_ASSET_UNKNOWN", "perception references an unknown asset", f"$.perception.assets[{index}]")
                elif item.get("asset_id") in seen:
                    report.add("PERCEPTION_ASSET_DUPLICATE", "duplicate perception asset", f"$.perception.assets[{index}]")
                seen.add(item.get("asset_id"))

    bindings = payload.get("asset_bindings")
    if not isinstance(bindings, list):
        report.add("BINDINGS_INVALID", "asset_bindings must be an array", "$.asset_bindings")
        bindings = []
    binding_ids: set[str] = set()
    for index, binding in enumerate(bindings):
        path = f"$.asset_bindings[{index}]"
        if not isinstance(binding, Mapping):
            report.add("BINDING_INVALID", "binding must be an object", path)
            continue
        binding_id = str(binding.get("binding_id", "")).strip()
        if not binding_id or binding_id in binding_ids:
            report.add("BINDING_ID_INVALID", "binding_id must be present and unique", path)
        binding_ids.add(binding_id)
        if binding.get("asset_id") not in asset_ids:
            report.add("BINDING_ASSET_UNKNOWN", "binding references an unknown asset", path)
        if binding.get("role") not in SUPPORTED_BINDING_ROLES:
            report.add("BINDING_ROLE_INVALID", "unsupported binding role", path)
        if binding.get("priority") not in SUPPORTED_PRIORITIES:
            report.add("BINDING_PRIORITY_INVALID", "priority must be hard or soft", path)
        inherit, exclude = set(_strings(binding.get("inherit"))), set(_strings(binding.get("exclude")))
        if not inherit:
            report.add("BINDING_INHERIT_EMPTY", "inherit must explicitly name controlled attributes", path)
        if inherit & exclude:
            report.add("BINDING_PROPERTY_CONFLICT", f"both inherited and excluded: {sorted(inherit & exclude)}", path)
        role = binding.get("role")
        blocked_lower = {item.lower() for item in exclude}
        blocks_identity = any("identity" in item for item in blocked_lower)
        if role == "motion":
            required = {"identity", "outfit", "scene"}
            if not (blocks_identity and {"outfit", "scene"}.issubset(blocked_lower)):
                report.add(
                    "MOTION_ISOLATION_INCOMPLETE",
                    "motion references must exclude identity, outfit, and scene",
                    path,
                )
        if role == "style":
            required = {"identity", "product geometry", "logo"}
            blocks_product_geometry = any("product geometry" in item for item in blocked_lower)
            blocks_logo = any("logo" in item for item in blocked_lower)
            if not (blocks_identity and blocks_product_geometry and blocks_logo):
                report.add(
                    "STYLE_ISOLATION_INCOMPLETE",
                    "style references must exclude identity, product geometry, and logo",
                    path,
                )

    isolation = payload.get("isolation_rules")
    if not isinstance(isolation, list):
        report.add("ISOLATION_INVALID", "isolation_rules must be an array", "$.isolation_rules")
        isolation = []
    isolated: set[str] = set()
    for index, rule in enumerate(isolation):
        path = f"$.isolation_rules[{index}]"
        if not isinstance(rule, Mapping) or rule.get("binding_id") not in binding_ids:
            report.add("ISOLATION_BINDING_UNKNOWN", "isolation rule references an unknown binding", path)
            continue
        isolated.add(str(rule.get("binding_id")))
        allow, block = set(_strings(rule.get("allow"))), set(_strings(rule.get("block")))
        if not allow:
            report.add("ISOLATION_ALLOW_EMPTY", "allow must name controlled attributes", path)
        if allow & block:
            report.add("ISOLATION_CONFLICT", f"both allowed and blocked: {sorted(allow & block)}", path)
    for binding_id in sorted(binding_ids - isolated):
        report.add("ISOLATION_RULE_MISSING", f"missing isolation for {binding_id}", "$.isolation_rules")

    constraints = payload.get("constraints")
    if not isinstance(constraints, Mapping):
        report.add("CONSTRAINTS_MISSING", "constraints must be an object", "$.constraints")
    else:
        preserve = set(_strings(constraints.get("preserve")))
        mutable = set(_strings(constraints.get("allow_change")))
        prohibit = set(_strings(constraints.get("prohibit")))
        if preserve & mutable or preserve & prohibit:
            report.add("CONSTRAINT_CONFLICT", "preserve conflicts with allow_change or prohibit", "$.constraints")

    timeline = payload.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        report.add("TIMELINE_MISSING", "timeline must be non-empty", "$.timeline")
    else:
        expected = 0.0
        shot_ids = set()
        for index, shot in enumerate(timeline):
            path = f"$.timeline[{index}]"
            if not isinstance(shot, Mapping):
                report.add("SHOT_INVALID", "shot must be an object", path)
                continue
            shot_id = str(shot.get("shot_id", ""))
            if not shot_id or shot_id in shot_ids:
                report.add("SHOT_ID_INVALID", "shot_id must be present and unique", path)
            shot_ids.add(shot_id)
            start, end = shot.get("start_seconds"), shot.get("end_seconds")
            if not _number(start) or not _number(end):
                report.add("SHOT_TIME_INVALID", "shot times must be numeric", path)
                continue
            start, end = float(start), float(end)
            if abs(start - expected) > EPSILON:
                report.add("TIMELINE_GAP_OR_OVERLAP", f"expected {expected:g}, got {start:g}", path)
            if end <= start:
                report.add("SHOT_DURATION_INVALID", "end must follow start", path)
            expected = end
            if not str(shot.get("event", "")).strip():
                report.add("SHOT_EVENT_MISSING", "event is required", path)
            for asset_id in _strings(shot.get("asset_refs")):
                if asset_id not in asset_ids:
                    report.add("SHOT_ASSET_UNKNOWN", f"unknown asset {asset_id}", path)
            for binding_id in _strings(shot.get("binding_refs")):
                if binding_id not in binding_ids:
                    report.add("SHOT_BINDING_UNKNOWN", f"unknown binding {binding_id}", path)
        if duration is not None and abs(expected - duration) > EPSILON:
            report.add("TOTAL_DURATION_MISMATCH", f"timeline ends at {expected:g}, target {duration:g}", "$.timeline")

    audio = payload.get("audio_plan")
    if not isinstance(audio, Mapping):
        report.add("AUDIO_PLAN_MISSING", "audio_plan must be an object", "$.audio_plan")
    else:
        for key in ("voice", "music", "sound_effects", "ambient_sound", "sync_rules"):
            if key not in audio:
                report.add("AUDIO_FIELD_MISSING", f"audio_plan.{key} is required", "$.audio_plan")

    generation = payload.get("generation_description")
    if not isinstance(generation, Mapping):
        report.add("GENERATION_DESCRIPTION_MISSING", "generation_description must be an object", "$.generation_description")
    else:
        for key in ("cinematography", "lighting", "materials", "performance", "continuity"):
            if key not in generation:
                report.add("GENERATION_FIELD_MISSING", f"generation_description.{key} is required", "$.generation_description")
    return report


def normalize_reference_isolation(payload: dict[str, Any]) -> dict[str, Any]:
    """Add mandatory non-transfer attributes without changing creative intent."""
    required_blocks = {
        "motion": ("identity", "outfit", "scene"),
        "style": ("identity", "product geometry", "logo"),
    }
    rules = {
        str(rule.get("binding_id")): rule
        for rule in payload.get("isolation_rules", [])
        if isinstance(rule, dict) and rule.get("binding_id")
    }
    for binding in payload.get("asset_bindings", []):
        if not isinstance(binding, dict):
            continue
        required = required_blocks.get(str(binding.get("role")))
        if not required:
            continue
        excluded = binding.setdefault("exclude", [])
        if isinstance(excluded, list):
            for attribute in required:
                if attribute not in excluded:
                    excluded.append(attribute)
        rule = rules.get(str(binding.get("binding_id")))
        if rule is not None:
            blocked = rule.setdefault("block", [])
            if isinstance(blocked, list):
                for attribute in required:
                    if attribute not in blocked:
                        blocked.append(attribute)
    return payload


def compile_context_ir(model_output: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(model_output))
    payload.setdefault("schema_version", IR_SCHEMA_VERSION)
    payload.setdefault("runtime", {
        "perception_provider": {"provider": "local-qwen3-vl-32b", "model": "Qwen3-VL-32B-Instruct", "options": {}},
        "reasoning_provider": {"provider": "glm", "model": "GLM-5.2"},
        "generation_provider": {"provider": "minimax", "model": "MiniMax-H3"},
    })
    normalize_reference_isolation(payload)
    report = validate_context_ir(payload)
    if not report.passed:
        raise ContextIRError(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return payload


def _format_timestamp(seconds: float) -> str:
    total_ms = round(float(seconds) * 1000)
    minutes, remainder = divmod(total_ms, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _condition_assets(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    mode = str(payload["task"]["type"]).lower()
    if mode == "t2va":
        return []
    if mode == "ref2va":
        return list(payload["assets"])
    binding_roles: dict[str, set[str]] = {}
    for binding in payload["asset_bindings"]:
        binding_roles.setdefault(binding["asset_id"], set()).add(binding["role"])
    result = []
    for asset in payload["assets"]:
        roles = binding_roles.get(asset["asset_id"], set())
        if "first_frame" in roles or "last_frame" in roles or asset.get("frame_index") is not None:
            result.append(asset)
    return result


def build_reference_inventory(payload: Mapping[str, Any]) -> dict[str, str]:
    """Assign H3 labels from final condition order, independently by media type."""
    counters = {"image": 0, "video": 0, "audio": 0}
    names = {"image": "Picture", "video": "Video", "audio": "Audio"}
    inventory: dict[str, str] = {}
    for asset in _condition_assets(payload):
        media_type = str(asset["media_type"])
        counters[media_type] += 1
        inventory[str(asset["asset_id"])] = f"<{names[media_type]} {counters[media_type]}>"
    return inventory


def _shot_text(shot: Mapping[str, Any], shot_number: int) -> str:
    pieces = [str(shot["event"])]
    pieces.extend(
        f"{key}: {shot[key]}"
        for key in ("action", "camera", "lighting", "transition")
        if shot.get(key)
    )
    prefix = f"[Shot {shot_number}]"
    if shot_number != 1:
        prefix += f" At {_format_timestamp(float(shot['start_seconds']))},"
    return prefix + " " + "; ".join(pieces)


def _sound_sections(payload: Mapping[str, Any]) -> tuple[str, str]:
    audio = payload["audio_plan"]
    soundscape = "; ".join(
        f"{key}: {audio[key]}"
        for key in ("voice", "sound_effects", "ambient_sound", "sync_rules")
    )
    music = str(audio["music"]).strip()
    if not music or music.lower() in {"none", "no", "false", "not requested"}:
        music = "N/A"
    return soundscape, music


def _render_base_prompt(payload: Mapping[str, Any], inventory: Mapping[str, str]) -> str:
    task = payload["task"]
    mode = str(task["type"]).lower()
    duration = float(task["duration_seconds"])
    instruction = ""
    pictures = [
        inventory[asset["asset_id"]]
        for asset in _condition_assets(payload)
        if asset["media_type"] == "image"
    ]
    last_shot = len(payload["timeline"])
    if mode == "i2va":
        instruction = f"For the target video, at 0.00 seconds into the target video, {pictures[0]} (from [Shot 1]) is fully referenced."
    elif mode == "fl2va":
        instruction = (
            "How the reference pictures align with the target video — "
            f"{pictures[0]} (from [Shot 1]) aligns with the 0.00-second mark of the target video; "
            f"{pictures[-1]} (from [Shot {last_shot}]) aligns with the {duration:.2f}-second mark of the target video."
        )
    elif mode == "l2va":
        instruction = (
            "How the reference pictures align with the target video — "
            f"{pictures[-1]} (from [Shot {last_shot}]) aligns with the {duration:.2f}-second mark of the target video."
        )
    generation = payload["generation_description"]
    opening = "; ".join(
        f"{key}: {generation[key]}"
        for key in ("cinematography", "lighting", "materials", "performance", "continuity")
    )
    shots = [_shot_text(shot, index) for index, shot in enumerate(payload["timeline"], start=1)]
    description = opening + ". " + " ".join(shots)
    soundscape, music = _sound_sections(payload)
    core = "\n\n".join((
        "integrated_multimodal_description: " + description,
        "overall_soundscape: " + soundscape,
        "non_diegetic_music: " + music,
    ))
    return ((instruction + "\n\n") if instruction else "") + core + "\n"


def _render_ref_prompt(payload: Mapping[str, Any], inventory: Mapping[str, str]) -> str:
    report = validate_context_ir(payload)
    if not report.passed:
        raise ContextIRError(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    task = payload["task"]
    assets = {item["asset_id"]: item for item in payload["assets"]}
    rules = {item["binding_id"]: item for item in payload["isolation_rules"]}
    subjects = []
    retention = []
    for binding in payload["asset_bindings"]:
        asset = assets[binding["asset_id"]]
        target = binding.get("target") or binding["role"]
        label = inventory[binding["asset_id"]]
        inherited = ", ".join(binding["inherit"])
        blocked = ", ".join(rules[binding["binding_id"]].get("block", binding.get("exclude", []))) or "none"
        subjects.append(f"<{target}> is controlled by {label} for {inherited}.")
        mode = "fully_preserved" if binding["priority"] == "hard" else "reference"
        retention.append(f"<{target}>: {mode} - inherit {inherited}; do not inherit {blocked}.")
    intent = payload["intent"]
    summary = (
        f"[{task['type']}] Create a {task['duration_seconds']}s {task['aspect_ratio']} video. "
        f"{intent.get('resolved_request') or intent['user_request']}. Target style: {task.get('style', '')}. "
        f"Audio generation: {task['generate_audio']}."
    )
    details = []
    generation = payload["generation_description"]
    details.append("; ".join(f"{key}: {generation[key]}" for key in ("cinematography", "lighting", "materials", "performance", "continuity")))
    details.extend(_shot_text(shot, index) for index, shot in enumerate(payload["timeline"], start=1))
    soundscape, music = _sound_sections(payload)
    return "\n\n".join([
        "subject_definitions:\n" + "\n".join(subjects),
        "summary:\n" + summary,
        "retention_analysis:\n" + "\n".join(retention),
        "detailed_description:\n" + "\n".join(details),
        "overall_soundscape:\n" + soundscape,
        "non_diegetic_music:\n" + music,
    ]) + "\n"


def render_h3_prompt(payload: Mapping[str, Any]) -> str:
    report = validate_context_ir(payload)
    if not report.passed:
        raise ContextIRError(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    inventory = build_reference_inventory(payload)
    mode = str(payload["task"]["type"]).lower()
    if mode == "ref2va":
        return _render_ref_prompt(payload, inventory)
    return _render_base_prompt(payload, inventory)


def audit_h3_prompt(payload: Mapping[str, Any], prompt: str) -> ValidationReport:
    """Deterministically audit the final compiled prompt before H3 packaging."""
    report = ValidationReport()
    mode = str(payload["task"]["type"]).lower()
    required = REF_SECTIONS if mode == "ref2va" else BASE_SECTIONS
    positions = []
    for section in required:
        match = re.search(rf"(?m)^{re.escape(section)}:", prompt)
        if not match:
            report.add("PROMPT_SECTION_MISSING", f"missing section {section}", "$.h3_prompt")
        else:
            positions.append(match.start())
    if positions != sorted(positions):
        report.add("PROMPT_SECTION_ORDER", "prompt sections are out of order", "$.h3_prompt")
    forbidden = BASE_SECTIONS if mode == "ref2va" else REF_SECTIONS[:4]
    for section in forbidden:
        if section not in required and re.search(rf"(?m)^{re.escape(section)}:", prompt):
            report.add("PROMPT_SECTION_UNEXPECTED", f"unexpected section {section}", "$.h3_prompt")
    if "[Shot 1]" not in prompt:
        report.add("PROMPT_SHOT_ONE_MISSING", "[Shot 1] is required", "$.h3_prompt")
    if INTERNAL_MEDIA_TERMS.search(prompt):
        report.add("INTERNAL_MEDIA_LEAK", "internal sampled-frame terminology leaked into final prompt", "$.h3_prompt")
    duration = float(payload["task"]["duration_seconds"])
    for match in TIMESTAMP_PATTERN.finditer(prompt):
        seconds = int(match.group(1)) * 60 + int(match.group(2)) + int(match.group(3)) / 1000
        if seconds <= 0 or seconds >= duration + EPSILON:
            report.add("PROMPT_TIMESTAMP_RANGE", f"timestamp {match.group(0)} is outside the cut range", "$.h3_prompt")
    expected = set(build_reference_inventory(payload).values())
    actual = {f"<{kind} {number}>" for kind, number in REFERENCE_TAG_PATTERN.findall(prompt)}
    if actual - expected:
        report.add("REFERENCE_TAG_UNEXPECTED", f"unexpected reference tags: {sorted(actual - expected)}", "$.h3_prompt")
    if mode == "ref2va" and expected - actual:
        report.add("REFERENCE_TAG_MISSING", f"unused reference tags: {sorted(expected - actual)}", "$.h3_prompt")
    if mode in {"i2va", "fl2va", "l2va"}:
        pictures = {label for label in expected if label.startswith("<Picture ")}
        if pictures - actual:
            report.add("KEYFRAME_TAG_MISSING", f"missing keyframe tags: {sorted(pictures - actual)}", "$.h3_prompt")
    return report


def build_h3_request(payload: Mapping[str, Any], prompt_file: str, output_path: str) -> dict[str, Any]:
    task = payload["task"]
    mode = str(task["type"]).lower()
    if mode == "t2va":
        conditions = []
    elif mode == "ref2va":
        conditions = [
            {"type": asset.get("condition_type", asset["media_type"]), "uri": asset["uri"], "role": "reference"}
            for asset in payload["assets"]
        ]
    elif mode in {"i2va", "fl2va", "l2va"}:
        binding_roles = {}
        for binding in payload["asset_bindings"]:
            binding_roles.setdefault(binding["asset_id"], set()).add(binding["role"])
        conditions = []
        for asset in payload["assets"]:
            roles = binding_roles.get(asset["asset_id"], set())
            frame_index = 0 if "first_frame" in roles else -1 if "last_frame" in roles else asset.get("frame_index")
            if frame_index is None:
                continue
            conditions.append({"type": "image", "uri": asset["uri"], "role": "keyframe", "frame_index": frame_index})
    else:
        raise ContextIRError(f"unsupported task {mode}")
    return {
        "task": mode,
        "prompt_file": prompt_file,
        "conditions": conditions,
        "target": {"short_edge": 768, "aspect_ratio": task["aspect_ratio"], "duration_seconds": task["duration_seconds"]},
        "seed": 0,
        "n": 1,
        "num_inference_steps": 20,
        "output_mode": "decoded_files",
        "output_path": output_path,
    }
