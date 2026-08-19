#!/usr/bin/env python3
"""Provider-neutral Context-IR contract, validator, and H3 renderer."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


IR_SCHEMA_VERSION = "0.1.0"
MEDIA_ANALYSIS_SCHEMA_VERSION = "media_analysis.v2"
LEGACY_MEDIA_ANALYSIS_SCHEMA_VERSIONS = {"media_analysis.v1"}
SUPPORTED_TASKS = {"t2va", "i2va", "fl2va", "l2va", "ref2va"}
SUPPORTED_MEDIA_TYPES = {"image", "video", "audio"}
SUPPORTED_BINDING_ROLES = {
    "identity", "outfit", "product", "motion", "voice", "music", "rhythm",
    "camera", "scene", "style", "first_frame", "last_frame",
}
SUPPORTED_PRIORITIES = {"hard", "soft"}
SUPPORTED_ASSET_AUTHORITIES = {"edit_base", "authoritative_content", "scoped_reference"}
SUPPORTED_ATTRIBUTE_DECISIONS = {"cite", "transfer", "discard"}
SUPPORTED_EVIDENCE_BASES = {"visible", "inferred", "user_instruction", "asset_role"}
SUPPORTED_FOCUS_LEVELS = {"hero", "primary", "supporting", "background"}
SUPPORTED_ATTENTION_ROLES = {"primary", "supporting", "background"}
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
            blocks_product_geometry = any("product geometry" in item for item in blocked_lower)
            blocks_logo = any("logo" in item for item in blocked_lower)
            if not (blocks_identity and blocks_product_geometry and blocks_logo):
                report.add(
                    "STYLE_ISOLATION_INCOMPLETE",
                    "style references must exclude identity, product geometry, and logo",
                    path,
                )

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

    decision_plan = payload.get("decision_plan")
    if decision_plan is not None:
        if not isinstance(decision_plan, Mapping):
            report.add("DECISION_PLAN_INVALID", "decision_plan must be an object", "$.decision_plan")
        else:
            hierarchy = decision_plan.get("intent_hierarchy")
            if not isinstance(hierarchy, Mapping):
                report.add("INTENT_HIERARCHY_MISSING", "decision_plan.intent_hierarchy is required", "$.decision_plan.intent_hierarchy")
            else:
                for key in ("explicit_goal", "intended_outcome"):
                    if not str(hierarchy.get(key, "")).strip():
                        report.add("INTENT_HIERARCHY_FIELD_MISSING", f"intent_hierarchy.{key} is required", f"$.decision_plan.intent_hierarchy.{key}")
                for key in ("execution_means", "non_authorized_inferences"):
                    if not isinstance(hierarchy.get(key), list):
                        report.add("INTENT_HIERARCHY_LIST_INVALID", f"intent_hierarchy.{key} must be an array", f"$.decision_plan.intent_hierarchy.{key}")

            authorities = decision_plan.get("asset_authority")
            authority_assets: set[str] = set()
            if not isinstance(authorities, list):
                report.add("ASSET_AUTHORITY_INVALID", "decision_plan.asset_authority must be an array", "$.decision_plan.asset_authority")
                authorities = []
            for index, authority in enumerate(authorities):
                path = f"$.decision_plan.asset_authority[{index}]"
                if not isinstance(authority, Mapping):
                    report.add("ASSET_AUTHORITY_ENTRY_INVALID", "asset authority must be an object", path)
                    continue
                asset_id = str(authority.get("asset_id", ""))
                if asset_id not in asset_ids or asset_id in authority_assets:
                    report.add("ASSET_AUTHORITY_COVERAGE_INVALID", "each asset needs exactly one authority classification", path)
                authority_assets.add(asset_id)
                if authority.get("authority") not in SUPPORTED_ASSET_AUTHORITIES:
                    report.add("ASSET_AUTHORITY_TYPE_INVALID", f"authority must use {sorted(SUPPORTED_ASSET_AUTHORITIES)}", path)
                if not _strings(authority.get("controlled_dimensions")):
                    report.add("ASSET_AUTHORITY_DIMENSIONS_EMPTY", "controlled_dimensions must name at least one dimension", path)
                if not isinstance(authority.get("secondary_dimensions"), list):
                    report.add("ASSET_AUTHORITY_SECONDARY_INVALID", "secondary_dimensions must be an array", path)
            if authority_assets != asset_ids:
                report.add("ASSET_AUTHORITY_COVERAGE", f"asset authority must cover exactly these assets: {sorted(asset_ids)}", "$.decision_plan.asset_authority")

            decisions = decision_plan.get("attribute_decisions")
            if not isinstance(decisions, list):
                report.add("ATTRIBUTE_DECISIONS_INVALID", "decision_plan.attribute_decisions must be an array", "$.decision_plan.attribute_decisions")
                decisions = []
            decision_assets: set[str] = set()
            accepted_attributes: dict[str, set[str]] = {}
            for index, decision in enumerate(decisions):
                path = f"$.decision_plan.attribute_decisions[{index}]"
                if not isinstance(decision, Mapping):
                    report.add("ATTRIBUTE_DECISION_INVALID", "attribute decision must be an object", path)
                    continue
                asset_id = str(decision.get("asset_id", ""))
                if asset_id not in asset_ids:
                    report.add("ATTRIBUTE_DECISION_ASSET_UNKNOWN", "attribute decision references an unknown asset", path)
                decision_assets.add(asset_id)
                attribute = str(decision.get("attribute", "")).strip()
                if not attribute:
                    report.add("ATTRIBUTE_DECISION_ATTRIBUTE_MISSING", "attribute must name one atomic property", path)
                action = decision.get("decision")
                if action not in SUPPORTED_ATTRIBUTE_DECISIONS:
                    report.add("ATTRIBUTE_DECISION_TYPE_INVALID", f"decision must use {sorted(SUPPORTED_ATTRIBUTE_DECISIONS)}", path)
                if decision.get("priority") not in SUPPORTED_PRIORITIES:
                    report.add("ATTRIBUTE_DECISION_PRIORITY_INVALID", "priority must be hard or soft", path)
                if decision.get("evidence_basis") not in SUPPORTED_EVIDENCE_BASES:
                    report.add("ATTRIBUTE_DECISION_EVIDENCE_INVALID", f"evidence_basis must use {sorted(SUPPORTED_EVIDENCE_BASES)}", path)
                target_subject = str(decision.get("target_subject_id", "")).strip()
                if target_subject and target_subject not in subject_ids:
                    report.add("ATTRIBUTE_DECISION_SUBJECT_UNKNOWN", f"unknown target subject {target_subject}", path)
                if action == "transfer" and not target_subject:
                    report.add("ATTRIBUTE_TRANSFER_TARGET_MISSING", "transfer decisions require target_subject_id", path)
                if action in {"cite", "transfer"} and attribute:
                    accepted_attributes.setdefault(asset_id, set()).add(attribute.lower())
                if not str(decision.get("rationale", "")).strip():
                    report.add("ATTRIBUTE_DECISION_RATIONALE_MISSING", "rationale is required", path)
            if asset_ids and decision_assets != asset_ids:
                report.add("ATTRIBUTE_DECISION_COVERAGE", "every asset needs at least one cite, transfer, or discard decision", "$.decision_plan.attribute_decisions")
            for index, binding in enumerate(bindings):
                if not isinstance(binding, Mapping) or binding.get("priority") != "hard":
                    continue
                accepted = accepted_attributes.get(str(binding.get("asset_id")), set())
                for attribute in _strings(binding.get("inherit")):
                    if attribute.lower() not in accepted:
                        report.add("HARD_BINDING_DECISION_MISSING", f"hard inherited attribute '{attribute}' needs a matching cite or transfer decision", f"$.asset_bindings[{index}].inherit")

            attention = decision_plan.get("attention_budget")
            if not isinstance(attention, list) or not attention:
                report.add("ATTENTION_BUDGET_MISSING", "decision_plan.attention_budget must be non-empty", "$.decision_plan.attention_budget")
            else:
                attention_subjects: set[str] = set()
                total_weight = 0.0
                primary_attention: list[str] = []
                for index, item in enumerate(attention):
                    path = f"$.decision_plan.attention_budget[{index}]"
                    if not isinstance(item, Mapping):
                        report.add("ATTENTION_ENTRY_INVALID", "attention entry must be an object", path)
                        continue
                    subject_id = str(item.get("subject_id", ""))
                    if subject_id not in subject_ids or subject_id in attention_subjects:
                        report.add("ATTENTION_SUBJECT_INVALID", "each subject may appear once and must be defined", path)
                    attention_subjects.add(subject_id)
                    weight = item.get("weight")
                    if not _number(weight) or float(weight) <= 0:
                        report.add("ATTENTION_WEIGHT_INVALID", "attention weight must be positive", path)
                    else:
                        total_weight += float(weight)
                    if item.get("role") not in SUPPORTED_ATTENTION_ROLES:
                        report.add("ATTENTION_ROLE_INVALID", f"attention role must use {sorted(SUPPORTED_ATTENTION_ROLES)}", path)
                    if item.get("role") == "primary":
                        primary_attention.append(subject_id)
                    if not _strings(item.get("requirements")):
                        report.add("ATTENTION_REQUIREMENTS_EMPTY", "attention requirements must be non-empty", path)
                if attention_subjects != subject_ids:
                    report.add("ATTENTION_SUBJECT_COVERAGE", "attention budget must cover every subject exactly once", "$.decision_plan.attention_budget")
                if abs(total_weight - 1.0) > EPSILON:
                    report.add("ATTENTION_WEIGHT_TOTAL", f"attention weights must sum to 1.0, got {total_weight:g}", "$.decision_plan.attention_budget")
                primary_focus_id = str(payload.get("creative_focus", {}).get("primary_subject_id", ""))
                if primary_attention != [primary_focus_id]:
                    report.add("ATTENTION_PRIMARY_MISMATCH", "exactly one primary attention entry must match creative_focus.primary_subject_id", "$.decision_plan.attention_budget")

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
            if decision_plan is not None:
                if not str(shot.get("purpose", "")).strip():
                    report.add("SHOT_PURPOSE_MISSING", "decision-planned shots require a distinct purpose", path)
                if shot.get("focus_level") not in SUPPORTED_FOCUS_LEVELS:
                    report.add("SHOT_FOCUS_LEVEL_INVALID", f"focus_level must use {sorted(SUPPORTED_FOCUS_LEVELS)}", path)
                if not isinstance(shot.get("reference_transfer"), list):
                    report.add("SHOT_REFERENCE_TRANSFER_INVALID", "reference_transfer must be an array", path)
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
            if decision_plan is not None and required_shot_ids:
                focus_levels = {
                    str(shot.get("focus_level", ""))
                    for shot in timeline
                    if str(shot.get("shot_id", "")) in required_shot_ids
                }
                if not focus_levels.intersection({"hero", "primary"}):
                    report.add("FOCUS_SHOT_PROMINENCE_MISSING", "at least one required focus shot must be hero or primary", "$.timeline")
        for subject in subjects:
            if not isinstance(subject, Mapping):
                continue
            declared = set(_strings(subject.get("appearance_shot_ids")))
            actual = {str(shot.get("shot_id", "")) for shot in timeline if subject.get("subject_id") in _strings(shot.get("subject_refs"))}
            if declared != actual:
                report.add("SUBJECT_APPEARANCE_MISMATCH", f"{subject.get('subject_id')} appearance_shot_ids must match timeline subject_refs", "$.subjects")

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
    """Apply non-negotiable safety blocks after semantic model decisions."""
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
    payload.setdefault("protocol", {"rewrite_language": "English", "preserve_source_language_for": ["dialogue", "lyrics", "visible scene text"]})
    payload.setdefault("runtime", {
        "perception_provider": {"provider": "gitee-qwen3-vl", "model": "Qwen3-VL-30B-A3B-Instruct", "options": {}},
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


def build_subject_inventory(payload: Mapping[str, Any]) -> dict[str, str]:
    """Assign stable official H3 Subject labels from validated entity order."""
    return {
        str(subject["subject_id"]): f"<Subject {index}>"
        for index, subject in enumerate(payload.get("subjects", []), start=1)
    }


def _shot_text(shot: Mapping[str, Any], shot_number: int, subject_inventory: Mapping[str, str] | None = None) -> str:
    subject_inventory = subject_inventory or {}
    labels = [subject_inventory[item] for item in _strings(shot.get("subject_refs")) if item in subject_inventory]
    subject_opening = ""
    if labels:
        subject_opening = ", ".join(labels) + (" are visible. " if len(labels) > 1 else " is visible. ")
    purpose = str(shot.get("purpose", "")).strip()
    focus_level = str(shot.get("focus_level", "")).strip()
    opening = subject_opening + str(shot["event"])
    pieces = [opening]
    if purpose:
        pieces.append(f"purpose: {purpose}")
    if focus_level:
        pieces.append(f"visual emphasis: {focus_level}")
    pieces.extend(
        f"{key}: {shot[key]}"
        for key in ("action", "camera", "lighting", "transition")
        if shot.get(key)
    )
    transfers = _strings(shot.get("reference_transfer"))
    if transfers:
        pieces.append("reference transfer: " + ", ".join(transfers))
    prefix = f"[Shot {shot_number}]"
    if shot_number != 1:
        prefix += f" At {_format_timestamp(float(shot['start_seconds']))},"
    return prefix + " " + "; ".join(pieces)


def _sound_sections(payload: Mapping[str, Any]) -> tuple[str, str]:
    audio = payload["audio_plan"]
    if not payload["task"]["generate_audio"]:
        return "N/A", "N/A"
    soundscape = "; ".join(
        f"{key}: {audio[key]}"
        for key in ("voice", "sound_effects", "ambient_sound", "sync_rules")
    )
    music = str(audio["music"]).strip()
    if not music or music.lower() in {"none", "no", "false", "not requested"}:
        music = "N/A"
    return soundscape, music


def _constraint_text(payload: Mapping[str, Any]) -> str:
    """Compile the IR's edit boundary into executable prompt language."""
    constraints = payload["constraints"]
    parts = []
    preserve = _strings(constraints.get("preserve"))
    allow_change = _strings(constraints.get("allow_change"))
    prohibit = _strings(constraints.get("prohibit"))
    if preserve:
        parts.append("Must preserve: " + ", ".join(preserve))
    if allow_change:
        parts.append("May change only as requested: " + ", ".join(allow_change))
    if prohibit:
        parts.append("Must not introduce: " + ", ".join(prohibit))
    return "; ".join(parts)


