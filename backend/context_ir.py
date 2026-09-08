#!/usr/bin/env python3
"""Provider-neutral Context-IR contract, validator, and H3 renderer."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from backend.directive_binding import compile_directive_bindings, derive_binding_graph


IR_SCHEMA_VERSION = "0.1.0"
MEDIA_ANALYSIS_SCHEMA_VERSION = "media_analysis.v2"
LEGACY_MEDIA_ANALYSIS_SCHEMA_VERSIONS = {"media_analysis.v1"}
SUPPORTED_TASKS = {"t2va", "i2va", "fl2va", "l2va", "ref2va"}
SUPPORTED_MEDIA_TYPES = {"image", "video", "audio"}
SUPPORTED_BINDING_ROLES = {
    "identity", "outfit", "product", "motion", "voice", "music", "rhythm",
    "camera", "scene", "style", "first_frame", "last_frame",
}
APPEARANCE_BINDING_ROLES = {"identity", "outfit", "product", "scene"}
STRUCTURAL_BINDING_ROLES = {"motion", "camera", "rhythm", "style"}
SUPPORTED_PRIORITIES = {"hard", "soft"}
POLICY_MODES = {"strict", "disabled", "reference", "enhance", "auto"}
POLICY_SOURCES = {
    "explicit_user", "explicit_prohibition", "reference_evidence",
    "edit_base_preservation", "user_soft_goal", "category_prior",
    "default_completion", "inferred", "derived_requirement",
}
SUPPORTED_KEYFRAME_ROLES = {
    "appearance_source", "scene_anchor", "action_keyframe", "product_detail",
    "first_frame", "last_frame", "composition_anchor", "style_reference",
}
KEYFRAME_ROLE_SOURCES = {
    "explicit_user", "reference_evidence", "derived_requirement",
}
PERFORMANCE_BEAT_STATUSES = {"observed", "user_overridden", "unresolved_tail"}
PERFORMANCE_ACTION_SOURCES = {
    "reference_evidence", "explicit_user", "derived_requirement", "unresolved",
}
PRODUCTION_POLICY_MODULES = (
    "camera", "editing", "motion", "performance", "composition",
    "lighting", "audio", "style", "effects", "text",
)
ENTITY_CONSTRAINT_MODULES = ("identity", "product", "continuity")
SOURCE_SCHEMA_VERSION = "context_request.v1"
LEGACY_SOURCE_SCHEMA_VERSIONS = {"resolved_request.v1"}
DIRECTIVE_OPERATIONS = {"preserve", "replace", "transfer", "may_change", "exclude"}
DIRECTIVE_PROVENANCE = {"explicit_user", "confirmed_by_upstream", "product_default", "ir_completion"}
SUPPORTED_SUBJECT_KINDS = {"person", "product", "animal", "object", "environment", "other"}
VISUAL_RETENTION_MODES = {"fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"}
AUDIO_RETENTION_MODES = {"fully_copy", "partially_copy", "reference", "weak_reference"}
REFERENCE_RELATIONSHIPS = {"source_video_edit", "reference_generation", "keyframe_completion", "video_continuation", "audio_reuse", "audio_reference"}
SUMMARY_TASK_TYPES = {"keyframe completion", "reference generation", "video editing", "video continuation", "audio reuse", "audio reference"}
RELATIONSHIP_TASK_TYPE = {"source_video_edit": "video editing", "reference_generation": "reference generation", "keyframe_completion": "keyframe completion", "video_continuation": "video continuation", "audio_reuse": "audio reuse", "audio_reference": "audio reference"}
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
SUBJECT_TAG_PATTERN = re.compile(r"<Subject\s+(\d+)>")
ANGLE_TAG_PATTERN = re.compile(r"<([^>]+)>")
TIMESTAMP_PATTERN = re.compile(r"\b(\d{2}):(\d{2})\.(\d{3})\b")
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
RAW_ASSET_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(?:image|video|audio)_\d+(?![A-Za-z0-9_])", re.IGNORECASE)
CAMERA_MOVE_PATTERN = re.compile(
    r"\b(?:camera\s+)?(?:pan(?:s|ning)?|tilt(?:s|ing)?|track(?:s|ing)?|"
    r"push(?:es|ing)?\s+in|pull(?:s|ing)?\s+(?:back|out)|zoom(?:s|ing)?|"
    r"arc(?:s|ing)?|orbit(?:s|ing)?|handheld|reframe(?:s|ing)?)\b",
    re.IGNORECASE,
)
INTERNAL_CUT_PATTERN = re.compile(
    r"\b(?:(?:quick|hard|smash|match|jump)\s+)?cut(?:s)?\s+"
    r"(?:to|back\s+to)\b",
    re.IGNORECASE,
)
EDITORIAL_AUTHORITY_PATTERN = re.compile(
    r"(?:\bcamera\b|\bshot(?:s)?\b|\bedit(?:ing|orial)?\b|\btransition(?:s)?\b|"
    r"\bcut(?:s|ting)?\b|\bcinematograph(?:y|ic)\b|\bshot\s+(?:rhythm|pacing)\b|"
    r"运镜|镜头(?:运动|节奏|切换|设计|结构)?|剪辑|转场|切镜)",
    re.IGNORECASE,
)
STORY_CONTINUATION_PATTERN = re.compile(
    r"(?:\bcontinue\b|\bcontinuation\b|\bextend\b|\bcomplete\s+the\s+story\b|"
    r"\bimprovise\b|续写|延续(?:剧情|故事)|补全(?:剧情|故事)|补充(?:剧情|故事)|自由发挥)",
    re.IGNORECASE,
)


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


def _motion_reference_without_editorial_authority(payload: Mapping[str, Any]) -> set[str]:
    """Return video IDs authorized for performance transfer but not shot design.

    Motion, expression, and performance rhythm do not implicitly authorize the
    reference video's camera, cuts, transitions, or a newly invented edit.  A
    video used as an edit base or appearance/scene source is excluded because
    its existing visual timeline may legitimately remain authoritative.
    """
    asset_media = {
        str(asset.get("asset_id", "")): str(asset.get("media_type", ""))
        for asset in payload.get("assets", [])
        if isinstance(asset, Mapping)
    }
    bindings = [
        binding for binding in payload.get("asset_bindings", [])
        if isinstance(binding, Mapping)
    ]
    motion_ids = {
        str(binding.get("asset_id", ""))
        for binding in bindings
        if asset_media.get(str(binding.get("asset_id", ""))) == "video"
        and str(binding.get("role", "")) == "motion"
        and str(binding.get("priority", "")) == "hard"
    }
    if not motion_ids:
        return set()

    edit_base_ids = {
        str(item.get("asset_id", ""))
        for item in payload.get("reference_relationships", [])
        if isinstance(item, Mapping) and item.get("relationship") == "source_video_edit"
    }
    appearance_or_scene_ids = {
        str(binding.get("asset_id", ""))
        for binding in bindings
        if str(binding.get("priority", "")) == "hard"
        and str(binding.get("role", "")) in {
            "identity", "outfit", "product", "scene", "first_frame", "last_frame"
        }
    }
    editorial_ids = {
        str(binding.get("asset_id", ""))
        for binding in bindings
        if str(binding.get("role", "")) == "camera"
        or (
            str(binding.get("role", "")) == "rhythm"
            and EDITORIAL_AUTHORITY_PATTERN.search(
                " ".join([
                    str(binding.get("target", "")),
                    *(_strings(binding.get("inherit"))),
                ])
            )
        )
    }
    directives = (
        payload.get("intent", {}).get("directives", [])
        if isinstance(payload.get("intent"), Mapping)
        else []
    )
    global_editorial_authority = False
    for directive in directives:
        if not isinstance(directive, Mapping) or directive.get("priority") != "hard":
            continue
        directive_text = " ".join([
            str(directive.get("target", "")),
            *(_strings(directive.get("scope"))),
        ])
        if not EDITORIAL_AUTHORITY_PATTERN.search(directive_text):
            continue
        asset_id = str(directive.get("asset_id", ""))
        if asset_id:
            editorial_ids.add(asset_id)
        else:
            global_editorial_authority = True
    if global_editorial_authority:
        editorial_ids.update(motion_ids)
    return motion_ids - edit_base_ids - appearance_or_scene_ids - editorial_ids


def _explicit_story_continuation_authority(payload: Mapping[str, Any]) -> bool:
    intent = payload.get("intent")
    if not isinstance(intent, Mapping):
        return False
    completion_policy = intent.get("completion_policy")
    if isinstance(completion_policy, Mapping) and completion_policy.get("creative") is True:
        return True
    for directive in intent.get("directives", []):
        if not isinstance(directive, Mapping) or directive.get("priority") != "hard":
            continue
        directive_text = " ".join([
            str(directive.get("target", "")),
            *(_strings(directive.get("scope"))),
        ])
        if STORY_CONTINUATION_PATTERN.search(directive_text):
            return True
    return False


def normalize_source_request(source: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize natural-language and legacy resolved requests into one contract."""
    payload = copy.deepcopy(dict(source))
    if payload.get("schema_version") in LEGACY_SOURCE_SCHEMA_VERSIONS:
        payload["schema_version"] = SOURCE_SCHEMA_VERSION
    payload.setdefault("schema_version", SOURCE_SCHEMA_VERSION)
    legacy_resolution = payload.pop("intent_resolution", None)
    if not isinstance(payload.get("directives"), list):
        payload["directives"] = []
    if isinstance(legacy_resolution, Mapping):
        if not payload["directives"]:
            payload["directives"] = copy.deepcopy(legacy_resolution.get("directives", []))
        if not str(payload.get("resolved_request", "")).strip():
            payload["resolved_request"] = str(legacy_resolution.get("summary", ""))
        legacy_questions = _strings(legacy_resolution.get("open_questions"))
        if legacy_questions:
            payload["open_questions"] = legacy_questions
    payload.setdefault("resolved_request", "")
    payload.setdefault("open_questions", [])
    policy = payload.get("completion_policy")
    if not isinstance(policy, dict):
        policy = {}
        payload["completion_policy"] = policy
    policy.setdefault("technical", True)
    policy.setdefault("conservative_semantic", True)
    policy.setdefault("creative", False)
    task = payload.get("task")
    if isinstance(task, dict):
        # H3 is an audio-capable video model. Silence is opt-in: callers that
        # explicitly set false keep that decision, while omitted audio intent
        # receives the same complete sound-design default as the official IR.
        task.setdefault("generate_audio", True)
    return payload


def validate_source_request(source: Mapping[str, Any]) -> ValidationReport:
    """Validate the upstream-to-IR contract before perception or LLM compilation."""
    report = ValidationReport()
    if not isinstance(source, Mapping):
        report.add("SOURCE_ROOT_INVALID", "source request must be an object")
        return report
    if source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        report.add("SOURCE_SCHEMA_UNSUPPORTED", f"schema_version must be {SOURCE_SCHEMA_VERSION}", "$.schema_version")
    if not str(source.get("user_request", "")).strip():
        report.add("SOURCE_USER_REQUEST_MISSING", "user_request is required", "$.user_request")
    assets = source.get("assets")
    if not isinstance(assets, list):
        report.add("SOURCE_ASSETS_INVALID", "assets must be an array", "$.assets")
        assets = []
    asset_ids = {
        str(item.get("asset_id", "")).strip()
        for item in assets
        if isinstance(item, Mapping) and str(item.get("asset_id", "")).strip()
    }
    directives = source.get("directives")
    if not isinstance(directives, list):
        report.add("DIRECTIVES_INVALID", "directives must be an array", "$.directives")
        directives = []
    directive_ids: set[str] = set()
    directives_by_id: dict[str, Mapping[str, Any]] = {}
    hard_controls: dict[tuple[str, str], tuple[str, str]] = {}
    for index, directive in enumerate(directives):
        path = f"$.directives[{index}]"
        if not isinstance(directive, Mapping):
            report.add("DIRECTIVE_INVALID", "directive must be an object", path)
            continue
        directive_id = str(directive.get("directive_id", "")).strip()
        if not directive_id or directive_id in directive_ids:
            report.add("DIRECTIVE_ID_INVALID", "directive_id must be present and unique", path)
        directive_ids.add(directive_id)
        asset_id = str(directive.get("asset_id", "")).strip()
        if asset_id and asset_id not in asset_ids:
            report.add("DIRECTIVE_ASSET_UNKNOWN", f"unknown directive asset {asset_id}", path)
        if directive.get("operation") not in DIRECTIVE_OPERATIONS:
            report.add("DIRECTIVE_OPERATION_INVALID", f"operation must use {sorted(DIRECTIVE_OPERATIONS)}", path)
        if directive.get("priority") not in SUPPORTED_PRIORITIES:
            report.add("DIRECTIVE_PRIORITY_INVALID", "priority must be hard or soft", path)
        if directive.get("provenance") not in DIRECTIVE_PROVENANCE:
            report.add("DIRECTIVE_PROVENANCE_INVALID", f"provenance must use {sorted(DIRECTIVE_PROVENANCE)}", path)
        if not str(directive.get("target", "")).strip():
            report.add("DIRECTIVE_TARGET_MISSING", "directive target is required", path)
        if not _strings(directive.get("scope")):
            report.add("DIRECTIVE_SCOPE_EMPTY", "directive scope must name controlled attributes", path)
        if directive.get("priority") == "hard":
            target = str(directive.get("target", "")).strip()
            operation = str(directive.get("operation", ""))
            for attribute in _strings(directive.get("scope")):
                key = (target, attribute.lower())
                previous = hard_controls.get(key)
                if previous and previous[0] != operation:
                    report.add(
                        "DIRECTIVE_CONFLICT",
                        f"hard directives {previous[1]} and {directive_id} apply conflicting operations to {target}.{attribute}",
                        path,
                    )
                else:
                    hard_controls[key] = (operation, directive_id)
    policy = source.get("completion_policy")
    if not isinstance(policy, Mapping):
        report.add("COMPLETION_POLICY_MISSING", "completion_policy is required", "$.completion_policy")
    else:
        for key in ("technical", "conservative_semantic", "creative"):
            if not isinstance(policy.get(key), bool):
                report.add("COMPLETION_POLICY_INVALID", f"completion_policy.{key} must be boolean", f"$.completion_policy.{key}")
    return report


