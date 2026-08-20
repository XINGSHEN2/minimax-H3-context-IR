"""Deterministically lower authoritative directives into Context-IR bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SUPPORTED_ROLES = {"identity", "outfit", "product", "motion", "voice", "music", "rhythm", "camera", "scene", "style", "first_frame", "last_frame"}


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def _append_unique(target: list[str], values: list[str]) -> None:
    known = {item.casefold() for item in target}
    for value in values:
        if value.casefold() not in known:
            target.append(value)
            known.add(value.casefold())


def _semantic_role(directive: Mapping[str, Any]) -> str:
    text = " ".join([str(directive.get("target", "")), *_strings(directive.get("scope"))]).casefold()
    dimensions = (
        ("first_frame", ("first frame", "opening frame")), ("last_frame", ("last frame", "ending frame")),
        ("identity", ("identity", "face", "hair", "body", "hand shape")),
        ("outfit", ("outfit", "clothing", "garment", "wardrobe")),
        ("camera", ("camera", "framing", "shot structure", "viewpoint")),
        ("rhythm", ("rhythm", "pacing", "cut timing", "edit timing")),
        ("motion", ("motion", "action", "movement", "performance", "gesture")),
        ("voice", ("voice", "dialogue", "narration", "speech")), ("music", ("music", "song", "melody")),
        ("scene", ("scene", "background", "environment", "visible text", "subtitle")),
        ("style", ("style", "lighting", "color grade", "aesthetic")),
        ("product", ("product", "appearance", "geometry", "material", "color", "pattern", "decoration")),
    )
    for role, markers in dimensions:
        if any(marker in text for marker in markers):
            return role
    return "scene"


def _new_binding_id(existing: set[str], role: str) -> str:
    base, suffix = f"b_directive_{role}", 2
    candidate = base
    while candidate in existing:
        candidate, suffix = f"{base}_{suffix}", suffix + 1
    existing.add(candidate)
    return candidate


def compile_directive_bindings(payload: dict[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    """Repair only facts directly provable from the source directive contract."""
    asset_ids = {str(item.get("asset_id", "")).strip() for item in source.get("assets", []) if isinstance(item, Mapping)}
    directives = [item for item in source.get("directives", []) if isinstance(item, Mapping)]
    directive_by_id = {str(item.get("directive_id", "")).strip(): item for item in directives}
    directive_ids = set(directive_by_id)
    bindings: list[dict[str, Any]] = []
    for item in payload.get("asset_bindings", []) if isinstance(payload.get("asset_bindings"), list) else []:
        if not isinstance(item, Mapping) or str(item.get("asset_id", "")).strip() not in asset_ids:
            continue
        binding = dict(item)
        binding["source_directive_ids"] = [value for value in _strings(binding.get("source_directive_ids")) if value in directive_ids]
        binding["role"] = binding.get("role") if binding.get("role") in SUPPORTED_ROLES else "scene"
        binding["inherit"], binding["exclude"] = _strings(binding.get("inherit")), _strings(binding.get("exclude"))
        bindings.append(binding)
    existing_ids = {str(item.get("binding_id", "")).strip() for item in bindings if str(item.get("binding_id", "")).strip()}
    by_asset: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        by_asset.setdefault(str(binding.get("asset_id", "")), []).append(binding)

    constraints = payload.setdefault("constraints", {})
    if not isinstance(constraints, dict):
        constraints, payload["constraints"] = {}, {}
    for key in ("preserve", "allow_change", "prohibit"):
        constraints[key] = _strings(constraints.get(key))
    for directive in directives:
        if str(directive.get("asset_id", "")).strip():
            continue
        operation = str(directive.get("operation", ""))
        destination = "prohibit" if operation == "exclude" else "allow_change" if operation == "may_change" else "preserve"
        _append_unique(constraints[destination], _strings(directive.get("scope")))

    for directive_id, directive in directive_by_id.items():
        asset_id = str(directive.get("asset_id", "")).strip()
        if not asset_id or asset_id not in asset_ids:
            continue
        role = _semantic_role(directive)
        candidates = [item for item in by_asset.get(asset_id, []) if directive_id in item["source_directive_ids"]]
        if not candidates:
            candidates = [item for item in by_asset.get(asset_id, []) if item.get("role") == role] or by_asset.get(asset_id, [])[:1]
        if not candidates:
            binding = {"binding_id": _new_binding_id(existing_ids, role), "asset_id": asset_id, "target": str(directive.get("target", "")).strip() or role, "role": role, "priority": str(directive.get("priority", "hard")), "source_directive_ids": [], "inherit": [], "exclude": []}
            bindings.append(binding)
            by_asset.setdefault(asset_id, []).append(binding)
            candidates = [binding]
        binding = candidates[0]
        if directive_id not in binding["source_directive_ids"]:
            binding["source_directive_ids"].append(directive_id)
        binding["priority"] = "hard" if directive.get("priority") == "hard" else binding.get("priority", "soft")
        destination = binding["exclude"] if directive.get("operation") == "exclude" else binding["inherit"]
        _append_unique(destination, _strings(directive.get("scope")))
    for binding in bindings:
        if not binding["inherit"]:
            binding["inherit"] = [f"{binding.get('role', 'scene')} reference scope"]
    payload["asset_bindings"] = bindings

    rules_by_id = {str(item.get("binding_id", "")): dict(item) for item in payload.get("isolation_rules", []) if isinstance(item, Mapping)}
    payload["isolation_rules"] = []
    for binding in bindings:
        rule = rules_by_id.get(str(binding["binding_id"]), {"binding_id": binding["binding_id"]})
        rule["allow"], rule["block"] = _strings(rule.get("allow")), _strings(rule.get("block"))
        _append_unique(rule["allow"], binding["inherit"])
        _append_unique(rule["block"], binding["exclude"])
        payload["isolation_rules"].append(rule)
    valid_ids = {str(item["binding_id"]) for item in bindings}
    for shot in payload.get("timeline", []):
        if isinstance(shot, dict):
            shot["binding_refs"] = [value for value in _strings(shot.get("binding_refs")) if value in valid_ids]
    focus = payload.get("creative_focus")
    if isinstance(focus, dict):
        focus["primary_binding_ids"] = [value for value in _strings(focus.get("primary_binding_ids")) if value in valid_ids]
    for subject in payload.get("subjects", []):
        if isinstance(subject, dict):
            subject["binding_ids"] = [value for value in _strings(subject.get("binding_ids")) if value in valid_ids]
    return payload