def _attention_text(payload: Mapping[str, Any], subject_inventory: Mapping[str, str] | None = None) -> str:
    """Compile the internal attention allocation into concise executable emphasis."""
    plan = payload.get("decision_plan")
    if not isinstance(plan, Mapping):
        return ""
    subject_inventory = subject_inventory or {}
    entries = []
    for item in plan.get("attention_budget", []):
        if not isinstance(item, Mapping):
            continue
        subject_id = str(item.get("subject_id", ""))
        label = subject_inventory.get(subject_id, subject_id)
        requirements = "; ".join(_strings(item.get("requirements")))
        entries.append(
            f"{label} ({item.get('role')}, attention {float(item.get('weight', 0)):.2f}): {requirements}"
        )
    return "Attention allocation: " + " | ".join(entries) if entries else ""


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
    attention_text = _attention_text(payload)
    description = ". ".join(part for part in (focus_text, attention_text, constraint_text, opening, " ".join(shots)) if part)
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
    for subject in payload["subjects"]:
        label = subject_inventory[subject["subject_id"]]
        sources = [inventory[item] for item in _strings(subject.get("source_asset_ids")) if item in inventory]
        source_text = " in " + ", ".join(sources) if sources else ""
        subjects.append(f"{label} is {str(subject['name']).strip().rstrip('.')}{source_text}, {str(subject['description']).strip().rstrip('.')}.")
        shots = ", ".join(f"[Shot {int(item)}]" for item in _strings(subject.get("appearance_shot_ids")))
        appearance = f" (appears in {shots})" if shots else ""
        retention.append(f"{label}{appearance}: {subject['retention_mode']} - {str(subject['retention_description']).strip().rstrip('.')}.")
    for relationship in payload["reference_relationships"]:
        label = inventory[relationship["asset_id"]]
        linked = [subject_inventory[item] for item in _strings(relationship.get("subject_refs")) if item in subject_inventory]
        link_text = f" It applies to {', '.join(linked)}." if linked else ""
        definition = str(relationship['definition']).strip().rstrip('.')
        if definition.lower().startswith("is "):
            definition = definition[3:]
        subjects.append(f"{label} is {definition}.{link_text}")
        retention.append(f"{label}: {relationship['retention_mode']} - {str(relationship['retention_description']).strip().rstrip('.')}.")
    intent = payload["intent"]
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
    focus_summary = f"{primary_subject_label} is the primary creative focus: {focus_objective}" if primary_subject_label else f"Primary creative objective: {focus_objective}"
    summary = (
        f"{prefix} {edit_opening}"
        f"{focus_summary}. "
        f"{str(intent.get('resolved_request') or intent['user_request']).strip().rstrip('.')}. Target style: {task.get('style', '')}. "
        f"Audio generation: {task['generate_audio']}."
    )
    details = []
    generation = payload["generation_description"]
    constraint_text = _constraint_text(payload)
    if constraint_text:
        details.append(constraint_text)
    focus_requirements = "; ".join(_strings(focus.get("presentation_requirements")))
    details.append(f"Primary visual focus: {focus_objective}. Presentation requirements: {focus_requirements.rstrip('.')}.")
    attention_text = _attention_text(payload, subject_inventory)
    if attention_text:
        details.append(attention_text + ".")
    details.append("; ".join(f"{key}: {generation[key]}" for key in ("cinematography", "lighting", "materials", "performance", "continuity")))
    details.extend(_shot_text(shot, index, subject_inventory) for index, shot in enumerate(payload["timeline"], start=1))
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
    language_probe = prompt
    perception = payload.get("perception")
    if isinstance(perception, Mapping):
        for asset in perception.get("assets", []):
            if not isinstance(asset, Mapping):
                continue
            technical = asset.get("technical")
            if isinstance(technical, Mapping):
                for literal in _strings(technical.get("visible_text")):
                    language_probe = language_probe.replace(literal, "")
            transcript = str(asset.get("transcript", "")).strip()
            if transcript:
                language_probe = language_probe.replace(transcript, "")
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