def validate_context_ir(payload: Mapping[str, Any]) -> ValidationReport:
    report = ValidationReport()
    if not isinstance(payload, Mapping):
        report.add("ROOT_INVALID", "Context-IR root must be an object")
        return report
    if payload.get("schema_version") != IR_SCHEMA_VERSION:
        report.add("SCHEMA_VERSION_UNSUPPORTED", f"schema_version must be {IR_SCHEMA_VERSION}", "$.schema_version")

    intent = payload.get("intent")
    directive_ids: set[str] = set()
    if not isinstance(intent, Mapping) or not str(intent.get("user_request", "")).strip():
        report.add("INTENT_MISSING", "intent.user_request is required", "$.intent.user_request")
    if isinstance(intent, Mapping):
        if not isinstance(intent.get("directives", []), list):
            report.add("INTENT_DIRECTIVES_INVALID", "intent.directives must be an array", "$.intent.directives")
        directive_ids = {
            str(item.get("directive_id", "")).strip()
            for item in intent.get("directives", [])
            if isinstance(item, Mapping) and str(item.get("directive_id", "")).strip()
        }
        directives_by_id = {
            str(item.get("directive_id", "")).strip(): item
            for item in intent.get("directives", [])
            if isinstance(item, Mapping) and str(item.get("directive_id", "")).strip()
        }
        if directive_ids:
            policy = intent.get("completion_policy")
            if not isinstance(policy, Mapping):
                report.add("INTENT_COMPLETION_POLICY_MISSING", "Context-IR with directives must retain completion policy", "$.intent.completion_policy")

    protocol = payload.get("protocol")
    if not isinstance(protocol, Mapping):
        report.add("PROTOCOL_MISSING", "protocol must declare the official H3 rewrite language", "$.protocol")
    elif str(protocol.get("rewrite_language", "")).strip().lower() != "english":
        report.add("REWRITE_LANGUAGE_INVALID", "official H3 rewrite sections must use English", "$.protocol.rewrite_language")
    else:
        task_types = _strings(protocol.get("summary_task_types"))
        if not task_types or any(item not in SUMMARY_TASK_TYPES for item in task_types):
            report.add("SUMMARY_TASK_TYPES_INVALID", f"summary_task_types must use {sorted(SUMMARY_TASK_TYPES)}", "$.protocol.summary_task_types")

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
        perception_version = perception.get("schema_version") if isinstance(perception, Mapping) else None
        if not isinstance(perception, Mapping) or perception_version not in ({MEDIA_ANALYSIS_SCHEMA_VERSION} | LEGACY_MEDIA_ANALYSIS_SCHEMA_VERSIONS):
            report.add("PERCEPTION_INVALID", f"perception must use {MEDIA_ANALYSIS_SCHEMA_VERSION} (legacy v1 remains readable)", "$.perception")
        else:
            if perception_version in LEGACY_MEDIA_ANALYSIS_SCHEMA_VERSIONS:
                report.add("PERCEPTION_LEGACY", "media_analysis.v1 is deprecated; regenerate perception as v2 for field-level evidence", "$.perception", "warning")
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
    covered_directive_ids: set[str] = set()
    # Global directives are target-production constraints, not attributes
    # inherited from a particular asset. The lowering stage stores them once.
    global_constraints = payload.get("constraints", {})
    if not isinstance(global_constraints, Mapping):
        global_constraints = {}
    for directive_id in directive_ids:
        directive = directives_by_id[directive_id]
        if str(directive.get("asset_id", "")).strip():
            continue
        operation = directive.get("operation")
        destination = "prohibit" if operation == "exclude" else "allow_change" if operation == "may_change" else "preserve"
        missing = {item.casefold() for item in _strings(directive.get("scope"))} - {
            item.casefold() for item in _strings(global_constraints.get(destination))
        }
        if missing:
            report.add(
                "GLOBAL_DIRECTIVE_NOT_RETAINED",
                f"global directive {directive_id} is missing from constraints.{destination}: {sorted(missing)}",
                f"$.constraints.{destination}",
                severity="error" if directive.get("priority") == "hard" else "warning",
            )
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
        source_directive_ids = _strings(binding.get("source_directive_ids"))
        for directive_id in source_directive_ids:
            if directive_id not in directive_ids:
                report.add("BINDING_DIRECTIVE_UNKNOWN", f"binding references unknown directive {directive_id}", path)
            else:
                covered_directive_ids.add(directive_id)
                directive = directives_by_id[directive_id]
                directive_asset = str(directive.get("asset_id", "")).strip()
                if not directive_asset:
                    # A binding may cite a global directive as provenance;
                    # that does not turn global presentation into asset truth.
                    continue
                if directive_asset and directive_asset != str(binding.get("asset_id", "")):
                    report.add("BINDING_DIRECTIVE_ASSET_MISMATCH", f"binding asset does not implement directive {directive_id}'s asset", path)
                if directive.get("priority") == "hard" and binding.get("priority") != "hard":
                    report.add("HARD_DIRECTIVE_WEAKENED", f"hard directive {directive_id} must compile to a hard binding", path)
                if directive.get("operation") == "exclude":
                    missing = {item.lower() for item in _strings(directive.get("scope"))} - {
                        item.lower() for item in _strings(binding.get("exclude"))
                    }
                    if missing:
                        report.add("EXCLUDE_DIRECTIVE_NOT_ENFORCED", f"binding does not exclude directive scope: {sorted(missing)}", path)
                else:
                    missing = {item.lower() for item in _strings(directive.get("scope"))} - {
                        item.lower() for item in _strings(binding.get("inherit"))
                    }
                    if missing:
                        report.add("DIRECTIVE_SCOPE_NOT_INHERITED", f"binding does not inherit directive scope: {sorted(missing)}", path)
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
            blocks_product_geometry = any("product geometry" in item for item in blocked_lower)
            blocks_logo = any("logo" in item for item in blocked_lower)
            if not (blocks_identity and blocks_product_geometry and blocks_logo):
                report.add(
                    "STYLE_ISOLATION_INCOMPLETE",
                    "style references must exclude identity, product geometry, and logo",
                    path,
                )
    if directive_ids:
        for permission in payload.get("change_permissions", []):
            if not isinstance(permission, Mapping):
                continue
            directive_id = str(permission.get("directive_id", ""))
            directive = directives_by_id.get(directive_id, {})
            if (directive.get("operation") == "may_change"
                and permission.get("asset_id") == directive.get("asset_id")
                and permission.get("target") == directive.get("target")
                and _strings(permission.get("scope")) == _strings(directive.get("scope"))):
                covered_directive_ids.add(directive_id)
        binding_directive_ids = {
            directive_id for directive_id, directive in directives_by_id.items()
            if str(directive.get("asset_id", "")).strip()
        }
        missing_directives = binding_directive_ids - covered_directive_ids
        if missing_directives:
            report.add("DIRECTIVE_BINDING_COVERAGE", f"directives lack binding coverage: {sorted(missing_directives)}", "$.asset_bindings")

    subjects = payload.get("subjects")
    if not isinstance(subjects, list):
        report.add("SUBJECTS_INVALID", "subjects must be an array", "$.subjects")
        subjects = []
    subject_ids: set[str] = set()
    expected_subject_ids = [f"subject_{index}" for index in range(1, len(subjects) + 1)]
    actual_subject_ids: list[str] = []
    for index, subject in enumerate(subjects):
        path = f"$.subjects[{index}]"
        if not isinstance(subject, Mapping):
            report.add("SUBJECT_INVALID", "subject must be an object", path)
            continue
        subject_id = str(subject.get("subject_id", "")).strip()
        actual_subject_ids.append(subject_id)
        if not subject_id or subject_id in subject_ids:
            report.add("SUBJECT_ID_INVALID", "subject_id must be present and unique", path)
        subject_ids.add(subject_id)
        if subject.get("kind") not in SUPPORTED_SUBJECT_KINDS:
            report.add("SUBJECT_KIND_INVALID", f"subject kind must use {sorted(SUPPORTED_SUBJECT_KINDS)}", path)
        if not str(subject.get("name", "")).strip() or not str(subject.get("description", "")).strip():
            report.add("SUBJECT_DESCRIPTION_MISSING", "subject name and description are required", path)
        if not isinstance(subject.get("primary"), bool):
            report.add("SUBJECT_PRIMARY_INVALID", "subject.primary must be boolean", path)
        for asset_id in _strings(subject.get("source_asset_ids")):
            if asset_id not in asset_ids:
                report.add("SUBJECT_ASSET_UNKNOWN", f"unknown subject source asset {asset_id}", path)
        for binding_id in _strings(subject.get("binding_ids")):
            if binding_id not in binding_ids:
                report.add("SUBJECT_BINDING_UNKNOWN", f"unknown subject binding {binding_id}", path)
        subject_binding_assets = {
            str(binding.get("asset_id"))
            for binding in bindings
            if isinstance(binding, Mapping)
            and str(binding.get("binding_id")) in _strings(subject.get("binding_ids"))
        }
        unbound_sources = set(_strings(subject.get("source_asset_ids"))) - subject_binding_assets
        if unbound_sources:
            report.add("SUBJECT_SOURCE_WITHOUT_BINDING", f"subject sources lack scoped bindings: {sorted(unbound_sources)}", path)
        if subject.get("retention_mode") not in VISUAL_RETENTION_MODES:
            report.add("SUBJECT_RETENTION_INVALID", "subject retention_mode must use an official visible-content marker", path)
        if not str(subject.get("retention_description", "")).strip():
            report.add("SUBJECT_RETENTION_DESCRIPTION_MISSING", "subject retention_description is required", path)
    if actual_subject_ids != expected_subject_ids:
        report.add("SUBJECT_ID_SEQUENCE", f"subjects must be ordered sequentially as {expected_subject_ids}", "$.subjects")

    relationships = payload.get("reference_relationships")
    if not isinstance(relationships, list):
        report.add("REFERENCE_RELATIONSHIPS_INVALID", "reference_relationships must be an array", "$.reference_relationships")
        relationships = []
    relationship_assets: set[str] = set()
    asset_media = {str(asset.get("asset_id")): str(asset.get("media_type")) for asset in assets if isinstance(asset, Mapping)}
    for index, relationship in enumerate(relationships):
        path = f"$.reference_relationships[{index}]"
        if not isinstance(relationship, Mapping):
            report.add("REFERENCE_RELATIONSHIP_INVALID", "reference relationship must be an object", path)
            continue
        asset_id = str(relationship.get("asset_id", ""))
        if asset_id not in asset_ids or asset_id in relationship_assets:
            report.add("REFERENCE_RELATIONSHIP_ASSET_INVALID", "each conditioned asset needs one unique relationship", path)
        relationship_assets.add(asset_id)
        if relationship.get("relationship") not in REFERENCE_RELATIONSHIPS:
            report.add("REFERENCE_RELATIONSHIP_TYPE_INVALID", f"relationship must use {sorted(REFERENCE_RELATIONSHIPS)}", path)
        for subject_id in _strings(relationship.get("subject_refs")):
            if subject_id not in subject_ids:
                report.add("REFERENCE_SUBJECT_UNKNOWN", f"unknown reference subject {subject_id}", path)
        allowed_modes = AUDIO_RETENTION_MODES if asset_media.get(asset_id) == "audio" else VISUAL_RETENTION_MODES
        if relationship.get("retention_mode") not in allowed_modes:
            report.add("REFERENCE_RETENTION_INVALID", f"retention_mode must use {sorted(allowed_modes)}", path)
        if not str(relationship.get("definition", "")).strip() or not str(relationship.get("retention_description", "")).strip():
            report.add("REFERENCE_DESCRIPTION_MISSING", "reference definition and retention_description are required", path)
    if str(task.get("type", "")).lower() == "ref2va" and relationship_assets != asset_ids:
        report.add("REFERENCE_RELATIONSHIP_COVERAGE", "Ref2VA requires one reference relationship per asset", "$.reference_relationships")
    if isinstance(protocol, Mapping) and relationships:
        declared_task_types = set(_strings(protocol.get("summary_task_types")))
        required_task_types = {RELATIONSHIP_TASK_TYPE[item["relationship"]] for item in relationships if isinstance(item, Mapping) and item.get("relationship") in RELATIONSHIP_TASK_TYPE}
        if declared_task_types != required_task_types:
            report.add("SUMMARY_TASK_RELATIONSHIP_MISMATCH", f"summary_task_types must exactly cover reference relationships: {sorted(required_task_types)}", "$.protocol.summary_task_types")

    creative_focus = payload.get("creative_focus")
    if not isinstance(creative_focus, Mapping):
        report.add("CREATIVE_FOCUS_MISSING", "creative_focus must identify the final visual objective", "$.creative_focus")
    else:
        if not str(creative_focus.get("primary_target", "")).strip():
            report.add("FOCUS_TARGET_MISSING", "creative_focus.primary_target is required", "$.creative_focus.primary_target")
        primary_asset_id = str(creative_focus.get("primary_asset_id", "")).strip()
        primary_subject_id = str(creative_focus.get("primary_subject_id", "")).strip()
        primary_binding_ids = _strings(creative_focus.get("primary_binding_ids"))
        supporting_asset_ids = _strings(creative_focus.get("supporting_asset_ids"))
        required_shot_ids = _strings(creative_focus.get("required_shot_ids"))
        if asset_ids and primary_asset_id not in asset_ids:
            report.add("FOCUS_ASSET_UNKNOWN", "creative_focus.primary_asset_id must reference an asset", "$.creative_focus.primary_asset_id")
        if asset_ids and not primary_binding_ids:
            report.add("FOCUS_BINDINGS_EMPTY", "creative_focus.primary_binding_ids must be non-empty when assets are supplied", "$.creative_focus.primary_binding_ids")
        if subjects and primary_subject_id not in subject_ids:
            report.add("FOCUS_SUBJECT_UNKNOWN", "creative_focus.primary_subject_id must reference a subject", "$.creative_focus.primary_subject_id")
        elif subjects:
            primary_flags = [item for item in subjects if isinstance(item, Mapping) and item.get("primary")]
            if len(primary_flags) != 1 or primary_flags[0].get("subject_id") != primary_subject_id:
                report.add("FOCUS_PRIMARY_SUBJECT_MISMATCH", "exactly one subject must be primary and match creative_focus", "$.subjects")
        for binding_id in primary_binding_ids:
            if binding_id not in binding_ids:
                report.add("FOCUS_BINDING_UNKNOWN", f"unknown focus binding {binding_id}", "$.creative_focus.primary_binding_ids")
        for asset_id in supporting_asset_ids:
            if asset_id not in asset_ids or asset_id == primary_asset_id:
                report.add("FOCUS_SUPPORT_INVALID", f"invalid supporting asset {asset_id}", "$.creative_focus.supporting_asset_ids")
        if not str(creative_focus.get("objective", "")).strip():
            report.add("FOCUS_OBJECTIVE_MISSING", "creative_focus.objective is required", "$.creative_focus.objective")
        if not _strings(creative_focus.get("presentation_requirements")):
            report.add("FOCUS_PRESENTATION_EMPTY", "creative_focus.presentation_requirements must be non-empty", "$.creative_focus.presentation_requirements")
        if not required_shot_ids:
            report.add("FOCUS_SHOTS_EMPTY", "creative_focus.required_shot_ids must be non-empty", "$.creative_focus.required_shot_ids")
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
            if not str(shot.get("primary_change", "")).strip():
                report.add("SHOT_PRIMARY_CHANGE_MISSING", "each shot needs exactly one primary visible change", path)
            if not str(shot.get("observable_end_state", "")).strip():
                report.add("SHOT_END_STATE_MISSING", "each shot needs an observable end state", path)
            camera_text = str(shot.get("camera", ""))
            locked_camera = re.search(
                r"\b(?:static|locked)(?:-off)?\b",
                camera_text,
                re.IGNORECASE,
            )
            camera_move = CAMERA_MOVE_PATTERN.search(camera_text)
            if locked_camera and camera_move:
                report.add(
                    "SHOT_CAMERA_CONTRADICTION",
                    "a semantic shot cannot combine locked/static camera wording with camera movement",
                    path + ".camera",
                    severity="warning",
                )
            execution_text = " ".join(
                str(shot.get(field, "")) for field in ("event", "action", "camera")
            )
            if INTERNAL_CUT_PATTERN.search(execution_text):
                report.add(
                    "SHOT_INTERNAL_CUT",
                    "an internal cut must be represented as a separate timeline shot",
                    path,
                    severity="warning",
                )
            state_changes = shot.get("state_changes", [])
            if not isinstance(state_changes, list):
                report.add("SHOT_STATE_CHANGES_INVALID", "state_changes must be an array", path)
                state_changes = []
            for change_index, change in enumerate(state_changes):
                change_path = f"{path}.state_changes[{change_index}]"
                if not isinstance(change, Mapping):
                    report.add("SHOT_STATE_CHANGE_INVALID", "state change must be an object", change_path)
                    continue
                if change.get("subject_id") not in subject_ids:
                    report.add("SHOT_STATE_SUBJECT_UNKNOWN", "state change references an unknown subject", change_path)
                for field_name in ("property", "from", "to"):
                    if not str(change.get(field_name, "")).strip():
                        report.add("SHOT_STATE_FIELD_MISSING", f"state change {field_name} is required", change_path)
            for asset_id in _strings(shot.get("asset_refs")):
                if asset_id not in asset_ids:
                    report.add("SHOT_ASSET_UNKNOWN", f"unknown asset {asset_id}", path)
            for binding_id in _strings(shot.get("binding_refs")):
                if binding_id not in binding_ids:
                    report.add("SHOT_BINDING_UNKNOWN", f"unknown binding {binding_id}", path)
            for subject_id in _strings(shot.get("subject_refs")):
                if subject_id not in subject_ids:
                    report.add("SHOT_SUBJECT_UNKNOWN", f"unknown subject {subject_id}", path)
        if duration is not None and abs(expected - duration) > EPSILON:
            report.add("TOTAL_DURATION_MISMATCH", f"timeline ends at {expected:g}, target {duration:g}", "$.timeline")
        if isinstance(creative_focus, Mapping):
            primary_binding_ids = set(_strings(creative_focus.get("primary_binding_ids")))
            required_shot_ids = set(_strings(creative_focus.get("required_shot_ids")))
            unknown_shots = required_shot_ids - shot_ids
            if unknown_shots:
                report.add("FOCUS_SHOT_UNKNOWN", f"unknown focus shots: {sorted(unknown_shots)}", "$.creative_focus.required_shot_ids")
            for index, shot in enumerate(timeline):
                if primary_binding_ids and str(shot.get("shot_id", "")) in required_shot_ids and not primary_binding_ids.intersection(_strings(shot.get("binding_refs"))):
                    report.add("FOCUS_BINDING_MISSING_FROM_SHOT", "required focus shot must reference a primary binding", f"$.timeline[{index}].binding_refs")
                if subjects and str(shot.get("shot_id", "")) in required_shot_ids and str(creative_focus.get("primary_subject_id", "")) not in _strings(shot.get("subject_refs")):
                    report.add("FOCUS_SUBJECT_MISSING_FROM_SHOT", "required focus shot must reference the primary subject", f"$.timeline[{index}].subject_refs")
        for subject in subjects:
            if not isinstance(subject, Mapping):
                continue
            declared = set(_strings(subject.get("appearance_shot_ids")))
            actual = {str(shot.get("shot_id", "")) for shot in timeline if subject.get("subject_id") in _strings(shot.get("subject_refs"))}
            if declared != actual:
                report.add("SUBJECT_APPEARANCE_MISMATCH", f"{subject.get('subject_id')} appearance_shot_ids must match timeline subject_refs", "$.subjects")

    _validate_keyframe_and_performance(payload, report)

    audio = payload.get("audio_plan")
    if not isinstance(audio, Mapping):
        report.add("AUDIO_PLAN_MISSING", "audio_plan must be an object", "$.audio_plan")
    else:
        for key in ("voice", "music", "sound_effects", "ambient_sound", "sync_rules"):
            if key not in audio:
                report.add("AUDIO_FIELD_MISSING", f"audio_plan.{key} is required", "$.audio_plan")
        if isinstance(task, Mapping) and task.get("generate_audio") is True:
            soundscape_values = [
                str(audio.get(key, "")).strip()
                for key in ("voice", "sound_effects", "ambient_sound")
            ]
            sync_rules = _strings(audio.get("sync_rules"))
            empty_values = {"", "none", "no", "false", "not requested", "n/a"}
            if not sync_rules and all(value.lower() in empty_values for value in soundscape_values):
                report.add(
                    "AUDIO_SOUNDSCAPE_EMPTY",
                    "audio-enabled output must define voice, sound effects, ambient sound, or synchronization rules",
                    "$.audio_plan",
                )
            if not sync_rules:
                report.add(
                    "AUDIO_SYNC_RULES_EMPTY",
                    "audio-enabled output must define at least one audio-visual synchronization or continuous-bed rule",
                    "$.audio_plan.sync_rules",
                )

    generation = payload.get("generation_description")
    if not isinstance(generation, Mapping):
        report.add("GENERATION_DESCRIPTION_MISSING", "generation_description must be an object", "$.generation_description")
    else:
        for key in ("cinematography", "lighting", "materials", "performance", "continuity"):
            if key not in generation:
                report.add("GENERATION_FIELD_MISSING", f"generation_description.{key} is required", "$.generation_description")
    _validate_policy_collection(payload, report)
    motion_only_video_ids = _motion_reference_without_editorial_authority(payload)
    if motion_only_video_ids:
        semantic_plan = payload.get("semantic_plan")
        completion_authority = (
            semantic_plan.get("completion_authority", {})
            if isinstance(semantic_plan, Mapping)
            else {}
        )
        if (
            isinstance(completion_authority, Mapping)
            and completion_authority.get("story_continuation") is True
            and not _explicit_story_continuation_authority(payload)
        ):
            report.add(
                "MOTION_REFERENCE_STORY_CONTINUATION_VIOLATION",
                "a motion/performance transfer does not authorize a new consequence or story continuation; stop at the last user-requested or evidenced action",
                "$.semantic_plan.completion_authority.story_continuation",
            )
        timeline_items = [
            shot for shot in payload.get("timeline", [])
            if isinstance(shot, Mapping)
        ]
        if len(timeline_items) > 1:
            report.add(
                "MOTION_REFERENCE_CUT_SCOPE_VIOLATION",
                "a motion/performance-only video reference does not authorize multiple content shots; preserve the interaction as one continuous full-duration shot unless an explicit camera/editing directive authorizes cuts",
                "$.timeline",
            )
        for index, shot in enumerate(timeline_items):
            camera_text = str(shot.get("camera", ""))
            if CAMERA_MOVE_PATTERN.search(camera_text):
                # Lexical matches also occur in prohibitions such as "no zoom".
                # Natural-language scope needs semantic review, not a hard gate.
                report.add(
                    "MOTION_REFERENCE_CAMERA_SCOPE_VIOLATION",
                    "camera vocabulary occurs in a motion-only reference plan; check whether it describes an actual unauthorized move or merely prohibits one",
                    f"$.timeline[{index}].camera",
                    severity="warning",
                )
            transition = str(shot.get("transition", "")).strip().casefold()
            if transition not in {"", "none", "continuous", "end", "no cut", "no transition"}:
                report.add(
                    "MOTION_REFERENCE_TRANSITION_SCOPE_VIOLATION",
                    "a motion/performance-only video reference does not authorize a new cut or transition",
                    f"$.timeline[{index}].transition",
                )
    perception = payload.get("perception")
    perception_assets = perception.get("assets", []) if isinstance(perception, Mapping) else []
    invalid_video_ids = {
        str(asset.get("asset_id", ""))
        for asset in perception_assets
        if isinstance(asset, Mapping)
        and str(asset.get("technical", {}).get("media_type", asset.get("media_type", ""))) == "video"
        and str(asset.get("technical", {}).get("analysis_status", "")) == "invalid_placeholder"
    }
    observed_video_ids = {
        str(asset.get("asset_id", ""))
        for asset in perception_assets
        if isinstance(asset, Mapping)
        and str(asset.get("technical", {}).get("media_type", asset.get("media_type", ""))) == "video"
        and str(asset.get("technical", {}).get("analysis_status", "")) in {"observed", "degraded"}
    }
    invalid_structural_reference = any(
        isinstance(binding, Mapping)
        and str(binding.get("asset_id", "")) in invalid_video_ids
        and str(binding.get("role", "")) in STRUCTURAL_BINDING_ROLES
        for binding in payload.get("asset_bindings", [])
    )
    if invalid_structural_reference and not observed_video_ids:
        for module in ("camera", "editing", "motion", "performance", "style"):
            policy = payload.get("production_policies", {}).get(module, {})
            for index, event in enumerate(policy.get("events", []) if isinstance(policy, Mapping) else []):
                if isinstance(event, Mapping) and event.get("source") == "reference_evidence":
                    report.add(
                        "INVALID_REFERENCE_EVIDENCE_EVENT",
                        "an invalid-placeholder video cannot support a concrete reference_evidence event",
                        f"$.production_policies.{module}.events[{index}]",
                    )
        timeline_items = payload.get("timeline", []) if isinstance(payload.get("timeline"), list) else []
        durations = [
            round(float(shot.get("end_seconds")) - float(shot.get("start_seconds")), 3)
            for shot in timeline_items
            if isinstance(shot, Mapping) and _number(shot.get("start_seconds")) and _number(shot.get("end_seconds"))
        ]
        uniform = len(durations) > 1 and max(durations) - min(durations) <= EPSILON
        request_text = str(payload.get("intent", {}).get("user_request", ""))
        explicit_uniform_timing = bool(re.search(
            r"(?:equal[ -]?duration|evenly\s+divid|均分|等时长|等长|"
            r"每(?:张|幅|镜|个镜头).{0,10}(?:秒|均分|等长)|"
            r"\d+(?:\.\d+)?\s*(?:秒|seconds?\b)|\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?)",
            request_text,
            re.IGNORECASE,
        ))
        if uniform and not explicit_uniform_timing:
            report.add(
                "UNSUPPORTED_UNIFORM_REFERENCE_TIMELINE",
                "do not replace unavailable reference timing with assumed equal-duration shots; use one unresolved structural-reference shot unless the user supplied exact timing",
                "$.timeline",
            )
    return report


