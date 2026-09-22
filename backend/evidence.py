"""Prepare task-focused source evidence and stable reference numbering.

The full Qwen media analysis remains part of the compilation record. This
module builds the smaller view sent to the planning/writing model: shared facts
are lifted once, empty/default fields are removed, and entity details already
covered by a concise summary are not repeated as attributes.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable


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


def _normalise_words(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(value or "").lower())


def _covered_by_summary(summary: str, name: str, value: str) -> bool:
    """Return true only for strong literal coverage, avoiding semantic guesses."""
    haystack = _normalise_words(summary)
    value_text = _normalise_words(value)
    if len(value_text) >= 3 and value_text in haystack:
        return True
    value_tokens = _focus_tokens(value)
    summary_tokens = _focus_tokens(summary)
    if value_tokens and len(value_tokens & summary_tokens) / len(value_tokens) >= 0.72:
        return True
    name_text = _normalise_words(name)
    return len(name_text) >= 3 and len(value_text) < 3 and name_text in haystack


def _focus_tokens(value: str) -> set[str]:
    """Generate coarse English words and CJK bigrams for relevance ranking."""
    value = str(value or "").lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", value))
    for run in re.findall(r"[\u3400-\u9fff]+", value):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def _compact_entity(
    entity: dict[str, Any], *, focus_text: str = "", feature_budget: int = 16,
) -> dict[str, Any]:
    """Keep identity evidence without echoing the entity summary.

    The default budget stays generous for callers that use this helper alone.
    ``build_writer_evidence`` uses a smaller task-focused budget and ranks
    explicitly mentioned attributes first.
    """
    summary = _clip_text(entity.get("summary"), 220)
    focus = _focus_tokens(focus_text)
    candidates: list[tuple[int, float, int, str, dict[str, Any]]] = []
    order = 0
    for group, raw_features in (entity.get("attributes") or {}).items():
        if not isinstance(raw_features, list):
            continue
        for feature in raw_features:
            if not isinstance(feature, dict):
                continue
            source = str(feature.get("source", ""))
            confidence = float(feature.get("confidence", 0.0) or 0.0)
            if source == "unresolved" or confidence < 0.45:
                continue
            name = _clip_text(feature.get("name"), 100)
            value = _clip_text(feature.get("value"), 180)
            if not name and not value:
                continue
            if _covered_by_summary(summary, name, value):
                continue
            relevance = len((_focus_tokens(name + " " + value)) & focus)
            candidates.append((relevance, confidence, -order, str(group), {
                "name": name,
                "value": value,
                "confidence": confidence,
                "source": source,
            }))
            order += 1

    candidates.sort(key=lambda item: (item[0] > 0, item[0], item[1], item[2]), reverse=True)
    attributes: dict[str, list[dict[str, Any]]] = {}
    for _, _, _, group, feature in candidates[:feature_budget]:
        attributes.setdefault(group, []).append(feature)

    result = {
        "entity_id": entity.get("entity_id"),
        "category": _clip_text(entity.get("category"), 80),
        "subcategory": _clip_text(entity.get("subcategory"), 80),
        "summary": summary,
        "quantity": entity.get("quantity", {}),
        "attributes": attributes,
        "uncertainties": [_clip_text(value, 180) for value in entity.get("uncertainties", [])[:4]],
    }
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _compact_directives(raw: Iterable[Any]) -> list[dict[str, Any]]:
    """Retain directive meaning while dropping repeated bookkeeping defaults."""
    compact = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        directive = {
            "id": item.get("directive_id"),
            "asset_id": item.get("asset_id"),
            "operation": item.get("operation"),
            "target": _clip_text(item.get("target"), 140),
            "scope": [_clip_text(value, 220) for value in item.get("scope", []) if str(value).strip()],
        }
        if item.get("priority") not in (None, "", "hard"):
            directive["priority"] = item.get("priority")
        if item.get("provenance") not in (None, "", "explicit_user"):
            directive["provenance"] = item.get("provenance")
        compact.append({key: value for key, value in directive.items() if value not in (None, "", [], {})})

    # Collapse the common resolver pattern "same instruction for Picture 1..N".
    grouped_by_scope: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    remainder = []
    for item in compact:
        if not item.get("asset_id"):
            remainder.append(item)
            continue
        key = (
            item.get("operation"), tuple(item.get("scope", [])),
            item.get("priority"), item.get("provenance"),
        )
        grouped_by_scope.setdefault(key, []).append(item)
    collapsed = []
    for items in grouped_by_scope.values():
        if len(items) == 1:
            collapsed.append(items[0])
            continue
        first = items[0]
        collapsed.append(_clean_mapping({
            "ids": [item.get("id") for item in items],
            "asset_ids": [item.get("asset_id") for item in items],
            "targets": [item.get("target") for item in items],
            "operation": first.get("operation"),
            "scope": first.get("scope", []),
            "priority": first.get("priority"),
            "provenance": first.get("provenance"),
        }))

    # Collapse global exclusions/preservations that share the same target.
    grouped_global: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in remainder:
        key = (
            item.get("operation"), item.get("target"),
            item.get("priority"), item.get("provenance"),
        )
        grouped_global.setdefault(key, []).append(item)
    for items in grouped_global.values():
        if len(items) == 1:
            collapsed.append(items[0])
            continue
        first = items[0]
        collapsed.append(_clean_mapping({
            "ids": [item.get("id") for item in items],
            "operation": first.get("operation"),
            "target": first.get("target"),
            "scope": list(dict.fromkeys(
                scope for item in items for scope in item.get("scope", [])
            )),
            "priority": first.get("priority"),
            "provenance": first.get("provenance"),
        }))
    return collapsed


def _clean_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _compact_visible_text(raw: Iterable[Any]) -> list[dict[str, Any]]:
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append(_clean_mapping({
            "text": _clip_text(item.get("text"), 160),
            "legibility": item.get("legibility"),
            "region": _clip_text(item.get("region"), 120),
        }))
    return result


def _promote_shared_text(
    assets: list[dict[str, Any]], field: str, *, minimum_assets: int = 2,
) -> list[dict[str, Any]]:
    """Lift exactly repeated cross-asset observations into one shared block."""
    counts = Counter(
        str(asset.get("global_analysis", {}).get(field, "")).strip()
        for asset in assets
        if str(asset.get("global_analysis", {}).get(field, "")).strip()
    )
    shared = []
    for value, count in counts.items():
        if count < minimum_assets:
            continue
        asset_ids = []
        for asset in assets:
            global_analysis = asset.get("global_analysis", {})
            if str(global_analysis.get(field, "")).strip() == value:
                asset_ids.append(asset.get("asset_id"))
                global_analysis.pop(field, None)
        shared.append({"field": field, "asset_ids": asset_ids, "value": value})
    return shared


def _promote_shared_uncertainties(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(
        value for asset in assets for value in asset.get("uncertainties", []) if value
    )
    shared = []
    for value, count in counts.items():
        if count < 2:
            continue
        asset_ids = []
        for asset in assets:
            uncertainties = asset.get("uncertainties", [])
            if value in uncertainties:
                asset_ids.append(asset.get("asset_id"))
                asset["uncertainties"] = [item for item in uncertainties if item != value]
        shared.append({"asset_ids": asset_ids, "uncertainty": value})
    return shared


def build_writer_evidence(source: dict[str, Any]) -> dict[str, Any]:
    """Build the task-focused evidence view sent to the single writer call."""
    focus_text = "\n".join(str(source.get(key, "") or "") for key in ("user_request", "resolved_request"))
    analyses = {
        str(item.get("asset_id", "")): item
        for item in (source.get("perception") or {}).get("assets", [])
        if isinstance(item, dict)
    }
    assets = []
    for asset in source.get("assets", []):
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("asset_id", ""))
        analysis = analyses.get(asset_id, {})
        entities = [
            _compact_entity(entity, focus_text=focus_text, feature_budget=8)
            for entity in analysis.get("entities", []) if isinstance(entity, dict)
        ]
        events = []
        for event in analysis.get("events", []):
            if not isinstance(event, dict):
                continue
            events.append(_clean_mapping({
                "event_id": event.get("event_id"),
                "time_range": event.get("time_range", []),
                "entity_ids": event.get("entity_ids", []),
                "action": _clip_text(event.get("action"), 320),
                "transition_type": _clip_text(event.get("transition_type"), 80),
                "confidence": event.get("confidence", 0.0),
            }))
        relations = []
        for relation in analysis.get("relations", []):
            if not isinstance(relation, dict):
                continue
            relations.append(_clean_mapping({
                "relation_id": relation.get("relation_id"),
                "type": relation.get("type"),
                "subject_id": relation.get("subject_id"),
                "object_id": relation.get("object_id"),
                "anchor": _clip_text(relation.get("anchor"), 180),
                "confidence": relation.get("confidence", 0.0),
                "source": relation.get("source"),
            }))
        global_analysis = analysis.get("global_analysis", {})
        if not isinstance(global_analysis, dict):
            global_analysis = {}
        technical = analysis.get("technical", {})
        if not isinstance(technical, dict):
            technical = {}
        technical_view = _clean_mapping({
            "duration_seconds": technical.get("duration_seconds"),
            "camera": technical.get("camera"),
            "framing": technical.get("framing"),
            "scene_cut_candidates_seconds": technical.get("scene_cut_candidates_seconds", []),
            "quality_warnings": technical.get("quality_warnings", []),
        })
        assets.append(_clean_mapping({
            "asset_id": asset_id,
            "media_type": asset.get("media_type"),
            "label": asset.get("label"),
            "user_role": asset.get("user_role"),
            "summary": _clip_text(analysis.get("summary", ""), 280),
            "global_analysis": _clean_mapping({
                "scene": _clip_text(global_analysis.get("scene"), 260),
                "composition": _clip_text(global_analysis.get("composition"), 320),
                "framing_layers": global_analysis.get("framing_layers", [])[:4],
                "visible_text": _compact_visible_text(global_analysis.get("visible_text", [])[:8]),
            }),
            "entities": entities,
            "relations": relations,
            "events": events,
            "technical": technical_view,
            "evidence_coverage": analysis.get("evidence_coverage", [])[:12],
            "uncertainties": [_clip_text(value, 220) for value in analysis.get("uncertainties", [])[:8]],
        }))

    shared_visual_context = []
    for field in ("scene", "composition"):
        shared_visual_context.extend(_promote_shared_text(assets, field))
    shared_uncertainties = _promote_shared_uncertainties(assets)
    shared_text = " ".join(item["value"] for item in shared_visual_context)
    for asset in assets:
        global_analysis = asset.get("global_analysis", {})
        if shared_text and global_analysis.get("framing_layers"):
            kept_layers = []
            for layer in global_analysis["framing_layers"]:
                if not isinstance(layer, dict):
                    continue
                description = str(layer.get("description", ""))
                tokens = _focus_tokens(description)
                shared_tokens = _focus_tokens(shared_text)
                coverage = len(tokens & shared_tokens) / len(tokens) if tokens else 0.0
                if coverage < 0.72:
                    kept_layers.append(_clean_mapping({
                        "description": _clip_text(description, 180),
                        "coverage": layer.get("coverage"),
                    }))
            if kept_layers:
                global_analysis["framing_layers"] = kept_layers
            else:
                global_analysis.pop("framing_layers", None)
        if not asset.get("global_analysis"):
            asset.pop("global_analysis", None)
        if not asset.get("uncertainties"):
            asset.pop("uncertainties", None)

    result = {
        "user_request": source.get("user_request", ""),
        "task": source.get("task", {}),
        "directives": _compact_directives(source.get("directives", [])),
        "completion_policy": source.get("completion_policy", {}),
        "reference_registry": _reference_registry(source),
        "shared_visual_context": shared_visual_context,
        "shared_uncertainties": shared_uncertainties,
        "assets": assets,
    }
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}
