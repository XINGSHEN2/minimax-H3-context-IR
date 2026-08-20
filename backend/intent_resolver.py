"""User-intent resolution before multimodal perception.

This stage decides what each asset must be inspected for.  It never claims to
see media content; visual facts remain the perception provider's responsibility.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Mapping

from backend.context_ir import normalize_source_request, validate_source_request


_DIMENSION_MARKERS = (
    ("first_frame", ("first frame", "opening frame", "start frame")),
    ("last_frame", ("last frame", "closing frame", "ending frame")),
    ("identity", ("identity", "face", "facial", "hair", "body shape", "expression", "人物身份", "人脸", "发型", "表情")),
    ("outfit", ("outfit", "clothing", "garment", "wardrobe", "服装", "穿着")),
    ("camera", ("camera", "composition", "framing", "shot scale", "viewpoint", "运镜", "构图", "景别")),
    ("rhythm", ("rhythm", "pacing", "shot order", "cut timing", "edit timing", "temporal structure", "剪辑", "节奏", "镜头顺序", "时间结构")),
    ("motion", ("motion", "action", "movement", "performance", "gesture", "walking path", "动作", "手势", "路径")),
    ("voice", ("voice", "dialogue", "narration", "speech", "sync audio", "同期声", "对白", "人声")),
    ("music", ("music", "song", "melody", "音乐", "歌曲")),
    ("scene", ("scene", "background", "environment", "store", "shelf", "basket", "sign", "visible text", "subtitle", "场景", "背景", "店铺", "货架", "购物篮", "招牌", "字幕")),
    ("style", ("style", "lighting", "color grade", "aesthetic", "风格", "灯光", "调色")),
    ("product", ("product", "appearance", "geometry", "material", "color", "pattern", "decoration", "nail", "商品", "外观", "材质", "颜色", "图案", "甲片")),
)


def _scope_dimension(value: str) -> str:
    text = value.casefold()
    for dimension, markers in _DIMENSION_MARKERS:
        if any(marker in text for marker in markers):
            return dimension
    return "other"


def _atomize_added_directives(directives: list[Any], supplied_count: int) -> list[Any]:
    """Split model-added mixed-control directives while preserving supplied directives."""
    result = copy.deepcopy(directives[:supplied_count])
    used_ids = {
        str(item.get("directive_id", "")).strip()
        for item in result
        if isinstance(item, Mapping)
    }
    next_id = 1

    def new_id() -> str:
        nonlocal next_id
        while f"d_{next_id}" in used_ids:
            next_id += 1
        value = f"d_{next_id}"
        used_ids.add(value)
        next_id += 1
        return value

    for item in directives[supplied_count:]:
        if not isinstance(item, Mapping):
            result.append(item)
            continue
        scopes = [str(value).strip() for value in item.get("scope", []) if str(value).strip()]
        groups: dict[str, list[str]] = {}
        for scope in scopes:
            groups.setdefault(_scope_dimension(scope), []).append(scope)
        if len(groups) <= 1:
            directive = copy.deepcopy(dict(item))
            identifier = str(directive.get("directive_id", "")).strip()
            if not identifier or identifier in used_ids:
                directive["directive_id"] = new_id()
            else:
                used_ids.add(identifier)
            result.append(directive)
            continue
        for dimension, grouped_scopes in groups.items():
            directive = copy.deepcopy(dict(item))
            directive["directive_id"] = new_id()
            directive["target"] = f"{str(item.get('target', '')).strip()} [{dimension}]".strip()
            directive["scope"] = grouped_scopes
            result.append(directive)
    return result


def build_intent_prompt(source: Mapping[str, Any]) -> str:
    manifest = [{k: item.get(k) for k in ("asset_id", "media_type", "label", "user_role", "original_filename")}
                for item in source.get("assets", []) if isinstance(item, Mapping)]
    return f"""You are the intent-resolution stage of a multimodal video compiler.
Read only the user's language and asset manifest. Do not claim to see, hear, OCR,
identify, or classify media contents. Convert explicit user requirements into
locked directives, and write a targeted perception plan telling a VLM what
visible evidence to inspect.

Rules:
- Preserve every supplied directive byte-for-byte; never rewrite or delete it.
- Add directives only for explicit user requirements. Do not turn guesses into locks.
- Every newly added directive must control exactly one semantic dimension. Split
  identity, outfit, product, motion, camera, rhythm, scene, voice, music, style,
  first-frame, and last-frame requirements into separate directives. Never put
  attributes from several of these dimensions into one scope array.