def _validate_keyframe_and_performance(payload: Mapping[str, Any], report: ValidationReport) -> None:
    """Validate the orthogonal Picture-role, performance-beat, and Shot layers."""
    asset_media = {
        str(item.get("asset_id", "")): str(item.get("media_type", ""))
        for item in payload.get("assets", [])
        if isinstance(item, Mapping)
    }
    subject_ids = {
        str(item.get("subject_id", ""))
        for item in payload.get("subjects", [])
        if isinstance(item, Mapping)
    }
    shot_ids = {
        str(item.get("shot_id", ""))
        for item in payload.get("timeline", [])
        if isinstance(item, Mapping)
    }
    plan = payload.get("performance_plan")
    beat_ids: set[str] = set()
    beats: list[Mapping[str, Any]] = []
    mappings_by_asset: dict[str, Mapping[str, Any]] = {}
    perception_videos = _perception_video_index(payload)
    observed_event_ids = {
        asset_id: {str(event.get("event_id", "")) for event in _valid_video_events(analysis)}
        for asset_id, analysis in perception_videos.items()
    }
    if plan is not None:
        if not isinstance(plan, Mapping):
            report.add("PERFORMANCE_PLAN_INVALID", "performance_plan must be an object", "$.performance_plan")
        else:
            source_ids = _strings(plan.get("source_asset_ids"))
            for source_id in source_ids:
                if asset_media.get(source_id) != "video":
                    report.add("PERFORMANCE_PLAN_SOURCE_INVALID", f"{source_id} is not a Video", "$.performance_plan.source_asset_ids")
            mappings = plan.get("duration_mappings", [])
            if not isinstance(mappings, list):
                report.add("PERFORMANCE_PLAN_MAPPING_INVALID", "duration_mappings must be an array", "$.performance_plan.duration_mappings")
                mappings = []
            for index, mapping in enumerate(mappings):
                path = f"$.performance_plan.duration_mappings[{index}]"
                if not isinstance(mapping, Mapping):
                    report.add("PERFORMANCE_PLAN_MAPPING_INVALID", "duration mapping must be an object", path)
                    continue
                source_id = str(mapping.get("source_asset_id", ""))
                if source_id not in source_ids or source_id in mappings_by_asset:
                    report.add("PERFORMANCE_PLAN_MAPPING_SOURCE_INVALID", "each performance Video needs one unique duration mapping", path)
                mappings_by_asset[source_id] = mapping
                if mapping.get("mode") == "scale_to_target":
                    if not _number(mapping.get("source_duration")) or float(mapping.get("source_duration", 0)) <= 0:
                        report.add("PERFORMANCE_PLAN_SOURCE_DURATION_INVALID", "source_duration must be positive", path)
                    if not _number(mapping.get("target_duration")) or float(mapping.get("target_duration", 0)) <= 0:
                        report.add("PERFORMANCE_PLAN_TARGET_DURATION_INVALID", "target_duration must be positive", path)
                    if not _number(mapping.get("scale")) or float(mapping.get("scale", 0)) <= 0:
                        report.add("PERFORMANCE_PLAN_SCALE_INVALID", "scale must be positive", path)
            if set(source_ids) != set(mappings_by_asset):
                report.add("PERFORMANCE_PLAN_MAPPING_COVERAGE", "every performance Video must have a duration mapping", "$.performance_plan.duration_mappings")
            beats_value = plan.get("beats", [])
            if not isinstance(beats_value, list):
                report.add("PERFORMANCE_BEATS_INVALID", "beats must be an array", "$.performance_plan.beats")
                beats_value = []
            beats = [item for item in beats_value if isinstance(item, Mapping)]
            motion_only_ids = _motion_reference_without_editorial_authority(payload)
            for index, beat in enumerate(beats_value):
                path = f"$.performance_plan.beats[{index}]"
                if not isinstance(beat, Mapping):
                    report.add("PERFORMANCE_BEAT_INVALID", "performance beat must be an object", path)
                    continue
                beat_id = str(beat.get("beat_id", ""))
                if not beat_id or beat_id in beat_ids:
                    report.add("PERFORMANCE_BEAT_ID_INVALID", "beat_id must be present and unique", path)
                beat_ids.add(beat_id)
                source_id = str(beat.get("source_asset_id", ""))
                if source_id not in source_ids:
                    report.add("PERFORMANCE_BEAT_SOURCE_UNKNOWN", "beat must reference a declared performance Video", path)
                if beat.get("status") not in PERFORMANCE_BEAT_STATUSES:
                    report.add("PERFORMANCE_BEAT_STATUS_INVALID", f"status must use {sorted(PERFORMANCE_BEAT_STATUSES)}", path)
                if beat.get("action_source") not in PERFORMANCE_ACTION_SOURCES:
                    report.add("PERFORMANCE_BEAT_ACTION_SOURCE_INVALID", f"action_source must use {sorted(PERFORMANCE_ACTION_SOURCES)}", path)
                if not str(beat.get("action", "")).strip():
                    report.add("PERFORMANCE_BEAT_ACTION_MISSING", "action is required", path)
                source_event_id = str(beat.get("source_event_id", ""))
                if beat.get("status") != "unresolved_tail" and source_event_id not in observed_event_ids.get(source_id, set()):
                    report.add("PERFORMANCE_BEAT_EVENT_UNKNOWN", "observed beat must reference a real perception event", path + ".source_event_id")
                for field_name in ("source_range", "target_range"):
                    value = beat.get(field_name)
                    if (
                        not isinstance(value, list)
                        or len(value) != 2
                        or not all(_number(item) for item in value)
                        or float(value[0]) < 0
                        or float(value[1]) <= float(value[0])
                    ):
                        report.add("PERFORMANCE_BEAT_TIME_INVALID", f"{field_name} must be a positive [start, end] range", path + f".{field_name}")
                target_range = beat.get("target_range")
                duration = payload.get("task", {}).get("duration_seconds")
                if isinstance(target_range, list) and len(target_range) == 2 and all(_number(item) for item in target_range) and _number(duration):
                    if float(target_range[1]) > float(duration) + EPSILON:
                        report.add("PERFORMANCE_BEAT_TIME_OUT_OF_RANGE", "target beat exceeds target duration", path + ".target_range")
                source_range = beat.get("source_range")
                mapping = mappings_by_asset.get(source_id)
                if (
                    isinstance(mapping, Mapping)
                    and mapping.get("mode") == "scale_to_target"
                    and _number(mapping.get("scale"))
                    and isinstance(source_range, list) and len(source_range) == 2 and all(_number(item) for item in source_range)
                    and isinstance(target_range, list) and len(target_range) == 2 and all(_number(item) for item in target_range)
                ):
                    scale = float(mapping["scale"])
                    expected = [float(source_range[0]) * scale, float(source_range[1]) * scale]
                    if any(abs(float(actual) - value) > 0.01 for actual, value in zip(target_range, expected)):
                        report.add("PERFORMANCE_BEAT_TIME_MAPPING_MISMATCH", "target_range must be the deterministic source-to-target time mapping", path + ".target_range")
                for subject_id in _strings(beat.get("subject_refs")):
                    if subject_id not in subject_ids:
                        report.add("PERFORMANCE_BEAT_SUBJECT_UNKNOWN", f"unknown subject {subject_id}", path + ".subject_refs")
                if beat.get("editorial_boundary") is not False and not isinstance(beat.get("editorial_boundary"), bool):
                    report.add("PERFORMANCE_BEAT_EDITORIAL_INVALID", "editorial_boundary must be boolean", path + ".editorial_boundary")
                if beat.get("editorial_boundary") is True and source_id in motion_only_ids:
                    report.add("UNAUTHORIZED_EDITORIAL_BOUNDARY", "a performance-only Video cannot create a cut boundary", path + ".editorial_boundary")
            for source_id, mapping in mappings_by_asset.items():
                if mapping.get("mode") != "scale_to_target" or not _number(mapping.get("source_duration")):
                    continue
                source_duration = float(mapping["source_duration"])
                events = _valid_video_events(perception_videos.get(source_id, {}))
                observed_end = max((float(item["time_range"][1]) for item in events), default=0.0)
                if source_duration - observed_end <= max(EPSILON, 0.25):
                    continue
                tails = [
                    beat for beat in beats
                    if beat.get("source_asset_id") == source_id and beat.get("status") == "unresolved_tail"
                ]
                if len(tails) != 1:
                    report.add("PERFORMANCE_BEAT_COVERAGE_TAIL_MISSING", "unobserved source tail must have exactly one unresolved_tail beat", "$.performance_plan.beats")

    keyframe_roles = payload.get("keyframe_roles")
    role_ids: set[str] = set()
    if keyframe_roles is not None:
        if not isinstance(keyframe_roles, list):
            report.add("KEYFRAME_ROLES_INVALID", "keyframe_roles must be an array", "$.keyframe_roles")
            keyframe_roles = []
        assigned_images: set[str] = set()
        for index, item in enumerate(keyframe_roles):
            path = f"$.keyframe_roles[{index}]"
            if not isinstance(item, Mapping):
                report.add("KEYFRAME_ROLE_INVALID", "keyframe role must be an object", path)
                continue
            role_id = str(item.get("role_id", ""))
            if not role_id or role_id in role_ids:
                report.add("KEYFRAME_ROLE_ID_INVALID", "role_id must be present and unique", path)
            role_ids.add(role_id)
            asset_id = str(item.get("asset_id", ""))
            if asset_media.get(asset_id) != "image":
                report.add("KEYFRAME_ROLE_ASSET_INVALID", "keyframe role must reference a Picture", path + ".asset_id")
            else:
                assigned_images.add(asset_id)
            if item.get("role") not in SUPPORTED_KEYFRAME_ROLES:
                report.add("KEYFRAME_ROLE_TYPE_INVALID", f"role must use {sorted(SUPPORTED_KEYFRAME_ROLES)}", path + ".role")
            if item.get("source") not in KEYFRAME_ROLE_SOURCES:
                report.add("KEYFRAME_ROLE_SOURCE_INVALID", f"source must use {sorted(KEYFRAME_ROLE_SOURCES)}", path + ".source")
            if not _strings(item.get("controls")):
                report.add("KEYFRAME_ROLE_CONTROLS_EMPTY", "controls must state what the Picture contributes", path + ".controls")
            forbidden_controls = {"motion", "camera", "editing", "music", "performance rhythm"}
            if forbidden_controls.intersection(value.casefold() for value in _strings(item.get("controls"))):
                report.add("KEYFRAME_ROLE_SCOPE_INVALID", "a Picture cannot control motion, camera, editing, music, or performance rhythm", path + ".controls")
            for subject_id in _strings(item.get("subject_refs")):
                if subject_id not in subject_ids:
                    report.add("KEYFRAME_ROLE_SUBJECT_UNKNOWN", f"unknown subject {subject_id}", path + ".subject_refs")
            for shot_id in _strings(item.get("shot_refs")):
                if shot_id not in shot_ids:
                    report.add("KEYFRAME_ROLE_SHOT_UNKNOWN", f"unknown shot {shot_id}", path + ".shot_refs")
            refs = _strings(item.get("beat_refs"))
            for beat_id in refs:
                if beat_id not in beat_ids:
                    report.add("ACTION_KEYFRAME_BEAT_UNKNOWN", f"unknown beat {beat_id}", path + ".beat_refs")
            if item.get("role") == "action_keyframe" and not refs:
                report.add("ACTION_KEYFRAME_BEAT_REQUIRED", "action_keyframe must anchor at least one performance beat", path + ".beat_refs")
            role_shots = _strings(item.get("shot_refs"))
            ordered_shots = [
                str(shot.get("shot_id", ""))
                for shot in payload.get("timeline", [])
                if isinstance(shot, Mapping)
            ]
            if item.get("role") == "first_frame" and ordered_shots and role_shots != [ordered_shots[0]]:
                report.add("KEYFRAME_ROLE_FIRST_FRAME_SHOT_INVALID", "first_frame must anchor only the first Shot", path + ".shot_refs")
            if item.get("role") == "last_frame" and ordered_shots and role_shots != [ordered_shots[-1]]:
                report.add("KEYFRAME_ROLE_LAST_FRAME_SHOT_INVALID", "last_frame must anchor only the last Shot", path + ".shot_refs")
        conditioned_images = {
            str(asset.get("asset_id", ""))
            for asset in _condition_assets(payload)
            if asset.get("media_type") == "image"
        }
        for asset_id in sorted(conditioned_images - assigned_images):
            report.add("KEYFRAME_ROLE_COVERAGE", f"conditioned Picture {asset_id} has no explicit role", "$.keyframe_roles")

    if plan is not None and isinstance(plan, Mapping):
        assigned_beats: set[str] = set()
        for index, shot in enumerate(payload.get("timeline", [])):
            if not isinstance(shot, Mapping):
                continue
            for beat_id in _strings(shot.get("beat_refs")):
                if beat_id not in beat_ids:
                    report.add("TIMELINE_BEAT_UNKNOWN", f"unknown beat {beat_id}", f"$.timeline[{index}].beat_refs")
                else:
                    assigned_beats.add(beat_id)
        for beat_id in sorted(beat_ids - assigned_beats):
            report.add("PERFORMANCE_BEAT_UNASSIGNED", f"performance beat {beat_id} is not attached to a Shot", "$.performance_plan.beats")
        for index, beat in enumerate(beats):
            for role_id in _strings(beat.get("keyframe_refs")):
                if role_id not in role_ids:
                    report.add("PERFORMANCE_KEYFRAME_UNKNOWN", f"unknown keyframe role {role_id}", f"$.performance_plan.beats[{index}].keyframe_refs")


