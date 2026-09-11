"""v20 source-request validation and H3 request serialization."""
from __future__ import annotations
import copy
import re
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
SOURCE_SCHEMA_VERSION = "context_request.v1"
SUPPORTED_TASKS = {"t2va", "i2va", "fl2va", "l2va", "ref2va"}
SUPPORTED_MEDIA_TYPES = {"image", "video", "audio"}
SUPPORTED_PRIORITIES = {"hard", "soft"}
DIRECTIVE_OPERATIONS = {"preserve", "replace", "transfer", "may_change", "exclude"}
DIRECTIVE_PROVENANCE = {"explicit_user", "confirmed_by_upstream", "product_default", "ir_completion"}
ASPECT_RATIO_PATTERN = re.compile(r"^(?:auto|[1-9]\d*:[1-9]\d*)$")

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

def normalize_source_request(source: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize v20 source requests into one contract."""
    payload = copy.deepcopy(dict(source))
    payload.setdefault("schema_version", SOURCE_SCHEMA_VERSION)
    if not isinstance(payload.get("directives"), list):
        payload["directives"] = []
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
    task = source.get("task")
    if not isinstance(task, Mapping):
        report.add("SOURCE_TASK_INVALID", "task must be an object", "$.task")
        task = {}
    if task.get("type") not in SUPPORTED_TASKS:
        report.add("SOURCE_TASK_TYPE_INVALID", "unsupported task type", "$.task.type")
    duration = task.get("duration_seconds")
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        report.add("SOURCE_DURATION_INVALID", "duration_seconds must be finite and positive", "$.task.duration_seconds")
    ratio = task.get("aspect_ratio")
    if not isinstance(ratio, str) or not ASPECT_RATIO_PATTERN.fullmatch(ratio):
        report.add("SOURCE_ASPECT_RATIO_INVALID", "aspect_ratio must be auto or W:H", "$.task.aspect_ratio")
    seen = set()
    for index, asset in enumerate(assets):
        path = f"$.assets[{index}]"
        if not isinstance(asset, Mapping):
            report.add("SOURCE_ASSET_INVALID", "asset must be an object", path)
            continue
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip() or asset_id in seen:
            report.add("SOURCE_ASSET_ID_INVALID", "asset_id must be nonempty and unique", path)
        else:
            seen.add(asset_id)
        if asset.get("media_type") not in SUPPORTED_MEDIA_TYPES:
            report.add("SOURCE_MEDIA_TYPE_INVALID", "unsupported media_type", path)
        if not isinstance(asset.get("uri"), str) or not asset["uri"].strip():
            report.add("SOURCE_ASSET_URI_INVALID", "asset uri is required", path)
    if task.get("type") in {"i2va", "l2va", "fl2va"}:
        expected = {"i2va": [0], "l2va": [-1], "fl2va": [-1, 0]}[task["type"]]
        frames = [a.get("frame_index") for a in assets if isinstance(a, Mapping)]
        valid = all(type(v) is int for v in frames) and sorted(frames) == expected
        valid = valid and all(isinstance(a, Mapping) and a.get("media_type") == "image" for a in assets)
        if not valid:
            report.add("SOURCE_KEYFRAMES_INVALID", "keyframe images require exact frame_index values for the selected task", "$.assets")
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
        conditions = []
        for asset in payload["assets"]:
            frame_index = asset.get("frame_index")
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
