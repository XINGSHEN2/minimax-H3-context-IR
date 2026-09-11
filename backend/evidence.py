"""Prepare source evidence and stable reference numbering for the v20 writer."""
import copy
from typing import Any

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

def build_writer_evidence(source: dict[str, Any]) -> dict[str, Any]:
    """Keep writer evidence useful without resending the full perception tree."""
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