def _validate_policy_collection(payload: Mapping[str, Any], report: ValidationReport) -> None:
    """Audit module permissions after deterministic policy normalization."""
    shot_ids = {
        str(item.get("shot_id", "")) for item in payload.get("timeline", [])
        if isinstance(item, Mapping)
    }
    collections = (
        ("production_policies", PRODUCTION_POLICY_MODULES),
        ("entity_constraints", ENTITY_CONSTRAINT_MODULES),
    )
    for collection_name, modules in collections:
        collection = payload.get(collection_name)
        if not isinstance(collection, Mapping):
            report.add("POLICY_COLLECTION_MISSING", f"{collection_name} must be an object", f"$.{collection_name}")
            continue
        for module in modules:
            policy = collection.get(module)
            path = f"$.{collection_name}.{module}"
            if not isinstance(policy, Mapping):
                report.add("POLICY_MODULE_MISSING", f"{module} policy is required", path)
                continue
            if policy.get("mode") not in POLICY_MODES:
                report.add("POLICY_MODE_INVALID", f"mode must use {sorted(POLICY_MODES)}", path + ".mode")
            if policy.get("source") not in POLICY_SOURCES:
                report.add("POLICY_SOURCE_INVALID", f"source must use {sorted(POLICY_SOURCES)}", path + ".source")
            if policy.get("priority") not in SUPPORTED_PRIORITIES:
                report.add("POLICY_PRIORITY_INVALID", "priority must be hard or soft", path + ".priority")
            if not isinstance(policy.get("allow_new_events"), bool) or not isinstance(policy.get("preserve_reference"), bool):
                report.add("POLICY_PERMISSION_INVALID", "allow_new_events and preserve_reference must be boolean", path)
            events = policy.get("events")
            if not isinstance(events, list):
                report.add("POLICY_EVENTS_INVALID", "events must be an array", path + ".events")
                events = []
            if policy.get("mode") == "disabled" and (policy.get("allow_new_events") or events):
                report.add("POLICY_DISABLED_HAS_EVENTS", "disabled policy cannot allow or contain events", path)
            for index, event in enumerate(events):
                event_path = f"{path}.events[{index}]"
                if not isinstance(event, Mapping) or not str(event.get("description", "")).strip():
                    report.add("POLICY_EVENT_INVALID", "event must contain a description", event_path)
                    continue
                unknown = set(_strings(event.get("shot_refs"))) - shot_ids
                if unknown:
                    report.add("POLICY_EVENT_SHOT_UNKNOWN", f"unknown shot refs: {sorted(unknown)}", event_path + ".shot_refs")
                if policy.get("mode") == "reference" and event.get("source") not in {"explicit_user", "reference_evidence", "edit_base_preservation"}:
                    report.add("POLICY_REFERENCE_EVENT_UNGROUNDED", "reference-mode events require user or reference evidence", event_path + ".source")
    entities = payload.get("entity_constraints")
    if isinstance(entities, Mapping):
        for module in ENTITY_CONSTRAINT_MODULES:
            policy = entities.get(module)
            if isinstance(policy, Mapping) and (policy.get("mode") != "strict" or policy.get("priority") != "hard"):
                report.add("ENTITY_POLICY_NOT_STRICT", f"{module} must remain strict and hard", f"$.entity_constraints.{module}")


