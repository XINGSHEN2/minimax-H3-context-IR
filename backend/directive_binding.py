"""Deterministically lower authoritative directives into Context-IR bindings."""

from __future__ import annotations

import re
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


def _binding_applies_to_subject(binding: Mapping[str, Any], subject_id: str) -> bool:
    """Honor explicit machine-readable Subject IDs in a binding target.

    A shared reference may contain several people.  If the semantic model wrote
    ``subject_1 identity`` and ``subject_2 identity`` as separate targets, the
    compiler must not attach both bindings to both Subjects.  Bindings without
    an explicit Subject ID remain shared/scoped semantic guidance.
    """
    mentioned = set(re.findall(r"\bsubject_\d+\b", str(binding.get("target", "")), re.IGNORECASE))
    return not mentioned or subject_id.casefold() in {item.casefold() for item in mentioned}


def _semantic_role(directive: Mapping[str, Any]) -> str:
    text = " ".join([str(directive.get("target", "")), *_strings(directive.get("scope"))]).casefold()
    dimensions = (
        ("first_frame", ("first frame", "opening frame")), ("last_frame", ("last frame", "ending frame")),
        ("identity", ("identity", "face", "hair", "body", "hand shape")),
        ("outfit", ("outfit", "clothing", "garment", "wardrobe")),
        ("camera", ("camera", "framing", "shot structure", "viewpoint")),
        ("rhythm", ("rhythm", "pacing", "cut timing", "edit timing")),
        ("motion", ("motion", "action", "movement", "performance", "expression", "gesture")),
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
    # The simplified semantic contract intentionally makes binding_id optional.
    # Assign temporary deterministic IDs before directive lowering; the graph
    # compiler later treats these IDs as the stable public identifiers.
    for index, binding in enumerate(bindings, start=1):
        if str(binding.get("binding_id", "")).strip():
            continue
        candidate = f"binding_{index:03d}"
        suffix = index
        while candidate in existing_ids:
            suffix += 1
            candidate = f"binding_{suffix:03d}"
        binding["binding_id"] = candidate
        existing_ids.add(candidate)
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

    permission_only_bindings: set[str] = set()
    payload["change_permissions"] = []
    for directive_id, directive in directive_by_id.items():
        asset_id = str(directive.get("asset_id", "")).strip()
        if not asset_id or asset_id not in asset_ids:
            continue
        if directive.get("operation") == "may_change":
            payload["change_permissions"].append({
                "directive_id": directive_id, "asset_id": asset_id,
                "target": str(directive.get("target", "")),
                "scope": _strings(directive.get("scope")),
            })
            # Permission to animate a target is not evidence of source motion.
            scope = _strings(directive.get("scope"))
            target = str(directive.get("target", "")).strip() or asset_id
            _append_unique(constraints["allow_change"], [
                f"{asset_id}: {target}: {value}" for value in scope
            ])
            for binding in by_asset.get(asset_id, []):
                if directive_id not in binding["source_directive_ids"]:
                    continue
                retained = {
                    value.casefold()
                    for other_id in binding["source_directive_ids"]
                    for other in [directive_by_id.get(other_id, {})]
                    if other.get("operation") in {"preserve", "transfer", "replace"}
                    for value in _strings(other.get("scope"))
                }
                editable = {value.casefold() for value in scope} - retained
                binding["inherit"] = [value for value in binding["inherit"] if value.casefold() not in editable]
                binding["source_directive_ids"].remove(directive_id)
                permission_only_bindings.add(binding["binding_id"])
            continue
        role = _semantic_role(directive)
        # Every binding that explicitly cites a directive implements that
        # directive and therefore must carry its complete scope.  This matters
        # when one character-appearance directive intentionally governs
        # several bindings (for example, two people in the same reference).
        # For an uncited directive, retain the conservative single-candidate
        # fallback used to lower upstream natural-language instructions.
        candidates = [item for item in by_asset.get(asset_id, []) if directive_id in item["source_directive_ids"]]
        if not candidates:
            role_candidates = [item for item in by_asset.get(asset_id, []) if item.get("role") == role]
            candidates = role_candidates[:1] or by_asset.get(asset_id, [])[:1]
        if not candidates:
            binding = {"binding_id": _new_binding_id(existing_ids, role), "asset_id": asset_id, "target": str(directive.get("target", "")).strip() or role, "role": role, "priority": str(directive.get("priority", "hard")), "source_directive_ids": [], "inherit": [], "exclude": []}
            bindings.append(binding)
            by_asset.setdefault(asset_id, []).append(binding)
            candidates = [binding]
        for binding in candidates:
            if directive_id not in binding["source_directive_ids"]:
                binding["source_directive_ids"].append(directive_id)
            binding["priority"] = "hard" if directive.get("priority") == "hard" else binding.get("priority", "soft")
            destination = binding["exclude"] if directive.get("operation") == "exclude" else binding["inherit"]
            _append_unique(destination, _strings(directive.get("scope")))
    bindings = [binding for binding in bindings if not (
        binding["binding_id"] in permission_only_bindings
        and not binding["inherit"] and not binding["exclude"]
        and not binding["source_directive_ids"]
    )]
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


def derive_binding_graph(payload: dict[str, Any]) -> dict[str, Any]:
    """Build every cross-reference from the canonical asset binding list.

    The semantic model owns only the decisions in ``asset_bindings`` plus the
    high-level asset/subject references.  Binding IDs, isolation mirrors,
    subject binding IDs, focus binding IDs, and shot binding refs are compiler
    products.  Rebuilding them here removes several mutually dependent fields
    from the model contract while preserving the public Context-IR shape.
    """
    raw_bindings = payload.get("asset_bindings")
    if not isinstance(raw_bindings, list):
        raw_bindings = []
    bindings: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, item in enumerate(raw_bindings, start=1):
        if not isinstance(item, Mapping):
            continue
        binding = dict(item)
        supplied_id = str(binding.get("binding_id", "")).strip()
        binding_id = supplied_id if supplied_id and supplied_id not in used_ids else f"binding_{index:03d}"
        while binding_id in used_ids:
            index += 1
            binding_id = f"binding_{index:03d}"
        binding["binding_id"] = binding_id
        used_ids.add(binding_id)
        binding["inherit"] = _strings(binding.get("inherit"))
        binding["exclude"] = _strings(binding.get("exclude"))
        binding["source_directive_ids"] = _strings(binding.get("source_directive_ids"))
        bindings.append(binding)
    payload["asset_bindings"] = bindings

    by_asset: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        by_id[binding["binding_id"]] = binding
        by_asset.setdefault(str(binding.get("asset_id", "")), []).append(binding)

    # Isolation is a rendered mirror of canonical inherit/exclude semantics.
    payload["isolation_rules"] = [
        {
            "binding_id": binding["binding_id"],
            "allow": list(binding["inherit"]),
            "block": list(binding["exclude"]),
        }
        for binding in bindings
    ]

    compatible_roles = {
        # ``product`` covers worn accessories such as glasses, jewelry, shoes,
        # and a demonstrated product when the relationship explicitly links it
        # to the person Subject.
        "person": {"identity", "outfit", "product"},
        "product": {"product"},
        "environment": {"scene"},
        "animal": {"identity", "outfit"},
        "object": {"identity", "product", "scene"},
        "other": {"identity", "outfit", "product", "scene"},
    }
    relationship_assets: dict[str, list[str]] = {}
    for relationship in payload.get("reference_relationships", []):
        if not isinstance(relationship, Mapping):
            continue
        asset_id = str(relationship.get("asset_id", ""))
        for subject_id in _strings(relationship.get("subject_refs")):
            relationship_assets.setdefault(subject_id, []).append(asset_id)
    subject_bindings: dict[str, list[str]] = {}
    for subject in payload.get("subjects", []):
        if not isinstance(subject, dict):
            continue
        allowed = compatible_roles.get(str(subject.get("kind", "other")), compatible_roles["other"])
        # ``reference_relationships.subject_refs`` is the model's semantic
        # statement that a reference applies to this Subject.  When that same
        # asset owns a compatible appearance binding, it must also become an
        # explicit appearance source.  Keeping these two facts disconnected
        # previously let product/accessory references appear in retention while
        # disappearing from the official Subject definition.
        source_asset_ids = _strings(subject.get("source_asset_ids"))
        subject_id = str(subject.get("subject_id", ""))
        for asset_id in relationship_assets.get(subject_id, []):
            if asset_id in source_asset_ids:
                continue
            if any(
                binding.get("role") in allowed and _binding_applies_to_subject(binding, subject_id)
                for binding in by_asset.get(asset_id, [])
            ):
                source_asset_ids.append(asset_id)
        subject["source_asset_ids"] = source_asset_ids
        ids = [
            binding["binding_id"]
            for asset_id in source_asset_ids
            for binding in by_asset.get(asset_id, [])
            if binding.get("role") in allowed and _binding_applies_to_subject(binding, subject_id)
        ]
        # A reference relationship links structural guidance to an entity
        # without granting that asset appearance authority.
        ids.extend(
            binding["binding_id"]
            for asset_id in relationship_assets.get(subject_id, [])
            for binding in by_asset.get(asset_id, [])
            if binding.get("role") in {"motion", "camera", "rhythm", "style"}
            and _binding_applies_to_subject(binding, subject_id)
        )
        subject["binding_ids"] = list(dict.fromkeys(ids))
        subject_bindings[subject_id] = subject["binding_ids"]

    focus = payload.get("creative_focus")
    if isinstance(focus, dict):
        focus_ids: list[str] = []
        primary_subject_id = str(focus.get("primary_subject_id", ""))
        focus_ids.extend(subject_bindings.get(primary_subject_id, []))
        primary_asset_id = str(focus.get("primary_asset_id", ""))
        focus_ids.extend(binding["binding_id"] for binding in by_asset.get(primary_asset_id, []))
        focus["primary_binding_ids"] = list(dict.fromkeys(focus_ids))

    required_shots = set(_strings(focus.get("required_shot_ids"))) if isinstance(focus, Mapping) else set()
    primary_ids = _strings(focus.get("primary_binding_ids")) if isinstance(focus, Mapping) else []
    for shot in payload.get("timeline", []):
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("shot_id", ""))
        subject_refs = _strings(shot.get("subject_refs"))
        primary_subject_id = str(focus.get("primary_subject_id", "")) if isinstance(focus, Mapping) else ""
        if shot_id in required_shots and primary_subject_id and primary_subject_id not in subject_refs:
            subject_refs.append(primary_subject_id)
        shot["subject_refs"] = subject_refs
        refs: list[str] = []
        for subject_id in subject_refs:
            refs.extend(subject_bindings.get(subject_id, []))
        # ``asset_refs`` is the simple semantic hook for shot-specific motion,
        # camera, rhythm, style, audio, or scene guidance.
        for asset_id in _strings(shot.pop("asset_refs", [])):
            refs.extend(binding["binding_id"] for binding in by_asset.get(asset_id, []))
        if shot_id in required_shots:
            refs.extend(primary_ids)
        shot["binding_refs"] = list(dict.fromkeys(refs))
    return payload