- Use only asset_id values present in the manifest.
- Separate user-claimed semantics (for example a claimed product category) from
  visual evidence. Put such claims in user_claimed_category, never as a VLM fact.
- role describes authority/use, not observed content. Prefer general values such
  as authoritative_product_appearance, identity_reference, motion_reference,
  camera_structure_reference, edit_base, scene_reference, or audio_reference.
- analyze contains concrete visible properties/questions relevant to the request.
- do_not_infer blocks likely contamination and unsupported semantic conclusions.
- If the request is ambiguous, use conservative completion and record an open
  question; do not fabricate a business-specific interpretation.
- Return exactly one JSON object, without Markdown.

Required shape:
{{
  "resolved_request": "faithful concise operational restatement",
  "directives": [{{"directive_id":"d_1","asset_id":"image_1 or empty","target":"stable semantic target","operation":"preserve|replace|transfer|may_change|exclude","scope":["controlled attribute"],"priority":"hard|soft","provenance":"explicit_user"}}],
  "completion_policy": {{"technical":true,"conservative_semantic":true,"creative":false}},
  "perception_plan": {{"assets":[{{"asset_id":"image_1","role":"authority/use role","user_claimed_category":"or empty","analyze":["visible property or relation"],"do_not_infer":["unsupported conclusion"]}}]}},
  "open_questions": []
}}

Supplied directives (immutable):
{json.dumps(source.get('directives', []), ensure_ascii=False, indent=2)}

User request:
{source.get('user_request', '')}

Asset manifest:
{json.dumps(manifest, ensure_ascii=False, indent=2)}
""".strip()


def validate_intent_resolution(payload: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("intent resolver response must be an object")
    asset_ids = {str(item.get("asset_id", "")) for item in source.get("assets", []) if isinstance(item, Mapping)}
    supplied = copy.deepcopy(source.get("directives", []))
    directives = payload.get("directives")
    if not isinstance(directives, list):
        raise ValueError("intent resolver directives must be an array")
    if directives[:len(supplied)] != supplied:
        raise ValueError("intent resolver changed or reordered supplied directives")
    directives = _atomize_added_directives(directives, len(supplied))
    plan = payload.get("perception_plan")
    if not isinstance(plan, Mapping) or not isinstance(plan.get("assets"), list):
        raise ValueError("intent resolver perception_plan.assets must be an array")
    planned: set[str] = set()
    normalized_plan = []
    for index, item in enumerate(plan["assets"]):
        if not isinstance(item, Mapping):
            raise ValueError(f"perception_plan.assets[{index}] must be an object")
        asset_id = str(item.get("asset_id", "")).strip()
        if asset_id not in asset_ids or asset_id in planned:
            raise ValueError(f"invalid or duplicate perception-plan asset_id: {asset_id}")
        planned.add(asset_id)
        normalized_plan.append({
            "asset_id": asset_id,
            "role": str(item.get("role", "reference")).strip() or "reference",
            "user_claimed_category": str(item.get("user_claimed_category", "")).strip(),
            "analyze": [str(v).strip() for v in item.get("analyze", []) if str(v).strip()],
            "do_not_infer": [str(v).strip() for v in item.get("do_not_infer", []) if str(v).strip()],
        })
    # Every asset must receive a plan, even when the model omitted an irrelevant one.
    for asset_id in sorted(asset_ids - planned):
        normalized_plan.append({"asset_id": asset_id, "role": "reference", "user_claimed_category": "", "analyze": ["generation-relevant visible evidence"], "do_not_infer": ["unsupported identity, brand, function, or user intent"]})
    resolved = normalize_source_request({
        **copy.deepcopy(dict(source)),
        "resolved_request": str(payload.get("resolved_request", "")).strip(),
        "directives": copy.deepcopy(directives),
        "completion_policy": copy.deepcopy(payload.get("completion_policy") or source.get("completion_policy")),
        "open_questions": [str(v).strip() for v in payload.get("open_questions", []) if str(v).strip()],
    })
    report = validate_source_request(resolved)
    if not report.passed:
        raise ValueError(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return {"source": resolved, "perception_plan": {"assets": normalized_plan}}


def resolve_intent(source: Mapping[str, Any], invoke: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    """Resolve intent with the configured reasoning provider and validate strictly."""
    return validate_intent_resolution(invoke(build_intent_prompt(source)), source)