def normalize_reference_isolation(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply non-negotiable safety blocks after semantic model decisions."""
    required_blocks = {
        "motion": ("identity", "outfit", "product appearance", "product geometry", "scene", "visible text", "logo"),
        "camera": ("identity", "outfit", "product appearance", "product geometry", "scene", "visible text", "logo"),
        "rhythm": ("identity", "outfit", "product appearance", "product geometry", "scene", "visible text", "logo"),
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


def normalize_subject_source_bindings(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep subject sources only when a compatible appearance binding supports them."""
    compatible_roles = {
        "person": {"identity", "outfit", "product"},
        "product": {"product"},
        "environment": {"scene"},
        "animal": {"identity", "outfit"},
        "object": {"identity", "product", "scene"},
        "other": APPEARANCE_BINDING_ROLES,
    }
    bindings = {
        str(item.get("binding_id", "")): item
        for item in payload.get("asset_bindings", [])
        if isinstance(item, Mapping) and str(item.get("binding_id", "")).strip()
    }
    by_asset: dict[str, list[Mapping[str, Any]]] = {}
    for binding in bindings.values():
        if binding.get("role") in APPEARANCE_BINDING_ROLES:
            by_asset.setdefault(str(binding.get("asset_id", "")), []).append(binding)
    for subject in payload.get("subjects", []):
        if not isinstance(subject, dict):
            continue
        subject_kind = str(subject.get("kind", "other"))
        allowed_roles = compatible_roles.get(subject_kind, APPEARANCE_BINDING_ROLES)
        binding_ids = [value for value in _strings(subject.get("binding_ids")) if value in bindings]
        retained_sources: list[str] = []
        for asset_id in _strings(subject.get("source_asset_ids")):
            attached = [
                bindings[binding_id]
                for binding_id in binding_ids
                if bindings[binding_id].get("asset_id") == asset_id
                and bindings[binding_id].get("role") in allowed_roles
            ]
            if attached:
                retained_sources.append(asset_id)
                continue
            candidates = [
                binding
                for binding in by_asset.get(asset_id, [])
                if binding.get("role") in allowed_roles
            ]
            if len(candidates) == 1:
                candidate_id = str(candidates[0].get("binding_id"))
                if candidate_id not in binding_ids:
                    binding_ids.append(candidate_id)
                retained_sources.append(asset_id)
        subject["binding_ids"] = binding_ids
        subject["source_asset_ids"] = retained_sources
    return payload


def normalize_focus_shot_bindings(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach declared primary bindings to every declared creative-focus shot."""
    focus = payload.get("creative_focus")
    if not isinstance(focus, Mapping):
        return payload
    valid_binding_ids = {
        str(item.get("binding_id", ""))
        for item in payload.get("asset_bindings", [])
        if isinstance(item, Mapping) and str(item.get("binding_id", "")).strip()
    }
    primary_binding_ids = [
        value for value in _strings(focus.get("primary_binding_ids"))
        if value in valid_binding_ids
    ]
    required_shot_ids = set(_strings(focus.get("required_shot_ids")))
    for shot in payload.get("timeline", []):
        if not isinstance(shot, dict) or str(shot.get("shot_id", "")) not in required_shot_ids:
            continue
        refs = [value for value in _strings(shot.get("binding_refs")) if value in valid_binding_ids]
        for binding_id in primary_binding_ids:
            if binding_id not in refs:
                refs.append(binding_id)
        shot["binding_refs"] = refs
    return payload


def normalize_primary_subject(payload: dict[str, Any]) -> dict[str, Any]:
    """Make the declared creative-focus subject the only primary subject."""
    focus = payload.get("creative_focus")
    subjects = payload.get("subjects")
    if not isinstance(focus, Mapping) or not isinstance(subjects, list):
        return payload
    primary_subject_id = str(focus.get("primary_subject_id", "")).strip()
    valid_ids = {
        str(subject.get("subject_id", "")).strip()
        for subject in subjects if isinstance(subject, Mapping)
    }
    if primary_subject_id not in valid_ids:
        return payload
    for subject in subjects:
        if isinstance(subject, dict):
            subject["primary"] = str(subject.get("subject_id", "")).strip() == primary_subject_id
    return payload


def normalize_binding_isolation_conflicts(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve exact allow/block collisions in favor of the controlled property."""
    directives = {
        str(directive.get("directive_id", "")).strip(): directive
        for directive in payload.get("intent", {}).get("directives", [])
        if isinstance(directive, Mapping)
        and str(directive.get("directive_id", "")).strip()
    } if isinstance(payload.get("intent"), Mapping) else {}
    bindings = {
        str(binding.get("binding_id", "")): binding
        for binding in payload.get("asset_bindings", [])
        if isinstance(binding, dict) and str(binding.get("binding_id", "")).strip()
    }
    for binding in bindings.values():
        inherited = _strings(binding.get("inherit"))
        explicit_excluded = {
            scope.casefold()
            for directive_id in _strings(binding.get("source_directive_ids"))
            for directive in [directives.get(directive_id, {})]
            if directive.get("operation") == "exclude"
            for scope in _strings(directive.get("scope"))
        }
        inherited = [
            value for value in inherited
            if value.casefold() not in explicit_excluded
        ]
        if not inherited:
            inherited = [f"{binding.get('role', 'scene')} reference scope"]
        inherited_lower = {value.casefold() for value in inherited}
        binding["inherit"] = inherited
        binding["exclude"] = [
            value for value in _strings(binding.get("exclude"))
            if value.casefold() not in inherited_lower
            or value.casefold() in explicit_excluded
        ]
    for rule in payload.get("isolation_rules", []):
        if not isinstance(rule, dict):
            continue
        binding = bindings.get(str(rule.get("binding_id", "")))
        allowed = _strings(binding.get("inherit")) if binding else _strings(rule.get("allow"))
        allowed_lower = {value.casefold() for value in allowed}
        rule["allow"] = allowed
        rule["block"] = [
            value for value in _strings(rule.get("block"))
            if value.casefold() not in allowed_lower
        ]
    return payload


def normalize_timeline_boundaries(payload: dict[str, Any]) -> dict[str, Any]:
    """Repair only technical gaps/overlaps while preserving shot order and end beats."""
    timeline = payload.get("timeline")
    task = payload.get("task")
    if not isinstance(timeline, list) or not timeline or not isinstance(task, Mapping):
        return payload
    try:
        duration = float(task.get("duration_seconds"))
    except (TypeError, ValueError):
        return payload
    expected = 0.0
    total = len(timeline)
    for index, shot in enumerate(timeline):
        if not isinstance(shot, dict):
            continue
        shot["start_seconds"] = expected
        if index == total - 1:
            end = duration
        else:
            try:
                end = float(shot.get("end_seconds"))
            except (TypeError, ValueError):
                end = expected
            remaining_shots = total - index - 1
            if end <= expected or end >= duration:
                end = expected + (duration - expected) / (remaining_shots + 1)
        shot["end_seconds"] = end
        expected = end
    return payload


def normalize_unresolved_reference_timeline(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove false timing precision when structural video evidence is unusable.

    The conditioned video remains in the H3 request.  This fallback preserves
    the planned visible events and subject order but collapses unsupported,
    uniformly divided cuts into one full-duration instruction so H3 can consume
    the reference directly.
    """
    perception = payload.get("perception")
    perception_assets = perception.get("assets", []) if isinstance(perception, Mapping) else []
    invalid_video_ids = {
        str(asset.get("asset_id", ""))
        for asset in perception_assets
        if isinstance(asset, Mapping)
        and str(asset.get("technical", {}).get("media_type", asset.get("media_type", ""))) == "video"
        and str(asset.get("technical", {}).get("analysis_status", "")) == "invalid_placeholder"
    }
    observed_video = any(
        isinstance(asset, Mapping)
        and str(asset.get("technical", {}).get("media_type", asset.get("media_type", ""))) == "video"
        and str(asset.get("technical", {}).get("analysis_status", "")) in {"observed", "degraded"}
        for asset in perception_assets
    )
    structural_invalid = any(
        isinstance(binding, Mapping)
        and str(binding.get("asset_id", "")) in invalid_video_ids
        and str(binding.get("role", "")) in STRUCTURAL_BINDING_ROLES
        for binding in payload.get("asset_bindings", [])
    )
    timeline = payload.get("timeline")
    if not structural_invalid or observed_video or not isinstance(timeline, list) or len(timeline) <= 1:
        return payload
    durations = [
        round(float(shot.get("end_seconds")) - float(shot.get("start_seconds")), 3)
        for shot in timeline
        if isinstance(shot, Mapping) and _number(shot.get("start_seconds")) and _number(shot.get("end_seconds"))
    ]
    if len(durations) != len(timeline) or max(durations) - min(durations) > EPSILON:
        return payload
    request_text = str(payload.get("intent", {}).get("user_request", ""))
    if re.search(
        r"(?:equal[ -]?duration|evenly\s+divid|均分|等时长|等长|"
        r"每(?:张|幅|镜|个镜头).{0,10}(?:秒|均分|等长)|"
        r"\d+(?:\.\d+)?\s*(?:秒|seconds?\b)|\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?)",
        request_text,
        re.IGNORECASE,
    ):
        return payload

    def collect(field: str) -> list[str]:
        return list(dict.fromkeys(
            value
            for shot in timeline if isinstance(shot, Mapping)
            for value in _strings(shot.get(field))
        ))

    visible_beats = [
        str(shot.get("primary_change", "")).strip().rstrip(".")
        for shot in timeline if isinstance(shot, Mapping) and str(shot.get("primary_change", "")).strip()
    ]
    actions = [
        str(shot.get("action", "")).strip().rstrip(".")
        for shot in timeline if isinstance(shot, Mapping) and str(shot.get("action", "")).strip()
    ]
    last = next((shot for shot in reversed(timeline) if isinstance(shot, Mapping)), {})
    duration = float(payload.get("task", {}).get("duration_seconds", timeline[-1].get("end_seconds", 0.0)))
    merged = {
        "shot_id": "01",
        "start_seconds": 0.0,
        "end_seconds": duration,
        "primary_change": "The supplied visual subjects appear in their requested order while the conditioned video controls unresolved rhythm and transitions.",
        "event": "; then ".join(visible_beats),
        "action": "; then ".join(actions) or "Present the supplied subjects in their requested order.",
        "camera": "Follow the conditioned video directly for camera execution; no unverified camera path is asserted.",
        "lighting": str(next((shot.get("lighting") for shot in timeline if isinstance(shot, Mapping) and str(shot.get("lighting", "")).strip()), "")),
        "transition": "Follow the conditioned video directly; exact cut boundaries are unresolved.",
        "observable_end_state": str(last.get("observable_end_state", "The final supplied subject is visible.")),
        "state_changes": [
            dict(change)
            for shot in timeline if isinstance(shot, Mapping)
            for change in shot.get("state_changes", []) if isinstance(change, Mapping)
        ],
        "subject_refs": collect("subject_refs"),
        "binding_refs": collect("binding_refs"),
    }
    asset_refs = collect("asset_refs")
    if asset_refs:
        merged["asset_refs"] = asset_refs
    payload["timeline"] = [merged]
    focus = payload.get("creative_focus")
    if isinstance(focus, dict):
        focus["required_shot_ids"] = ["01"]
    intent = payload.get("intent")
    if isinstance(intent, dict):
        uncertainties = intent.setdefault("uncertainties", [])
        if isinstance(uncertainties, list):
            uncertainties[:] = [
                value for value in uncertainties
                if "equal-duration" not in str(value).casefold() and "equal duration" not in str(value).casefold()
            ]
            note = "Reference video analysis is unusable; concrete cut timing and transition types are not asserted, and H3 must consume the conditioned video directly."
            if note not in uncertainties:
                uncertainties.append(note)
    for module in ("camera", "editing", "motion", "performance", "style"):
        policy = payload.get("production_policies", {}).get(module)
        if isinstance(policy, dict):
            policy["events"] = [
                event for event in policy.get("events", [])
                if not isinstance(event, Mapping) or event.get("source") != "reference_evidence"
            ]
    return payload


def normalize_subject_appearance_shots(payload: dict[str, Any]) -> dict[str, Any]:
    """Derive the subject appearance index from executable timeline references."""
    timeline = payload.get("timeline")
    subjects = payload.get("subjects")
    if not isinstance(timeline, list) or not isinstance(subjects, list):
        return payload
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        subject_id = str(subject.get("subject_id", "")).strip()
        subject["appearance_shot_ids"] = [
            str(shot.get("shot_id", "")).strip()
            for shot in timeline
            if isinstance(shot, Mapping)
            and subject_id in _strings(shot.get("subject_refs"))
        ]
    return payload


def normalize_global_constraint_conflicts(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove exact model duplicates from lower-authority mutable/prohibit lists."""
    constraints = payload.get("constraints")
    if not isinstance(constraints, dict):
        return payload
    preserve = _strings(constraints.get("preserve"))
    preserve_lower = {value.casefold() for value in preserve}
    constraints["preserve"] = preserve
    constraints["allow_change"] = [
        value for value in _strings(constraints.get("allow_change"))
        if value.casefold() not in preserve_lower
    ]
    constraints["prohibit"] = [
        value for value in _strings(constraints.get("prohibit"))
        if value.casefold() not in preserve_lower
    ]
    return payload


def normalize_creative_focus_asset(payload: dict[str, Any]) -> dict[str, Any]:
    """Repair focus asset/bindings after non-asset model bindings are lowered."""
    focus = payload.get("creative_focus")
    if not isinstance(focus, dict):
        return payload
    asset_ids = [
        str(item.get("asset_id", "")).strip()
        for item in payload.get("assets", [])
        if isinstance(item, Mapping) and str(item.get("asset_id", "")).strip()
    ]
    if not asset_ids:
        return payload
    valid_bindings = [
        item for item in payload.get("asset_bindings", [])
        if isinstance(item, Mapping)
        and str(item.get("binding_id", "")).strip()
        and str(item.get("asset_id", "")).strip() in asset_ids
    ]
    valid_binding_ids = {str(item.get("binding_id", "")).strip() for item in valid_bindings}
    primary_binding_ids = {
        value for value in _strings(focus.get("primary_binding_ids"))
        if value in valid_binding_ids
    }
    candidates: list[tuple[int, str]] = []
    for binding in valid_bindings:
        binding_id = str(binding.get("binding_id", "")).strip()
        asset_id = str(binding.get("asset_id", "")).strip()
        if binding_id not in primary_binding_ids or asset_id not in asset_ids:
            continue
        # Product appearance is the most concrete generation anchor for a
        # person-plus-product composite subject. Other focus bindings remain
        # supporting evidence rather than being concatenated into a fake ID.
        priority = 0 if binding.get("role") == "product" else 1
        candidates.append((priority, asset_id))
    current_asset_id = str(focus.get("primary_asset_id", "")).strip()
    if current_asset_id in asset_ids:
        primary_asset_id = current_asset_id
    elif candidates:
        candidates.sort(key=lambda item: (item[0], asset_ids.index(item[1])))
        primary_asset_id = candidates[0][1]
    else:
        product_assets = [
            str(binding.get("asset_id", "")).strip()
            for binding in valid_bindings if binding.get("role") == "product"
        ]
        primary_asset_id = product_assets[0] if product_assets else asset_ids[0]
    if not candidates:
        candidates = [(2, asset_ids[0])]
    focus["primary_asset_id"] = primary_asset_id
    focus["supporting_asset_ids"] = [
        asset_id for asset_id in asset_ids if asset_id != primary_asset_id
    ]
    if not primary_binding_ids:
        # Generated identity/outfit bindings may intentionally have no source
        # asset and are removed by directive lowering. Anchor the final focus to
        # the most concrete remaining asset-backed binding, preferring the
        # selected product appearance instead of leaving the focus unverifiable.
        ranked = sorted(
            valid_bindings,
            key=lambda binding: (
                0 if str(binding.get("asset_id", "")) == primary_asset_id and binding.get("role") == "product" else
                1 if binding.get("role") == "product" else
                2 if str(binding.get("asset_id", "")) == primary_asset_id else 3,
                str(binding.get("binding_id", "")),
            ),
        )
        if ranked:
            primary_binding_ids = {str(ranked[0].get("binding_id", "")).strip()}
    focus["primary_binding_ids"] = [
        str(binding.get("binding_id", "")).strip()
        for binding in valid_bindings
        if str(binding.get("binding_id", "")).strip() in primary_binding_ids
    ]
    return payload


def normalize_timeline_state_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Upgrade legacy IR shots without inventing new semantic events."""
    for shot in payload.get("timeline", []):
        if not isinstance(shot, dict):
            continue
        event = str(shot.get("event", "")).strip()
        shot.setdefault("primary_change", event)
        shot.setdefault("observable_end_state", f"The described shot event is visibly complete: {event}" if event else "")
        shot.setdefault("state_changes", [])
    return payload


def normalize_reference_retention_modes(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize equivalent retention labels using the referenced media type."""
    media_types = {
        str(asset.get("asset_id")): str(asset.get("media_type"))
        for asset in payload.get("assets", [])
        if isinstance(asset, Mapping) and asset.get("asset_id")
    }
    visual_aliases = {
        "fully_copy": "fully_preserved",
        "partially_copy": "partially_preserved",
    }
    audio_aliases = {
        "fully_preserved": "fully_copy",
        "partially_preserved": "partially_copy",
    }
    for relationship in payload.get("reference_relationships", []):
        if not isinstance(relationship, dict):
            continue
        media_type = media_types.get(str(relationship.get("asset_id")))
        mode = str(relationship.get("retention_mode", ""))
        if media_type in {"image", "video"} and mode in visual_aliases:
            relationship["retention_mode"] = visual_aliases[mode]
        elif media_type == "audio" and mode in audio_aliases:
            relationship["retention_mode"] = audio_aliases[mode]
    return payload


def normalize_source_video_audio_relationship(payload: dict[str, Any]) -> dict[str, Any]:
    """Fold redundant audio reuse into the single required source-video relation."""
    relationships = payload.get("reference_relationships")
    if not isinstance(relationships, list):
        return payload
    by_asset: dict[str, int] = {}
    normalized: list[Any] = []
    changed = False
    for relationship in relationships:
        if not isinstance(relationship, dict):
            normalized.append(relationship)
            continue
        asset_id = str(relationship.get("asset_id", ""))
        existing_index = by_asset.get(asset_id)
        if existing_index is None:
            by_asset[asset_id] = len(normalized)
            normalized.append(relationship)
            continue
        existing = normalized[existing_index]
        if not isinstance(existing, dict):
            normalized.append(relationship)
            continue
        pair = {existing.get("relationship"), relationship.get("relationship")}
        if "source_video_edit" in pair and pair.intersection({"audio_reuse", "audio_reference"}):
            primary = existing if existing.get("relationship") == "source_video_edit" else relationship
            audio = relationship if primary is existing else existing
            primary["subject_refs"] = list(dict.fromkeys(
                _strings(primary.get("subject_refs")) + _strings(audio.get("subject_refs"))
            ))
            primary_description = str(primary.get("retention_description", "")).strip()
            audio_description = str(audio.get("retention_description", "")).strip()
            if audio_description and audio_description not in primary_description:
                primary["retention_description"] = (
                    primary_description.rstrip(".") + ". Audio retention: " + audio_description
                ).strip()
            normalized[existing_index] = primary
            changed = True
            continue
        normalized.append(relationship)
    if not changed:
        return payload
    payload["reference_relationships"] = normalized
    protocol = payload.get("protocol")
    if isinstance(protocol, dict):
        required = [
            RELATIONSHIP_TASK_TYPE[item["relationship"]]
            for item in normalized
            if isinstance(item, Mapping) and item.get("relationship") in RELATIONSHIP_TASK_TYPE
        ]
        required = list(dict.fromkeys(required))
        existing_types = _strings(protocol.get("summary_task_types"))
        protocol["summary_task_types"] = (
            [item for item in existing_types if item in required]
            + [item for item in required if item not in existing_types]
        )
    return payload


def _perception_video_index(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    perception = payload.get("perception")
    items = perception.get("assets", []) if isinstance(perception, Mapping) else []
    return {
        str(item.get("asset_id", "")): dict(item)
        for item in items
        if isinstance(item, Mapping)
        and str(item.get("technical", {}).get("media_type", item.get("media_type", ""))) == "video"
        and str(item.get("asset_id", ""))
    }


def _valid_video_events(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return timestamped observations only; never repair event semantics here."""
    result: list[dict[str, Any]] = []
    for item in analysis.get("events", []) if isinstance(analysis.get("events"), list) else []:
        if not isinstance(item, Mapping):
            continue
        time_range = item.get("time_range")
        if (
            not isinstance(time_range, list)
            or len(time_range) != 2
            or not all(_number(value) for value in time_range)
        ):
            continue
        start, end = float(time_range[0]), float(time_range[1])
        if start < 0 or end <= start:
            continue
        event_id = str(item.get("event_id", "")).strip()
        action = str(item.get("action", "")).strip()
        if not event_id or not action:
            continue
        result.append({**dict(item), "time_range": [start, end]})
    return sorted(result, key=lambda item: (item["time_range"][0], item["time_range"][1]))


def normalize_performance_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Compile observed Video events into performance beats, never into shots.

    The semantic model may replace an observed event's object-level meaning in
    ``action`` (for example sponge -> foam), but source timing and source action
    always come from perception.  This keeps semantic transfer flexible while
    making temporal provenance deterministic.
    """
    asset_media = {
        str(item.get("asset_id", "")): str(item.get("media_type", ""))
        for item in payload.get("assets", [])
        if isinstance(item, Mapping)
    }
    motion_video_ids = list(dict.fromkeys(
        str(binding.get("asset_id", ""))
        for binding in payload.get("asset_bindings", [])
        if isinstance(binding, Mapping)
        and binding.get("role") == "motion"
        and asset_media.get(str(binding.get("asset_id", ""))) == "video"
    ))
    candidate = payload.get("performance_plan")
    if not isinstance(candidate, Mapping):
        candidate = {}
    candidate_beats = [
        item for item in candidate.get("beats", [])
        if isinstance(item, Mapping)
    ] if isinstance(candidate.get("beats"), list) else []
    candidate_by_event = {
        (str(item.get("source_asset_id", "")), str(item.get("source_event_id", ""))): item
        for item in candidate_beats
        if str(item.get("source_asset_id", "")) and str(item.get("source_event_id", ""))
    }
    candidate_by_asset: dict[str, list[Mapping[str, Any]]] = {}
    for item in candidate_beats:
        candidate_by_asset.setdefault(str(item.get("source_asset_id", "")), []).append(item)

    requested_sources = [
        item for item in _strings(candidate.get("source_asset_ids"))
        if item in motion_video_ids
    ]
    source_ids = list(dict.fromkeys(requested_sources + motion_video_ids))
    perception = _perception_video_index(payload)
    target_duration = float(payload.get("task", {}).get("duration_seconds", 0.0) or 0.0)
    motion_only_ids = _motion_reference_without_editorial_authority(payload)
    normalized_beats: list[dict[str, Any]] = []
    duration_mappings: list[dict[str, Any]] = []

    for source_id in source_ids:
        analysis = perception.get(source_id, {})
        technical = analysis.get("technical", {}) if isinstance(analysis, Mapping) else {}
        events = _valid_video_events(analysis)
        source_duration_value = technical.get("duration_seconds") if isinstance(technical, Mapping) else None
        source_duration = float(source_duration_value) if _number(source_duration_value) else 0.0
        if source_duration <= 0 and events:
            source_duration = max(float(item["time_range"][1]) for item in events)
        scale = target_duration / source_duration if source_duration > 0 else None
        duration_mappings.append({
            "source_asset_id": source_id,
            "mode": "scale_to_target" if scale is not None else "unresolved",
            "source_duration": source_duration if source_duration > 0 else None,
            "target_duration": target_duration,
            "scale": round(scale, 8) if scale is not None else None,
        })
        positional = candidate_by_asset.get(source_id, [])
        for event_index, event in enumerate(events):
            event_id = str(event["event_id"])
            semantic = candidate_by_event.get((source_id, event_id))
            if semantic is None and event_index < len(positional):
                semantic = positional[event_index]
            source_range = [float(value) for value in event["time_range"]]
            target_range = [
                round(value * scale, 3) if scale is not None else 0.0
                for value in source_range
            ]
            source_action = str(event.get("action", "")).strip()
            action = str(semantic.get("action", "")).strip() if isinstance(semantic, Mapping) else ""
            if not action:
                # Source actions often name source-world props or performers.
                # Without a semantic Beat supplied by the reasoning model,
                # projecting that wording can contradict a requested content
                # replacement. Keep the source description as audit evidence
                # and render only the authorized abstract transfer.
                action = (
                    "Follow the observed action, expression, and performance "
                    "rhythm from the reference Video for this interval."
                )
            requested_action_source = (
                str(semantic.get("action_source", "")).strip()
                if isinstance(semantic, Mapping) else ""
            )
            action_source = requested_action_source if requested_action_source in PERFORMANCE_ACTION_SOURCES else (
                "reference_evidence" if action == source_action else
                "explicit_user" if isinstance(semantic, Mapping) else "derived_requirement"
            )
            status = "user_overridden" if isinstance(semantic, Mapping) and action != source_action else "observed"
            transition_type = str(event.get("transition_type", "")).casefold()
            editorial_boundary = (
                source_id not in motion_only_ids
                and transition_type in {"cut", "hard_cut", "jump_cut", "match_cut", "dissolve", "fade"}
            )
            normalized_beats.append({
                "beat_id": "",
                "source_asset_id": source_id,
                "source_event_id": event_id,
                "source_range": source_range,
                "target_range": target_range,
                "source_action": source_action,
                "action": action,
                "action_source": action_source,
                "subject_refs": list(dict.fromkeys(_strings(semantic.get("subject_refs")))) if isinstance(semantic, Mapping) else [],
                "keyframe_refs": [],
                "editorial_boundary": editorial_boundary,
                "status": status,
                "evidence_refs": [f"{source_id}.{event_id}"],
            })
        if source_duration > 0:
            observed_end = max((float(item["time_range"][1]) for item in events), default=0.0)
            if source_duration - observed_end > max(EPSILON, 0.25):
                normalized_beats.append({
                    "beat_id": "",
                    "source_asset_id": source_id,
                    "source_event_id": "",
                    "source_range": [observed_end, source_duration],
                    "target_range": [round(observed_end * scale, 3), target_duration] if scale is not None else [0.0, target_duration],
                    "source_action": "",
                    "action": "Reference performance is unresolved for this interval; do not loop, repeat, or invent a new action.",
                    "action_source": "unresolved",
                    "subject_refs": [],
                    "keyframe_refs": [],
                    "editorial_boundary": False,
                    "status": "unresolved_tail",
                    "evidence_refs": [],
                })

    for index, beat in enumerate(normalized_beats, start=1):
        beat["beat_id"] = f"beat_{index:02d}"
    plan = {
        "source_asset_ids": source_ids,
        "transfer_scope": list(dict.fromkeys(
            _strings(candidate.get("transfer_scope"))
            or ["action", "expression", "performance_rhythm"]
        )) if source_ids else [],
        "excluded_scope": list(dict.fromkeys(
            _strings(candidate.get("excluded_scope"))
            or ["identity", "outfit", "scene", "camera", "editing"]
        )) if source_ids else [],
        "duration_mappings": duration_mappings,
        "beats": normalized_beats,
    }
    if len(duration_mappings) == 1:
        plan["duration_mapping"] = copy.deepcopy(duration_mappings[0])
    payload["performance_plan"] = plan
    return payload


def normalize_timeline_beat_refs(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach beats to overlapping shots without deriving any new shot."""
    beats = payload.get("performance_plan", {}).get("beats", [])
    if not isinstance(beats, list):
        beats = []
    for shot in payload.get("timeline", []):
        if not isinstance(shot, dict):
            continue
        if not _number(shot.get("start_seconds")) or not _number(shot.get("end_seconds")):
            shot["beat_refs"] = []
            continue
        shot_start, shot_end = float(shot["start_seconds"]), float(shot["end_seconds"])
        refs = []
        for beat in beats:
            if not isinstance(beat, Mapping):
                continue
            target_range = beat.get("target_range")
            if not isinstance(target_range, list) or len(target_range) != 2 or not all(_number(value) for value in target_range):
                continue
            beat_start, beat_end = float(target_range[0]), float(target_range[1])
            if beat_end > shot_start + EPSILON and beat_start < shot_end - EPSILON:
                refs.append(str(beat.get("beat_id", "")))
        shot["beat_refs"] = [item for item in refs if item]
    return payload


def normalize_keyframe_roles(payload: dict[str, Any]) -> dict[str, Any]:
    """Compile each conditioned Picture into an explicit, dimension-scoped role."""
    assets = {
        str(item.get("asset_id", "")): item
        for item in payload.get("assets", [])
        if isinstance(item, Mapping) and str(item.get("asset_id", ""))
    }
    bindings_by_asset: dict[str, list[Mapping[str, Any]]] = {}
    for binding in payload.get("asset_bindings", []):
        if isinstance(binding, Mapping):
            bindings_by_asset.setdefault(str(binding.get("asset_id", "")), []).append(binding)
    subject_shots = {
        str(subject.get("subject_id", "")): _strings(subject.get("appearance_shot_ids"))
        for subject in payload.get("subjects", [])
        if isinstance(subject, Mapping)
    }
    relationship_subjects = {
        str(item.get("asset_id", "")): _strings(item.get("subject_refs"))
        for item in payload.get("reference_relationships", [])
        if isinstance(item, Mapping)
    }
    candidates = payload.get("keyframe_roles")
    candidates = [item for item in candidates if isinstance(item, Mapping)] if isinstance(candidates, list) else []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def add_role(item: Mapping[str, Any]) -> None:
        asset_id = str(item.get("asset_id", "")).strip()
        role = str(item.get("role", "")).strip()
        subject_refs = list(dict.fromkeys(_strings(item.get("subject_refs"))))
        shot_refs = list(dict.fromkeys(_strings(item.get("shot_refs"))))
        beat_refs = list(dict.fromkeys(_strings(item.get("beat_refs"))))
        key = (asset_id, role, tuple(subject_refs), tuple(shot_refs), tuple(beat_refs))
        if key in seen:
            return
        seen.add(key)
        related_bindings = bindings_by_asset.get(asset_id, [])
        controls = list(dict.fromkeys(
            _strings(item.get("controls"))
            or [value for binding in related_bindings for value in _strings(binding.get("inherit"))]
        ))
        excludes = list(dict.fromkeys(
            _strings(item.get("excludes"))
            + [value for binding in related_bindings for value in _strings(binding.get("exclude"))]
            + ["motion", "camera", "editing", "music", "performance rhythm"]
        ))
        source = str(item.get("source", ""))
        normalized.append({
            "role_id": "",
            "asset_id": asset_id,
            "role": role,
            "subject_refs": subject_refs,
            "shot_refs": shot_refs,
            "beat_refs": beat_refs,
            "controls": controls or [role.replace("_", " ")],
            "excludes": excludes,
            "description": str(item.get("description", "")).strip() or f"The Picture supplies {role.replace('_', ' ')} only.",
            "source": source if source in KEYFRAME_ROLE_SOURCES else "derived_requirement",
            "evidence_refs": list(dict.fromkeys(_strings(item.get("evidence_refs")))),
            "confidence": float(item.get("confidence")) if _number(item.get("confidence")) else (1.0 if source == "explicit_user" else 0.8),
        })

    for candidate in candidates:
        add_role(candidate)

    conditioned_image_ids = [
        str(asset.get("asset_id", ""))
        for asset in _condition_assets(payload)
        if asset.get("media_type") == "image"
    ]
    assigned_roles: dict[str, set[str]] = {}
    for item in normalized:
        assigned_roles.setdefault(item["asset_id"], set()).add(item["role"])
    first_shot = str(payload.get("timeline", [{}])[0].get("shot_id", "01")) if payload.get("timeline") else "01"
    last_shot = str(payload.get("timeline", [{}])[-1].get("shot_id", "01")) if payload.get("timeline") else "01"
    for asset_id in conditioned_image_ids:
        bindings = bindings_by_asset.get(asset_id, [])
        binding_roles = {str(item.get("role", "")) for item in bindings}
        inherited = list(dict.fromkeys(
            value for binding in bindings for value in _strings(binding.get("inherit"))
        ))
        inherited_text = " ".join(inherited).casefold()
        subject_refs = relationship_subjects.get(asset_id, [])
        shot_refs = list(dict.fromkeys(
            shot_id for subject_id in subject_refs for shot_id in subject_shots.get(subject_id, [])
        ))
        derived_roles: list[tuple[str, list[str], list[str]]] = []
        if "first_frame" in binding_roles:
            derived_roles.append(("first_frame", [first_shot], inherited))
        if "last_frame" in binding_roles:
            derived_roles.append(("last_frame", [last_shot], inherited))
        appearance_markers = (
            "appearance", "identity", "face", "facial", "hair", "body",
            "outfit", "wardrobe", "clothing", "product", "geometry", "material",
        )
        if binding_roles.intersection({"identity", "outfit", "product"}) or any(
            re.search(r"\b" + re.escape(marker) + r"\b", inherited_text) for marker in appearance_markers
        ):
            appearance_controls = [
                value for value in inherited
                if any(re.search(r"\b" + re.escape(marker) + r"\b", value.casefold()) for marker in appearance_markers)
            ]
            derived_roles.append(("appearance_source", shot_refs or [first_shot], appearance_controls or inherited))
        scene_markers = (
            "scene", "environment", "background", "layout", "sink", "cabinet",
            "counter", "door", "wall", "set dressing", "location",
        )
        if "scene" in binding_roles or any(re.search(r"\b" + re.escape(marker) + r"\b", inherited_text) for marker in scene_markers):
            scene_controls = [
                value for value in inherited
                if any(re.search(r"\b" + re.escape(marker) + r"\b", value.casefold()) for marker in scene_markers)
            ]
            derived_roles.append(("scene_anchor", shot_refs or [first_shot], scene_controls or inherited))
        if "style" in binding_roles:
            derived_roles.append(("style_reference", shot_refs or [first_shot], inherited))
        if not derived_roles:
            derived_roles.append(("composition_anchor", shot_refs or [first_shot], inherited))
        for role, role_shots, role_controls in derived_roles:
            if role in assigned_roles.get(asset_id, set()):
                continue
            add_role({
                "asset_id": asset_id,
                "role": role,
                "subject_refs": subject_refs,
                "shot_refs": role_shots,
                "beat_refs": [],
                "controls": role_controls,
                "description": f"The Picture is the scoped {role.replace('_', ' ')} for the referenced target.",
                "source": "derived_requirement",
                "evidence_refs": [],
                "confidence": 0.8,
            })
    for index, item in enumerate(normalized, start=1):
        item["role_id"] = f"keyframe_role_{index:03d}"
    payload["keyframe_roles"] = normalized
    beats = payload.get("performance_plan", {}).get("beats", [])
    beat_index = {
        str(beat.get("beat_id", "")): beat
        for beat in beats
        if isinstance(beat, dict)
    }
    for item in normalized:
        if item["role"] != "action_keyframe":
            continue
        for beat_id in item["beat_refs"]:
            beat = beat_index.get(beat_id)
            if beat is None:
                continue
            refs = list(dict.fromkeys(_strings(beat.get("keyframe_refs")) + [item["role_id"]]))
            beat["keyframe_refs"] = refs
    return payload


def _policy_default(module: str, source_edit: bool, generate_audio: bool) -> dict[str, Any]:
    if module in ENTITY_CONSTRAINT_MODULES:
        return {
            "mode": "strict", "source": "derived_requirement", "priority": "hard",
            "allow_new_events": False, "preserve_reference": True,
            "constraints": {}, "events": [], "prohibit": [], "assumptions": [],
        }
    if source_edit and module in {"camera", "editing", "motion", "lighting", "audio"}:
        return {
            "mode": "reference", "source": "edit_base_preservation", "priority": "hard",
            "allow_new_events": False, "preserve_reference": True,
            "constraints": {}, "events": [], "prohibit": [], "assumptions": [],
        }
    defaults = {
        "camera": ("auto", False), "editing": ("auto", False),
        "motion": ("auto", True), "performance": ("auto", True),
        "composition": ("auto", True), "lighting": ("auto", False),
        "audio": (("enhance" if generate_audio else "disabled"), generate_audio),
        "style": ("auto", True), "effects": ("disabled", False),
        "text": ("disabled", False),
    }
    mode, allow = defaults[module]
    prohibit = []
    if module == "lighting":
        prohibit = ["random flicker", "exposure pumping", "unsupported dynamic light effects"]
    elif module == "audio":
        prohibit = ["unsupported narration", "unsupported dialogue", "unsupported lyrics"]
    elif module == "effects":
        prohibit = ["unsupported particles", "unsupported smoke", "unsupported lens flare"]
    elif module == "text":
        prohibit = ["new subtitles", "invented slogans", "invented logos", "price text"]
    return {
        "mode": mode, "source": "default_completion", "priority": "soft",
        "allow_new_events": bool(allow), "preserve_reference": False,
        "constraints": {}, "events": [], "prohibit": prohibit, "assumptions": [],
    }


def normalize_production_policies(payload: dict[str, Any]) -> dict[str, Any]:
    """Fill policy permissions without overriding explicit model decisions."""
    source_edit = any(
        isinstance(item, Mapping) and item.get("relationship") == "source_video_edit"
        for item in payload.get("reference_relationships", [])
    )
    task = payload.get("task", {})
    generate_audio = isinstance(task, Mapping) and task.get("generate_audio") is True
    production = payload.get("production_policies")
    if not isinstance(production, dict):
        production = {}
        payload["production_policies"] = production
    entities = payload.get("entity_constraints")
    if not isinstance(entities, dict):
        entities = {}
        payload["entity_constraints"] = entities
    for collection, modules in ((production, PRODUCTION_POLICY_MODULES), (entities, ENTITY_CONSTRAINT_MODULES)):
        for module in modules:
            default = _policy_default(module, source_edit, generate_audio)
            candidate = collection.get(module)
            if not isinstance(candidate, dict):
                collection[module] = default
                continue
            for key, value in default.items():
                candidate.setdefault(key, copy.deepcopy(value))
            if (
                source_edit
                and module in {"camera", "editing", "motion", "lighting", "audio"}
                and candidate.get("source") not in {"explicit_user", "explicit_prohibition"}
            ):
                candidate.update({
                    "mode": "reference", "source": "edit_base_preservation",
                    "priority": "hard", "allow_new_events": False,
                    "preserve_reference": True,
                })
                events = candidate.get("events")
                if isinstance(events, list):
                    candidate["events"] = [
                        event for event in events
                        if isinstance(event, Mapping)
                        and event.get("source") in {
                            "explicit_user", "reference_evidence", "edit_base_preservation"
                        }
                    ]
            if candidate.get("mode") == "disabled":
                candidate["allow_new_events"] = False
                candidate["events"] = []
            if candidate.get("mode") == "reference" and not source_edit:
                events = candidate.get("events")
                has_completion_event = isinstance(events, list) and any(
                    isinstance(event, Mapping)
                    and event.get("source") not in {
                        "explicit_user", "reference_evidence", "edit_base_preservation"
                    }
                    for event in events
                )
                if has_completion_event:
                    # A reference-guided module may still contain conservative
                    # production completion. It is therefore mixed/automatic,
                    # not a pure reference replay. Preserve the reference while
                    # making the additional event permission explicit.
                    candidate["mode"] = "auto"
                    candidate["allow_new_events"] = True
                    assumptions = candidate.get("assumptions")
                    if not isinstance(assumptions, list):
                        assumptions = []
                        candidate["assumptions"] = assumptions
                    note = (
                        "Reference-guided module also contains conservative "
                        "completion events; normalized to auto mode."
                    )
                    if note not in assumptions:
                        assumptions.append(note)
            if module == "audio" and not generate_audio:
                candidate.update({
                    "mode": "disabled", "source": "explicit_prohibition",
                    "priority": "hard", "allow_new_events": False,
                    "events": [],
                })
            if module in ENTITY_CONSTRAINT_MODULES:
                candidate["mode"] = "strict"
                candidate["priority"] = "hard"
                candidate["allow_new_events"] = False
            if candidate.get("source") in {"explicit_user", "explicit_prohibition"}:
                candidate["priority"] = "hard"
    motion_only_video_ids = _motion_reference_without_editorial_authority(payload)
    if motion_only_video_ids:
        # A hard performance transfer is dimension-scoped.  Technical
        # completion may select a conservative locked framing, but it may not
        # silently turn performance rhythm into editorial or camera authority.
        for module in ("camera", "editing"):
            candidate = production[module]
            candidate.update({
                "mode": "disabled" if module == "editing" else "auto",
                "source": "derived_requirement",
                "priority": "hard",
                "allow_new_events": False,
                "preserve_reference": False,
            })
            candidate["events"] = []
            assumptions = candidate.get("assumptions")
            if not isinstance(assumptions, list):
                assumptions = []
                candidate["assumptions"] = assumptions
            note = (
                "Motion/performance transfer does not grant camera or editing "
                "authority; use one continuous shot with conservative framing."
            )
            if note not in assumptions:
                assumptions.append(note)
        semantic_plan = payload.get("semantic_plan")
        if isinstance(semantic_plan, dict):
            semantic_plan["shot_planning_mode"] = "reference"
            authority = semantic_plan.get("completion_authority")
            if isinstance(authority, dict):
                authority["timeline"] = False
    return payload


def compile_context_ir(model_output: Mapping[str, Any], source_request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = copy.deepcopy(dict(model_output))
    payload.setdefault("schema_version", IR_SCHEMA_VERSION)
    payload.setdefault("protocol", {"rewrite_language": "English", "preserve_source_language_for": ["dialogue", "lyrics", "visible scene text"]})
    payload.setdefault("runtime", {
        "perception_provider": {"provider": "gitee-qwen3-vl", "model": "Qwen3-VL-30B-A3B-Instruct", "options": {}},
        "reasoning_provider": {"provider": "glm", "model": "GLM-5.2"},
        "generation_provider": {"provider": "minimax", "model": "MiniMax-H3"},
    })
    if source_request is not None:
        source = normalize_source_request(source_request)
        # These fields are authoritative input facts, not semantic decisions.
        # Inject them instead of asking the reasoning model to reproduce a large
        # perception tree and file paths byte-for-byte.
        payload["task"] = copy.deepcopy(source.get("task", {}))
        payload["assets"] = copy.deepcopy(source.get("assets", []))
        payload["perception"] = copy.deepcopy(source.get("perception"))
        perception_provider = (
            source.get("perception", {}).get("provider", {})
            if isinstance(source.get("perception"), Mapping)
            else {}
        )
        runtime = payload.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
            payload["runtime"] = runtime
        runtime["perception_provider"] = copy.deepcopy(perception_provider)
        runtime.setdefault("reasoning_provider", {"provider": "configured", "model": "configured"})
        runtime.setdefault("generation_provider", {"provider": "minimax", "model": "MiniMax-H3"})
        intent = payload.setdefault("intent", {})
        if not isinstance(intent, dict):
            raise ContextIRError("intent must be an object")
        intent["user_request"] = source.get("user_request", "")
        intent.pop("resolution_status", None)
        intent["resolved_request"] = source.get("resolved_request", "") or intent.get("resolved_request", "")
        intent["directives"] = copy.deepcopy(source.get("directives", []))
        intent["completion_policy"] = copy.deepcopy(source["completion_policy"])
        # Source directives are authoritative. A reasoning model may still invent
        # directive IDs while expanding a natural-language-only request. Remove
        # those cross-field references deterministically before validation. When
        # real source directives exist, the existing coverage audit below still
        # rejects any authoritative directive the model failed to implement.
        source_directive_ids = {
            str(item.get("directive_id", "")).strip()
            for item in source.get("directives", [])
            if isinstance(item, Mapping) and str(item.get("directive_id", "")).strip()
        }
        directive_assets = {
            str(item.get("directive_id", "")).strip(): str(item.get("asset_id", "")).strip()
            for item in source.get("directives", [])
            if isinstance(item, Mapping) and str(item.get("directive_id", "")).strip()
        }
        bindings = payload.get("asset_bindings", [])
        if isinstance(bindings, list):
            for binding in bindings:
                if isinstance(binding, dict):
                    binding_asset = str(binding.get("asset_id", "")).strip()
                    binding["source_directive_ids"] = [
                        directive_id
                        for directive_id in _strings(binding.get("source_directive_ids"))
                        if directive_id in source_directive_ids
                        and (
                            not directive_assets.get(directive_id)
                            or directive_assets[directive_id] == binding_asset
                        )
                    ]
        compile_directive_bindings(payload, source)
    # asset_bindings is the single authoritative relation graph. All duplicate
    # cross-field references are compiler-derived, not independently authored
    # by the semantic model.
    derive_binding_graph(payload)
    normalize_source_video_audio_relationship(payload)
    normalize_reference_retention_modes(payload)
    normalize_reference_isolation(payload)
    normalize_subject_source_bindings(payload)
    normalize_creative_focus_asset(payload)
    normalize_primary_subject(payload)
    normalize_focus_shot_bindings(payload)
    normalize_binding_isolation_conflicts(payload)
    normalize_timeline_boundaries(payload)
    normalize_unresolved_reference_timeline(payload)
    normalize_subject_appearance_shots(payload)
    normalize_focus_shot_bindings(payload)
    normalize_global_constraint_conflicts(payload)
    normalize_timeline_state_fields(payload)
    normalize_production_policies(payload)
    normalize_performance_plan(payload)
    normalize_timeline_beat_refs(payload)
    normalize_keyframe_roles(payload)
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


def build_subject_inventory(payload: Mapping[str, Any]) -> dict[str, str]:
    """Assign stable official H3 Subject labels from validated entity order."""
    return {
        str(subject["subject_id"]): f"<Subject {index}>"
        for index, subject in enumerate(payload.get("subjects", []), start=1)
    }


def project_reference_labels(text: str, inventory: Mapping[str, str]) -> str:
    """Replace internal asset IDs with the exact official H3 reference labels."""
    result = str(text)
    # Longest first prevents image_1 from touching a hypothetical image_10.
    for asset_id in sorted(inventory, key=len, reverse=True):
        result = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(asset_id)}(?![A-Za-z0-9_])",
            inventory[asset_id],
            result,
            flags=re.IGNORECASE,
        )
    return result


def _shot_text(shot: Mapping[str, Any], shot_number: int, subject_inventory: Mapping[str, str] | None = None) -> str:
    subject_inventory = subject_inventory or {}
    labels = [subject_inventory[item] for item in _strings(shot.get("subject_refs")) if item in subject_inventory]
    subject_opening = ""
    if labels:
        subject_opening = ", ".join(labels) + (" are visible. " if len(labels) > 1 else " is visible. ")
    pieces = [subject_opening + str(shot["event"])]
    pieces.extend(
        f"{key}: {shot[key]}"
        for key in ("camera", "lighting", "transition")
        if shot.get(key)
    )
    pieces.append("observable end state: " + str(shot.get("observable_end_state", "")))
    prefix = f"[Shot {shot_number}]"
    if shot_number != 1:
        prefix += f" At {_format_timestamp(float(shot['start_seconds']))},"
    return prefix + " " + "; ".join(pieces)


def _sound_sections(payload: Mapping[str, Any]) -> tuple[str, str]:
    audio = payload["audio_plan"]
    if not payload["task"]["generate_audio"]:
        return "N/A", "N/A"
    soundscape_parts = []
    for key in ("voice", "sound_effects", "ambient_sound", "sync_rules"):
        value = audio[key]
        value_text = str(value).strip()
        if not value_text or value_text.lower() in {"none", "no", "false", "not requested", "[]"}:
            continue
        soundscape_parts.append(f"{key}: {value}")
    soundscape = "; ".join(soundscape_parts) or "N/A"
    music = str(audio["music"]).strip()
    if not music or music.lower() in {"none", "no", "false", "not requested"} or music.lower().startswith(("none;", "no ")):
        music = "N/A"
    return soundscape, music


def _dedupe_prompt_items(values: Iterable[str]) -> list[str]:
    """Deduplicate executable prompt items without changing their first wording."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value).strip().split()).rstrip(".;")
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _constraint_text(payload: Mapping[str, Any]) -> str:
    """Render one authoritative global constraint block.

    Policy provenance, modes and event registries remain in Context-IR for
    auditability.  The H3 prompt receives only executable boundaries.  Policy
    events are already expressed by their referenced timeline shots and must
    not be expanded a second time here.
    """
    constraints = payload["constraints"]
    parts = []
    preserve = _dedupe_prompt_items(_strings(constraints.get("preserve")))
    allow_change = _dedupe_prompt_items(_strings(constraints.get("allow_change")))
    prohibit_values = list(_strings(constraints.get("prohibit")))
    for collection_name, modules in (
        ("production_policies", PRODUCTION_POLICY_MODULES),
        ("entity_constraints", ENTITY_CONSTRAINT_MODULES),
    ):
        collection = payload.get(collection_name, {})
        if not isinstance(collection, Mapping):
            continue
        for module in modules:
            policy = collection.get(module)
            if isinstance(policy, Mapping):
                prohibit_values.extend(_strings(policy.get("prohibit")))
    prohibit = _dedupe_prompt_items(prohibit_values)
    if preserve:
        parts.append("Must preserve: " + ", ".join(preserve))
    if allow_change:
        parts.append("May change only as requested: " + ", ".join(allow_change))
    if prohibit:
        parts.append("Must not introduce: " + ", ".join(prohibit))
    return "Global constraints: " + "; ".join(parts) if parts else ""


def _projected_constraint_text(payload: Mapping[str, Any], covered_text: str = "") -> str:
    """Project only authoritative user-facing boundaries into the H3 prompt.

    The full normalized constraint and policy matrices remain in Context-IR.
    Prompt text follows the official rewrite style: user directives appear
    once, while compiler safety defaults and audit provenance stay internal.
    """
    intent = payload.get("intent", {})
    directives = intent.get("directives", []) if isinstance(intent, Mapping) else []
    preserve: list[str] = []
    change: list[str] = []
    prohibit: list[str] = []
    for directive in directives if isinstance(directives, list) else []:
        if not isinstance(directive, Mapping):
            continue
        scopes = _strings(directive.get("scope"))
        # The target carries semantic scope (for example Shot 1 only).
        # Dropping it promotes local requirements into global restrictions.
        target = str(directive.get("target", "")).strip()
        if target and scopes:
            scopes = [f"For {target}: " + "; ".join(scopes)]
        operation = str(directive.get("operation", ""))
        if operation == "exclude":
            prohibit.extend(scopes)
        elif operation in {"replace", "transfer", "may_change"}:
            change.extend(scopes)
        elif operation == "preserve":
            preserve.extend(scopes)
    # Legacy/natural-language callers may have no directive contract. In that
    # case retain their explicit normalized constraints rather than dropping
    # safety boundaries from the prompt projection.
    if not directives:
        constraints = payload.get("constraints", {})
        if isinstance(constraints, Mapping):
            preserve.extend(_strings(constraints.get("preserve")))
            change.extend(_strings(constraints.get("allow_change")))
            prohibit.extend(_strings(constraints.get("prohibit")))
    covered_folded = " ".join(covered_text.casefold().split())
    preserve = [item for item in preserve if " ".join(item.casefold().split()) not in covered_folded]
    change = [item for item in change if " ".join(item.casefold().split()) not in covered_folded]
    prohibit = [item for item in prohibit if " ".join(item.casefold().split()) not in covered_folded]
    parts: list[str] = []
    preserve = _dedupe_prompt_items(preserve)
    change = _dedupe_prompt_items(change)
    prohibit = _dedupe_prompt_items(prohibit)
    if preserve:
        parts.append("Preserve " + ", ".join(preserve))
    if change:
        parts.append("Change only as specified: " + ", ".join(change))
    if prohibit:
        parts.append("Do not introduce or inherit " + ", ".join(prohibit))
    return "Scoped requirements: " + "; ".join(parts) + "." if parts else ""


def _shot_text_projected(
    shot: Mapping[str, Any],
    shot_number: int,
    subject_inventory: Mapping[str, str],
    performance_beats: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Render an official-style shot from the richer executable IR state."""
    labels = [subject_inventory[item] for item in _strings(shot.get("subject_refs")) if item in subject_inventory]
    event = str(shot.get("event", "")).strip().rstrip(".;")
    parts = [event] if event else []
    event_folded = event.casefold()
    camera_markers = (
        "camera", " shot", "frame", "view", "focus", "pan", "zoom", "dolly",
        "orbit", "track", "handheld", "static", "rack", "push-in", "pull-back", "tilt",
    )
    camera = str(shot.get("camera", "")).strip().rstrip(".;")
    if camera and not any(marker in event_folded for marker in camera_markers):
        parts.append(camera)
    transition = str(shot.get("transition", "")).strip().rstrip(".;")
    transition_markers = ("transition", "cut", "whip", "dissolve", "fade", "blur", "smear")
    if transition and not any(marker in event_folded for marker in transition_markers):
        parts.append(transition)
    beat_items = [
        performance_beats[beat_id]
        for beat_id in _strings(shot.get("beat_refs"))
        if performance_beats and beat_id in performance_beats
    ]
    if beat_items:
        sequence_parts = []
        generic_by_source: dict[str, list[str]] = {}
        for beat in beat_items:
            target_range = beat.get("target_range", [])
            if not isinstance(target_range, list) or len(target_range) != 2:
                continue
            start = _format_timestamp(float(target_range[0]))
            if beat.get("status") == "unresolved_tail":
                sequence_parts.append(
                    f"From {start} onward, the reference performance is unresolved; do not loop, repeat, or invent a new action"
                )
            else:
                action = str(beat.get("action", "")).strip().rstrip(".;")
                if beat.get("action_source") == "derived_requirement":
                    generic_by_source.setdefault(str(beat.get("source_asset_id", "the reference Video")), []).append(start)
                elif action:
                    sequence_parts.append(f"At {start}, {action[0].lower() + action[1:]}")
        for source_id, times in generic_by_source.items():
            change_times = [value for value in times if value != "00:00.000"]
            timing = f"; observed action beats change at {', '.join(change_times)}" if change_times else ""
            sequence_parts.insert(
                0,
                f"Follow {source_id} continuously for ordered action, expression, and performance rhythm{timing}",
            )
        if sequence_parts:
            parts.append("Performance sequence: " + "; then ".join(sequence_parts))
    end_state = str(shot.get("observable_end_state", "")).strip().rstrip(".;")
    if end_state:
        meaningful = {
            token for token in re.findall(r"[a-z0-9'-]+", end_state.casefold())
            if len(token) > 3 and token not in {"with", "that", "this", "from", "into", "shot", "state"}
        }
        covered = sum(token in event_folded for token in meaningful)
        if meaningful and covered / len(meaningful) < 0.55:
            parts.append("The shot ends with " + end_state[0].lower() + end_state[1:])
    subject_opening = ""
    if labels:
        subject_opening = ", ".join(labels) + (" are visible. " if len(labels) > 1 else " is visible. ")
    prefix = f"[Shot {shot_number}]"
    if shot_number != 1:
        prefix += f" At {_format_timestamp(float(shot['start_seconds']))},"
    return prefix + " " + subject_opening + ". ".join(parts) + "."


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
    constraint_text = _constraint_text(payload)
    focus = payload["creative_focus"]
    focus_text = (
        f"Primary visual focus: {focus['objective']}. Presentation requirements: "
        + "; ".join(_strings(focus.get("presentation_requirements")))
    )
    description = ". ".join(part for part in (focus_text, constraint_text, opening, " ".join(shots)) if part)
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
    subject_inventory = build_subject_inventory(payload)
    focus = payload["creative_focus"]
    subjects = []
    retention = []
    binding_by_id = {
        str(binding.get("binding_id")): binding
        for binding in payload.get("asset_bindings", [])
        if isinstance(binding, Mapping)
    }
    media_by_asset = {
        str(asset.get("asset_id")): str(asset.get("media_type"))
        for asset in payload.get("assets", [])
        if isinstance(asset, Mapping)
    }
    performance_beats = {
        str(beat.get("beat_id", "")): beat
        for beat in payload.get("performance_plan", {}).get("beats", [])
        if isinstance(beat, Mapping) and str(beat.get("beat_id", ""))
    }
    keyframe_roles_by_subject: dict[str, list[Mapping[str, Any]]] = {}
    for role in payload.get("keyframe_roles", []):
        if not isinstance(role, Mapping):
            continue
        for subject_id in _strings(role.get("subject_refs")):
            keyframe_roles_by_subject.setdefault(subject_id, []).append(role)
    for subject in payload["subjects"]:
        label = subject_inventory[subject["subject_id"]]
        source_controls: dict[str, dict[str, Any]] = {}
        for binding_id in _strings(subject.get("binding_ids")):
            binding = binding_by_id.get(binding_id)
            if not binding:
                continue
            asset_id = str(binding.get("asset_id", ""))
            if asset_id not in inventory:
                continue
            control = source_controls.setdefault(asset_id, {"roles": [], "inherit": [], "exclude": [], "hard": False})
            control["roles"].append(str(binding.get("role", "")))
            control["inherit"].extend(_strings(binding.get("inherit")))
            control["exclude"].extend(_strings(binding.get("exclude")))
            control["hard"] = control["hard"] or binding.get("priority") == "hard"
        clauses = []
        source_asset_ids = list(_strings(subject.get("source_asset_ids")))
        # Structural bindings still need an explicit provenance/appearance
        # guard in the official Subject definition.  A reasoning model may
        # correctly omit a style, motion or camera reference from
        # source_asset_ids because it is not an appearance source; recover the
        # bound asset here so the renderer can state that distinction instead
        # of leaving the reference ambiguous.
        for binding_id in _strings(subject.get("binding_ids")):
            binding = binding_by_id.get(binding_id)
            if not binding:
                continue
            bound_asset_id = str(binding.get("asset_id", ""))
            if bound_asset_id in inventory and bound_asset_id not in source_asset_ids:
                source_asset_ids.append(bound_asset_id)
        for asset_id in source_asset_ids:
            if asset_id not in inventory:
                continue
            label_ref = inventory[asset_id]
            control = source_controls.get(asset_id, {"roles": [], "inherit": [], "exclude": [], "hard": False})
            roles = set(control["roles"])
            structural_roles = roles.intersection(STRUCTURAL_BINDING_ROLES)
            appearance_roles = roles.intersection(APPEARANCE_BINDING_ROLES)
            if roles and roles.issubset(STRUCTURAL_BINDING_ROLES):
                role_text = ", ".join(sorted(roles))
                clauses.append(f"its {role_text} follows {label_ref}; {label_ref} is not an appearance source")
            elif appearance_roles:
                ordered_roles = [
                    role for role in ("identity", "outfit", "product", "scene")
                    if role in appearance_roles
                ]
                role_labels = {
                    "identity": "identity and facial appearance",
                    "outfit": "outfit",
                    "product": "product appearance",
                    "scene": "environment appearance",
                }
                scope_text = ", ".join(role_labels[role] for role in ordered_roles)
                clause = f"{label_ref} controls its {scope_text}"
                if structural_roles:
                    clause += f" and its {', '.join(sorted(structural_roles))} also follows that reference"
                clauses.append(clause)
            else:
                clauses.append(f"its scoped reference guidance comes from {label_ref}")
        for role in keyframe_roles_by_subject.get(str(subject.get("subject_id", "")), []):
            asset_id = str(role.get("asset_id", ""))
            label_ref = inventory.get(asset_id)
            if not label_ref:
                continue
            role_type = str(role.get("role", ""))
            if role_type == "action_keyframe":
                times = []
                for beat_id in _strings(role.get("beat_refs")):
                    beat = performance_beats.get(beat_id)
                    target_range = beat.get("target_range", []) if beat else []
                    if isinstance(target_range, list) and len(target_range) == 2 and _number(target_range[0]):
                        times.append(_format_timestamp(float(target_range[0])))
                timing = " at " + ", ".join(times) if times else ""
                clauses.append(f"{label_ref} anchors its exact action pose{timing}, not motion or edit rhythm")
            elif role_type == "product_detail":
                clauses.append(f"{label_ref} anchors its exact product surface and close-detail appearance")
            elif role_type == "appearance_source":
                bound_roles = set(source_controls.get(asset_id, {}).get("roles", []))
                if not bound_roles.intersection(APPEARANCE_BINDING_ROLES - {"scene"}):
                    controls = ", ".join(_strings(role.get("controls"))[:6])
                    detail = f" ({controls})" if controls else ""
                    clauses.append(f"{label_ref} controls its appearance{detail}")
            elif role_type == "scene_anchor":
                if "scene" not in source_controls.get(asset_id, {}).get("roles", []):
                    clauses.append(f"{label_ref} anchors its environment appearance without supplying motion")
            elif role_type == "composition_anchor":
                clauses.append(f"{label_ref} anchors its composition without supplying motion or editing")
            elif role_type == "style_reference":
                if "style" not in source_controls.get(asset_id, {}).get("roles", []):
                    clauses.append(f"{label_ref} supplies only its authorized visual style")
        source_text = ("; " + "; ".join(clauses)) if clauses else ""
        subjects.append(f"{label} is {str(subject['name']).strip().rstrip('.')}, {str(subject['description']).strip().rstrip('.')}{source_text}.")
        shots = ", ".join(f"[Shot {int(item)}]" for item in _strings(subject.get("appearance_shot_ids")))
        appearance = f" (appears in {shots})" if shots else ""
        retention.append(f"{label}{appearance}: {subject['retention_mode']} - {str(subject['retention_description']).strip().rstrip('.')}.")
    binding_roles_by_asset: dict[str, set[str]] = {}
    for binding in payload.get("asset_bindings", []):
        if isinstance(binding, Mapping):
            binding_roles_by_asset.setdefault(str(binding.get("asset_id")), set()).add(str(binding.get("role")))
    subject_binding_ids = {
        binding_id
        for subject in payload.get("subjects", [])
        if isinstance(subject, Mapping)
        for binding_id in _strings(subject.get("binding_ids"))
    }


    subject_roles_by_asset: dict[str, set[str]] = {}
    for binding_id in subject_binding_ids:
        binding = binding_by_id.get(binding_id)
        if binding:
            subject_roles_by_asset.setdefault(str(binding.get("asset_id")), set()).add(str(binding.get("role")))
    structural_subject_assets = {
        asset_id
        for asset_id, roles in subject_roles_by_asset.items()
        if roles and roles.issubset(STRUCTURAL_BINDING_ROLES)
    }
    for relationship in payload["reference_relationships"]:
        label = inventory[relationship["asset_id"]]
        linked = [subject_inventory[item] for item in _strings(relationship.get("subject_refs")) if item in subject_inventory]
        link_text = f" It applies to {', '.join(linked)}." if linked else ""
        definition = str(relationship['definition']).strip().rstrip('.')
        if definition.lower().startswith("is "):
            definition = definition[3:]
        asset_id = str(relationship["asset_id"])
        roles = binding_roles_by_asset.get(asset_id, set())
        is_frame_anchor = bool(roles.intersection({"first_frame", "last_frame"})) or relationship.get("relationship") == "keyframe_completion"
        needs_standalone_definition = media_by_asset.get(asset_id) in {"video", "audio"} or is_frame_anchor or not linked
        if needs_standalone_definition:
            appearance_guard = (
                f" {label} is not an appearance source."
                if asset_id in structural_subject_assets or (roles and roles.issubset(STRUCTURAL_BINDING_ROLES))
                else ""
            )
            subjects.append(f"{label} is {definition}.{link_text}{appearance_guard}")
        retention.append(f"{label}: {relationship['retention_mode']} - {str(relationship['retention_description']).strip().rstrip('.')}.")
    task_types = _strings(payload["protocol"].get("summary_task_types"))
    prefix = "[" + " + ".join(task_types) + "]"
    source_video_label = ""
    for relationship in payload["reference_relationships"]:
        if relationship.get("relationship") == "source_video_edit":
            source_video_label = inventory.get(relationship["asset_id"], "")
            break
    edit_opening = f"The target video is an edited version of {source_video_label}. " if "video editing" in task_types and source_video_label else ""
    primary_subject_label = subject_inventory.get(str(focus.get("primary_subject_id", "")), "")
    focus_objective = str(focus['objective']).strip().rstrip('.')
    priority = (payload.get("semantic_plan") or {}).get("subject_priority") or {}
    joint_labels = list(dict.fromkeys(
        subject_inventory[subject_id]
        for subject_id in _strings(priority.get("subject_ids"))
        if subject_id in subject_inventory
    ))
    if priority.get("mode") == "co_equal" and len(joint_labels) > 1:
        focus_summary = f"{', '.join(joint_labels)} share the creative focus: {focus_objective}"
    else:
        focus_summary = f"{primary_subject_label} is the primary creative focus: {focus_objective}" if primary_subject_label else f"Primary creative objective: {focus_objective}"
    style = str(task.get("style", "")).strip().rstrip(".")
    style_summary = f" Target style: {style}." if style else ""
    summary = (
        f"{prefix} {edit_opening}"
        f"{focus_summary}."
        f"{style_summary} "
        f"Audio generation: {task['generate_audio']}."
    )
    projected_shots = [
        _shot_text_projected(shot, index, subject_inventory, performance_beats)
        for index, shot in enumerate(payload["timeline"], start=1)
    ]
    details = []
    generation = payload["generation_description"]
    style_opening = ". ".join(
        str(value).strip().rstrip(".")
        for value in (task.get("style"), generation.get("cinematography"), generation.get("lighting"))
        if str(value or "").strip()
    )
    if style_opening:
        details.append(style_opening + ".")
    covered_text = "\n".join(subjects + retention + [summary, style_opening] + projected_shots)
    global_constraints = _projected_constraint_text(payload, covered_text)
    if global_constraints:
        details.insert(0, global_constraints)
    details.extend(projected_shots)
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
        prompt = _render_ref_prompt(payload, inventory)
    else:
        prompt = _render_base_prompt(payload, inventory)
    return project_reference_labels(prompt, inventory)


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
    raw_asset_ids = sorted(set(RAW_ASSET_ID_PATTERN.findall(prompt)), key=str.casefold)
    if raw_asset_ids:
        report.add(
            "RAW_ASSET_ID_LEAK",
            f"internal asset IDs must be projected to official reference labels: {raw_asset_ids}",
            "$.h3_prompt",
        )
    language_probe = prompt
    # Official H3 dialogue/lyrics tags preserve verbatim source language. Strip
    # their contents only for the rewrite-language audit; the tags remain in the
    # delivered prompt. Untagged CJK prose must still fail below.
    language_probe = re.sub(
        r"<(?:d|l)(?:\s[^>]*)?>.*?</(?:d|l)>",
        "",
        language_probe,
        flags=re.IGNORECASE | re.DOTALL,
    )
    perception = payload.get("perception")
    visible_text_literals: list[str] = []
    if isinstance(perception, Mapping):
        for asset in perception.get("assets", []):
            if not isinstance(asset, Mapping):
                continue
            technical = asset.get("technical")
            if isinstance(technical, Mapping):
                for literal in _strings(technical.get("visible_text")):
                    visible_text_literals.append(literal)
                    language_probe = language_probe.replace(literal, "")
            transcript = str(asset.get("transcript", "")).strip()
            if transcript:
                language_probe = language_probe.replace(transcript, "")
    # A generated shot may cite a concise verbatim fragment of longer OCR
    # evidence. Allow only CJK runs that are literal substrings of a recorded
    # visible-text string; unsupported source-language prose remains an error.
    for fragment in set(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", language_probe)):
        if any(fragment in literal for literal in visible_text_literals):
            language_probe = language_probe.replace(fragment, "")
    if str(payload.get("protocol", {}).get("rewrite_language", "")).lower() == "english" and CJK_PATTERN.search(language_probe):
        report.add(
            "PROMPT_REWRITE_LANGUAGE_VIOLATION",
            "official H3 rewrite sections must be English except verbatim dialogue, lyrics, and visible scene text",
            "$.h3_prompt",
        )
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
    expected_subjects = set(build_subject_inventory(payload).values()) if mode == "ref2va" else set()
    actual_subjects = {f"<Subject {number}>" for number in SUBJECT_TAG_PATTERN.findall(prompt)}
    if actual_subjects - expected_subjects:
        report.add("SUBJECT_TAG_UNEXPECTED", f"unexpected subject tags: {sorted(actual_subjects - expected_subjects)}", "$.h3_prompt")
    if mode == "ref2va" and expected_subjects - actual_subjects:
        report.add("SUBJECT_TAG_MISSING", f"unused subject tags: {sorted(expected_subjects - actual_subjects)}", "$.h3_prompt")
    allowed_angle_tags = {item[1:-1] for item in expected | expected_subjects} | {"d", "/d", "scenetrans", "/scenetrans", "cutoff", "/cutoff"}
    illegal_angle_tags = sorted({item for item in ANGLE_TAG_PATTERN.findall(prompt) if item not in allowed_angle_tags})
    if illegal_angle_tags:
        report.add("PROMPT_NONOFFICIAL_ANGLE_TAG", f"non-official angle-bracket labels: {illegal_angle_tags}", "$.h3_prompt")
    if mode == "ref2va":
        sections = {}
        for index, section in enumerate(REF_SECTIONS):
            start_match = re.search(rf"(?m)^{re.escape(section)}:\s*", prompt)
            if not start_match:
                continue
            end = len(prompt)
            for later in REF_SECTIONS[index + 1:]:
                later_match = re.search(rf"(?m)^{re.escape(later)}:", prompt[start_match.end():])
                if later_match:
                    end = start_match.end() + later_match.start()
                    break
            sections[section] = prompt[start_match.end():end]
        definitions = sections.get("subject_definitions", "")
        retention_text = sections.get("retention_analysis", "")
        details_text = sections.get("detailed_description", "")
        summary_text = sections.get("summary", "")
        for label in expected_subjects:
            if not re.search(rf"(?m)^{re.escape(label)}\s+is\s+", definitions):
                report.add("SUBJECT_DEFINITION_MISSING", f"{label} lacks an official definition", "$.h3_prompt.subject_definitions")
            if label not in retention_text:
                report.add("SUBJECT_RETENTION_MISSING", f"{label} is absent from retention_analysis", "$.h3_prompt.retention_analysis")
            if label not in details_text:
                report.add("SUBJECT_DETAIL_USAGE_MISSING", f"{label} is absent from detailed_description", "$.h3_prompt.detailed_description")
        inventory_by_asset = build_reference_inventory(payload)
        media_by_asset = {
            str(asset.get("asset_id")): str(asset.get("media_type"))
            for asset in payload.get("assets", [])
            if isinstance(asset, Mapping)
        }
        roles_by_asset: dict[str, set[str]] = {}
        subject_roles_by_asset: dict[str, set[str]] = {}
        subject_binding_ids = {
            binding_id
            for subject in payload.get("subjects", [])
            if isinstance(subject, Mapping)
            for binding_id in _strings(subject.get("binding_ids"))
        }
        for binding in payload.get("asset_bindings", []):
            if not isinstance(binding, Mapping):
                continue
            asset_id = str(binding.get("asset_id", ""))
            role = str(binding.get("role", ""))
            roles_by_asset.setdefault(asset_id, set()).add(role)
            if str(binding.get("binding_id")) in subject_binding_ids:
                subject_roles_by_asset.setdefault(asset_id, set()).add(role)
        structural_subject_assets = {
            asset_id
            for asset_id, roles in subject_roles_by_asset.items()
            if roles and roles.issubset(STRUCTURAL_BINDING_ROLES)
        }
        for relationship in payload.get("reference_relationships", []):
            if not isinstance(relationship, Mapping):
                continue
            asset_id = str(relationship.get("asset_id", ""))
            label = inventory_by_asset.get(asset_id, "")
            roles = roles_by_asset.get(asset_id, set())
            frame_anchor = bool(roles.intersection({"first_frame", "last_frame"})) or relationship.get("relationship") == "keyframe_completion"
            linked = bool(_strings(relationship.get("subject_refs")))
            if media_by_asset.get(asset_id) == "image" and linked and not frame_anchor:
                if re.search(rf"(?m)^{re.escape(label)}\s+is\s+", definitions):
                    report.add("PICTURE_STANDALONE_NOT_ANCHOR", f"{label} should be cited inside its Subject definition, not defined as a standalone frame", "$.h3_prompt.subject_definitions")
            if asset_id in structural_subject_assets and label:
                if f"{label} is not an appearance source" not in definitions:
                    report.add("STRUCTURAL_REFERENCE_APPEARANCE_AMBIGUOUS", f"{label} must be explicitly excluded as an appearance source", "$.h3_prompt.subject_definitions")
        task_types = _strings(payload.get("protocol", {}).get("summary_task_types"))
        expected_prefix = "[" + " + ".join(task_types) + "]"
        if not summary_text.lstrip().startswith(expected_prefix):
            report.add("SUMMARY_TASK_PREFIX_INVALID", f"summary must begin with {expected_prefix}", "$.h3_prompt.summary")
        if "video editing" in task_types and not re.match(rf"\s*{re.escape(expected_prefix)} The target video is an edited version of <Video \d+>\.", summary_text):
            report.add("SUMMARY_VIDEO_EDIT_OPENING_INVALID", "video-editing summary must use the official source-video opening", "$.h3_prompt.summary")
        primary_subject = str(payload.get("creative_focus", {}).get("primary_subject_id", ""))
        primary_label = build_subject_inventory(payload).get(primary_subject)
        if primary_label and primary_label not in summary_text:
            report.add("SUMMARY_PRIMARY_SUBJECT_MISSING", "summary must cite the primary Subject label", "$.h3_prompt.summary")
    intent = payload.get("intent", {})
    directives = intent.get("directives", []) if isinstance(intent, Mapping) else []
    prompt_folded = prompt.casefold()
    for directive in directives if isinstance(directives, list) else []:
        if not isinstance(directive, Mapping) or directive.get("priority") != "hard":
            continue
        for scope in _strings(directive.get("scope")):
            if scope.casefold() not in prompt_folded:
                report.add(
                    "PROMPT_HARD_DIRECTIVE_MISSING",
                    f"hard directive scope is absent from prompt projection: {scope}",
                    "$.h3_prompt",
                )
    focus = payload.get("creative_focus")
    if isinstance(focus, Mapping):
        primary_binding_ids = set(_strings(focus.get("primary_binding_ids")))
        required_shot_ids = set(_strings(focus.get("required_shot_ids")))
        focused_shots = {
            str(shot.get("shot_id", ""))
            for shot in payload.get("timeline", [])
            if primary_binding_ids.intersection(_strings(shot.get("binding_refs")))
        }
        missing_focus = required_shot_ids - focused_shots
        if primary_binding_ids and missing_focus:
            report.add("PROMPT_PRIMARY_FOCUS_MISSING", f"primary focus is missing from required shots: {sorted(missing_focus)}", "$.h3_prompt")
        objective = str(focus.get("objective", "")).strip()
        if objective and objective not in prompt:
            report.add("PROMPT_FOCUS_OBJECTIVE_MISSING", "creative focus objective is absent from the compiled prompt", "$.h3_prompt")
    if not payload["task"]["generate_audio"]:
        if not re.search(r"(?m)^overall_soundscape:\s*\n?N/A\s*$", prompt):
            report.add("PROMPT_SILENCE_FORMAT_INVALID", "silent output must use N/A for overall_soundscape", "$.h3_prompt")
        if not re.search(r"(?m)^non_diegetic_music:\s*\n?N/A\s*$", prompt):
            report.add("PROMPT_MUSIC_SILENCE_FORMAT_INVALID", "silent output must use N/A for non_diegetic_music", "$.h3_prompt")
    if mode in {"i2va", "fl2va", "l2va"}:
        pictures = {label for label in expected if label.startswith("<Picture ")}
        if pictures - actual:
            report.add("KEYFRAME_TAG_MISSING", f"missing keyframe tags: {sorted(pictures - actual)}", "$.h3_prompt")
    if len(prompt) > 8000:
        report.add("PROMPT_OVERLONG", "compiled H3 prompt exceeds the 8,000-character soft budget", "$.h3_prompt", "warning")
    if mode == "ref2va":
        detail_match = re.search(
            r"(?ms)^detailed_description:\s*(.*?)(?=^overall_soundscape:)",
            prompt,
        )
        if detail_match and len(re.findall(r"\b[\w'-]+\b", detail_match.group(1))) > 650:
            report.add(
                "PROMPT_DETAIL_OVERLONG",
                "detailed_description exceeds the 650-word soft projection budget",
                "$.h3_prompt.detailed_description",
                "warning",
            )
    return report


_PROMPT_CONTRACT_CODES = {
    "PROMPT_SECTION_MISSING",
    "PROMPT_SECTION_ORDER",
    "PROMPT_SECTION_UNEXPECTED",
    "PROMPT_SHOT_ONE_MISSING",
    "INTERNAL_MEDIA_LEAK",
    "RAW_ASSET_ID_LEAK",
    "PROMPT_REWRITE_LANGUAGE_VIOLATION",
    "PROMPT_TIMESTAMP_RANGE",
    "REFERENCE_TAG_UNEXPECTED",
    "REFERENCE_TAG_MISSING",
    "SUBJECT_TAG_UNEXPECTED",
    "SUBJECT_TAG_MISSING",
    "PROMPT_NONOFFICIAL_ANGLE_TAG",
    "SUBJECT_DEFINITION_MISSING",
    "SUMMARY_TASK_PREFIX_INVALID",
    "SUMMARY_VIDEO_EDIT_OPENING_INVALID",
}


_PROMPT_PRESENTATION_CODES = {
    "PROMPT_SECTION_ORDER",
    "PROMPT_SECTION_UNEXPECTED",
    "PROMPT_SHOT_LABEL_NOT_LINE_START",
    "SUMMARY_TASK_PREFIX_INVALID",
    "SUMMARY_VIDEO_EDIT_OPENING_INVALID",
}


def audit_h3_prompt_contract(payload: Mapping[str, Any], prompt: str) -> ValidationReport:
    """Check only the deterministic H3 transport/format contract.

    This intentionally does not score aesthetics, shot quality, or creative
    semantics.  Failures are suitable for a bounded LLM format-repair turn.
    """
    full = audit_h3_prompt(payload, prompt)
    report = ValidationReport([
        item for item in full.issues
        if item.code in _PROMPT_CONTRACT_CODES and item.severity == "error"
    ])
    cjk_fragments = list(dict.fromkeys(re.findall(
        r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+",
        re.sub(r"<(?:d|l)(?:\s[^>]*)?>.*?</(?:d|l)>", "", prompt, flags=re.IGNORECASE | re.DOTALL),
    )))
    if cjk_fragments and any(item.code == "PROMPT_REWRITE_LANGUAGE_VIOLATION" for item in report.issues):
        report.add(
            "PROMPT_UNTAGGED_CJK_FRAGMENTS",
            "translate or remove unsupported CJK prose: " + ", ".join(cjk_fragments[:12]),
            "$.h3_prompt",
        )
    mode = str(payload.get("task", {}).get("type", "")).lower()
    required = REF_SECTIONS if mode == "ref2va" else BASE_SECTIONS
    for section in required:
        count = len(re.findall(rf"(?m)^{re.escape(section)}:\s*", prompt))
        if count > 1:
            report.add(
                "PROMPT_SECTION_DUPLICATE",
                f"section {section} appears {count} times",
                "$.h3_prompt",
            )

    exact_shots = [int(value) for value in re.findall(r"(?m)^\[Shot\s+(\d+)\](?:\s|$)", prompt)]
    detail_match = re.search(
        r"(?ms)^detailed_description:\s*(.*?)(?=^overall_soundscape:)",
        prompt,
    )
    shot_label_scope = detail_match.group(1) if detail_match else prompt
    misplaced_shots = [
        line.strip()
        for line in shot_label_scope.splitlines()
        if re.search(r"\[Shot\s+\d+\]", line, re.IGNORECASE)
        and not re.match(r"^\[Shot\s+\d+\](?:\s|$)", line, re.IGNORECASE)
    ]
    if misplaced_shots:
        report.add(
            "PROMPT_SHOT_LABEL_NOT_LINE_START",
            f"every shot line must begin with [Shot N]: {misplaced_shots[:4]}",
            "$.h3_prompt.detailed_description",
        )
    bracketed_shot_lines = re.findall(r"(?m)^\[[^\]\r\n]+\]", prompt)
    malformed = [
        value for value in bracketed_shot_lines
        if re.match(r"^\[(?:Shot|\d)", value, re.IGNORECASE)
        and not re.fullmatch(r"\[Shot\s+\d+\]", value)
    ]
    if malformed:
        report.add(
            "PROMPT_SHOT_LABEL_INVALID",
            f"shot labels must use exactly [Shot N]: {malformed[:4]}",
            "$.h3_prompt",
        )
    if exact_shots and exact_shots != list(range(1, len(exact_shots) + 1)):
        report.add(
            "PROMPT_SHOT_SEQUENCE_INVALID",
            f"shot labels must be sequential from 1: {exact_shots}",
            "$.h3_prompt",
        )

    camera_scope_match = re.search(
        r"(?ms)^detailed_description:\s*(.*?)(?=^overall_soundscape:)",
        prompt,
    )
    camera_scope = camera_scope_match.group(1) if camera_scope_match else prompt
    shot_chunks = re.split(r"(?m)(?=^\[Shot\s+\d+\])", camera_scope)
    for index, chunk in enumerate(shot_chunks[1:], start=1):
        locked_camera = re.search(
            r"(?:\b(?:static|locked)(?:-off)?\s+(?:camera|shot)\b|"
            r"\b(?:static|locked)(?:-off)?\b.{0,60}\b(?:pan|tilt|track|push|pull|zoom|arc|orbit|handheld|reframe))",
            chunk,
            re.IGNORECASE,
        )
        camera_move = re.search(
            r"\b(?:camera\s+)?(?:pan(?:s|ning)?|tilt(?:s|ing)?|track(?:s|ing)?|"
            r"push(?:es|ing)?\s+in|pull(?:s|ing)?\s+(?:back|out)|zoom(?:s|ing)?|"
            r"arc(?:s|ing)?|orbit(?:s|ing)?|handheld|reframe(?:s|ing)?)\b",
            chunk,
            re.IGNORECASE,
        )
        if locked_camera and camera_move:
            report.add(
                "PROMPT_CAMERA_CONTRADICTION",
                f"Shot {index} combines a locked/static camera with camera movement",
                "$.h3_prompt.detailed_description",
                severity="warning",
            )
        camera_terms = (
            r"(?:static(?:-off)?\s+(?:camera|shot)|locked(?:-off)?\s+(?:camera|shot)|"
            r"handheld|pan(?:s|ning)?|tilt(?:s|ing)?|track(?:s|ing)?|"
            r"push(?:es|ing)?\s+in|pull(?:s|ing)?\s+(?:back|out)|zoom(?:s|ing)?|"
            r"arc(?:s|ing)?|orbit(?:s|ing)?|reframe(?:s|ing)?)"
        )
        if re.search(rf"\b{camera_terms}\b.{{0,50}}\bor\b.{{0,50}}\b{camera_terms}\b", chunk, re.IGNORECASE):
            report.add(
                "PROMPT_CAMERA_ALTERNATIVE",
                f"Shot {index} offers multiple camera alternatives instead of one executable choice",
                "$.h3_prompt.detailed_description",
                severity="warning",
            )

    semantic_plan = payload.get("semantic_plan")
    if isinstance(semantic_plan, Mapping):
        subject_priority = semantic_plan.get("subject_priority")
        if (
            isinstance(subject_priority, Mapping)
            and subject_priority.get("mode") == "co_equal"
            and len(_strings(subject_priority.get("subject_ids"))) > 1
        ):
            summary_match = re.search(
                r"(?ms)^summary:\s*(.*?)(?=^retention_analysis:)",
                prompt,
            )
            summary_body = summary_match.group(1).lstrip() if summary_match else ""
            summary_body = re.sub(r"^\[[^\]\r\n]+\]\s*", "", summary_body)
            if re.match(r"<Subject\s+\d+>\s+is the primary creative focus", summary_body, re.IGNORECASE):
                report.add(
                    "PROMPT_COEQUAL_PRIORITY_CONTRADICTION",
                    "summary makes one subject dominant although semantic_plan marks the subjects co-equal",
                    "$.h3_prompt.summary",
                )

    if mode == "ref2va":
        definitions_match = re.search(
            r"(?ms)^subject_definitions:\s*(.*?)(?=^summary:)",
            prompt,
        )
        definitions = definitions_match.group(1) if definitions_match else ""
        subject_inventory = build_subject_inventory(payload)
        reference_inventory = build_reference_inventory(payload)
        subject_blocks: dict[str, str] = {}
        subject_matches = list(re.finditer(r"(?m)^(<Subject\s+\d+>)\s+is\s+", definitions))
        for index, match in enumerate(subject_matches):
            end = subject_matches[index + 1].start() if index + 1 < len(subject_matches) else len(definitions)
            subject_blocks[match.group(1)] = definitions[match.start():end]
        for subject in payload.get("subjects", []):
            if not isinstance(subject, Mapping):
                continue
            subject_label = subject_inventory.get(str(subject.get("subject_id", "")), "")
            block = subject_blocks.get(subject_label, "")
            for asset_id in _strings(subject.get("source_asset_ids")):
                reference_label = reference_inventory.get(asset_id, "")
                if reference_label and reference_label not in block:
                    report.add(
                        "SUBJECT_APPEARANCE_SOURCE_MISSING",
                        f"{subject_label} must cite appearance source {reference_label} in its definition",
                        "$.h3_prompt.subject_definitions",
                    )
            if len(_strings(subject.get("source_asset_ids"))) > 1 and len(re.findall(
                r"appearance\s+comes\s+exclusively\s+from",
                block,
                re.IGNORECASE,
            )) > 1:
                report.add(
                    "SUBJECT_APPEARANCE_AUTHORITY_CONTRADICTION",
                    f"{subject_label} assigns exclusive whole-appearance authority to multiple references; scope each source by attribute",
                    "$.h3_prompt.subject_definitions",
                )
    # Presentation differences remain visible to callers, but must not consume
    # another generation turn when references and required content are present.
    # Missing sections, invalid references and out-of-range timing still block.
    report.issues = [
        ValidationIssue(item.code, item.message, item.path, "warning")
        if item.code in _PROMPT_PRESENTATION_CODES else item
        for item in report.issues
    ]
    return report


def normalize_h3_prompt_transport(payload: Mapping[str, Any], prompt: str) -> str:
    """Repair format-only H3 transport defects without changing semantics.

    The final director remains responsible for all content.  This helper only
    canonicalizes exact section-name lines and moves an already-authored shot
    label in front of an already-authored timestamp on the same line.
    """
    mode = str(payload.get("task", {}).get("type", "")).lower()
    required = REF_SECTIONS if mode == "ref2va" else BASE_SECTIONS
    normalized_lines: list[str] = []
    for raw_line in str(prompt).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        heading_key = re.sub(r"[\s-]+", "_", stripped.rstrip(":").casefold())
        if heading_key in required and re.fullmatch(r"[A-Za-z_\- ]+:?", stripped):
            normalized_lines.append(f"{heading_key}:")
            continue
        shot_after_time = re.match(
            r"^At\s+(\d{2}:\d{2}\.\d{3}),?\s*\[Shot\s+(\d+)\]\s*(.*)$",
            stripped,
            re.IGNORECASE,
        )
        if shot_after_time:
            timestamp, shot_number, remainder = shot_after_time.groups()
            suffix = f" {remainder.strip()}" if remainder.strip() else ""
            if int(shot_number) == 1 and timestamp == "00:00.000":
                normalized_lines.append(f"[Shot 1]{suffix}".rstrip())
            else:
                normalized_lines.append(f"[Shot {int(shot_number)}] At {timestamp},{suffix}".rstrip())
            continue
        first_shot_zero = re.match(
            r"^\[Shot\s+1\]\s+At\s+00:00\.000,?\s*(.*)$",
            stripped,
            re.IGNORECASE,
        )
        if first_shot_zero:
            suffix = f" {first_shot_zero.group(1).strip()}" if first_shot_zero.group(1).strip() else ""
            normalized_lines.append(f"[Shot 1]{suffix}".rstrip())
            continue
        if re.match(r"^\[Shot\s+1\](?:\s|$)", stripped, re.IGNORECASE):
            # Models occasionally insert the zero timestamp after subject
            # setup prose instead of directly after the shot label.  It is
            # still format-only metadata and the first shot must omit it.
            first_shot_clean = re.sub(
                r"\s*\bAt\s+00:00\.000,?\s*",
                " ",
                stripped,
                count=1,
                flags=re.IGNORECASE,
            )
            normalized_lines.append(re.sub(r"\s{2,}", " ", first_shot_clean).strip())
            continue
        normalized_lines.append(raw_line)
    normalized = "\n".join(normalized_lines).strip() + "\n"
    if mode == "ref2va":
        task_types = _strings(payload.get("protocol", {}).get("summary_task_types"))
        expected_prefix = "[" + " + ".join(task_types) + "]"
        source_video_label = ""
        inventory = build_reference_inventory(payload)
        for relationship in payload.get("reference_relationships", []):
            if isinstance(relationship, Mapping) and relationship.get("relationship") == "source_video_edit":
                source_video_label = inventory.get(str(relationship.get("asset_id", "")), "")
                break
        summary_match = re.search(
            r"(?ms)(^summary:\s*)(.*?)(?=^retention_analysis:)",
            normalized,
        )
        if summary_match and expected_prefix != "[]":
            body = summary_match.group(2).strip()
            body = re.sub(r"^\[[^\]\r\n]+\]\s*", "", body)
            if "video editing" in task_types and source_video_label:
                official_opening = f"The target video is an edited version of {source_video_label}."
                if not body.startswith(official_opening):
                    body = re.sub(r"^This is (?:a )?video editing task:\s*", "", body, flags=re.IGNORECASE)
                    body = f"{official_opening} {body}".strip()
            replacement = f"summary:\n{expected_prefix} {body}\n\n"
            normalized = normalized[:summary_match.start()] + replacement + normalized[summary_match.end():]
    return normalized


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
