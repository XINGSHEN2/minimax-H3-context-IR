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
    ("identity", ("identity", "face", "facial structure", "hair", "body shape", "人物身份", "人脸", "面部结构", "发型")),
    ("outfit", ("outfit", "clothing", "garment", "wardrobe", "服装", "穿着")),
    ("camera", ("camera", "composition", "framing", "shot scale", "viewpoint", "运镜", "构图", "景别")),
    ("rhythm", ("rhythm", "pacing", "shot order", "cut timing", "edit timing", "temporal structure", "剪辑", "节奏", "镜头顺序", "时间结构")),
    ("motion", ("motion", "action", "movement", "performance", "expression", "gesture", "walking path", "动作", "表情", "表演", "手势", "路径")),
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
- Resolve a generic character phrase such as "人物", "characters", or "the
  performers" against the whole described interaction. If several characters
  participate in a reciprocal action and the user does not explicitly name only
  one, target all participating characters rather than arbitrarily selecting the
  first actor mentioned.
- Dynamic facial expression and performance timing transferred from a video are
  motion/performance controls, not identity controls. Identity covers stable face,
  hair, and body appearance.
- Every newly added directive must control exactly one semantic dimension. Split
  identity, outfit, product, motion, camera, rhythm, scene, voice, music, style,
  first-frame, and last-frame requirements into separate directives. Never put
  attributes from several of these dimensions into one scope array.
- Use an asset_id from the manifest only when that asset is the source of the
  controlled attribute. For instructions about the target video itself, use
  asset_id="" and state the affected Picture, subject, shot or boundary in target.
  Do not attach global camera/style/sound instructions to the first asset.
- transfer means inheriting an attribute from a reference; it does not mean
  generating an action requested in text. A still Picture cannot supply observed
  camera motion, speech, walking or edit rhythm. Record such explicit target
  requirements as asset-free directives with their exact required behavior and
  target scope. Reserve may_change for permission rather than mandatory action.
- Preservation is local to the referenced content unless cross-shot persistence
  is explicitly required. 'Keep each source composition' means keep each distinct
  scene in its assigned shot, not carry one scene or product into all shots.
  Repeated branding or a shared theme does not establish physical identity.
  Before seeing evidence, preserve 'the referenced content as depicted' rather
  than asserting the same named physical object occurs in every asset.
- Resolve every asset reference in the user's language into asset_mentions. This
  includes image, video, and audio references. Preserve the exact referring text.
- Semantic reference resolution belongs to you, not to downstream code. Record
  whether the referring phrase is singular or plural. For a singular reference,
  return exactly one resolved asset. If it is genuinely
  ambiguous, return no resolved asset, list all plausible candidates, and add a
  concise open question instead of guessing.
- expected_media_type must reflect the user's wording (image, video, audio, or
  empty when the wording does not imply a type). Never resolve a typed mention
  to an asset of a different media type.
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
  "asset_mentions": [{{"source_text":"exact text such as 图1 or reference video","resolved_asset_ids":["image_1"],"expected_media_type":"image|video|audio|empty","cardinality":"singular|plural","resolution":"exact|semantic|ambiguous|unresolved","confidence":1.0,"candidates":[]}}],
  "directives": [{{"directive_id":"d_1","asset_id":"image_1","target":"stable semantic target","operation":"preserve|replace|transfer|may_change|exclude","scope":["controlled attribute"],"priority":"hard|soft","provenance":"explicit_user"}}],
  "completion_policy": {{"technical":true,"conservative_semantic":true,"creative":false}},
  "perception_plan": {{"assets":[{{"asset_id":"image_1","role":"authority/use role","user_claimed_category":"or empty","analyze":["visible property or relation"],"evidence_requirements":[{{"claim":"single visible fact needed by a directive","priority":"required|useful|optional","region_or_time":"visible region, source-time window, or empty","retry_policy":"local_only","max_retries":1}}],"do_not_infer":["unsupported conclusion"]}}]}},
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
    asset_types = {
        str(item.get("asset_id", "")).strip(): str(item.get("media_type", "")).strip().lower()
        for item in source.get("assets", []) if isinstance(item, Mapping)
    }
    asset_ids = set(asset_types)
    mentions = payload.get("asset_mentions")
    if not isinstance(mentions, list):
        raise ValueError("intent resolver asset_mentions must be an array")
    normalized_mentions: list[dict[str, Any]] = []
    for index, item in enumerate(mentions):
        if not isinstance(item, Mapping):
            raise ValueError(f"asset_mentions[{index}] must be an object")
        source_text = str(item.get("source_text", "")).strip()
        if not source_text:
            raise ValueError(f"asset_mentions[{index}].source_text must not be empty")
        resolution = str(item.get("resolution", "")).strip().lower()
        if resolution not in {"exact", "semantic", "ambiguous", "unresolved"}:
            raise ValueError(f"asset_mentions[{index}].resolution is invalid")
        expected_type = str(item.get("expected_media_type", "")).strip().lower()
        if expected_type in {"empty", "none", "null"}:
            expected_type = ""
        if expected_type not in {"", "image", "video", "audio"}:
            raise ValueError(f"asset_mentions[{index}].expected_media_type is invalid")
        cardinality = str(item.get("cardinality", "singular")).strip().lower()
        if cardinality not in {"singular", "plural"}:
            raise ValueError(f"asset_mentions[{index}].cardinality is invalid")
        resolved_ids = [str(value).strip() for value in item.get("resolved_asset_ids", []) if str(value).strip()]
        candidates = [str(value).strip() for value in item.get("candidates", []) if str(value).strip()]
        if len(resolved_ids) != len(set(resolved_ids)) or len(candidates) != len(set(candidates)):
            raise ValueError(f"asset_mentions[{index}] contains duplicate asset IDs")
        unknown = (set(resolved_ids) | set(candidates)) - asset_ids
        if unknown:
            raise ValueError(f"asset_mentions[{index}] references unknown assets: {sorted(unknown)}")
        if resolution in {"exact", "semantic"} and cardinality == "singular" and len(resolved_ids) != 1:
            raise ValueError(f"asset_mentions[{index}] resolved singular mention must identify exactly one asset")
        if resolution in {"exact", "semantic"} and cardinality == "plural" and not resolved_ids:
            raise ValueError(f"asset_mentions[{index}] resolved plural mention must identify at least one asset")
        if resolution in {"ambiguous", "unresolved"} and resolved_ids:
            raise ValueError(f"asset_mentions[{index}] unresolved mention must not select an asset")
        if resolution == "ambiguous" and len(candidates) < 2:
            raise ValueError(f"asset_mentions[{index}] ambiguous mention must list at least two candidates")
        for asset_id in resolved_ids + candidates:
            if expected_type and asset_types[asset_id] != expected_type:
                raise ValueError(
                    f"asset_mentions[{index}] media type mismatch: expected {expected_type}, "
                    f"got {asset_types[asset_id]} for {asset_id}"
                )
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"asset_mentions[{index}].confidence must be numeric") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"asset_mentions[{index}].confidence must be between 0 and 1")
        normalized_mentions.append({
            "source_text": source_text,
            "resolved_asset_ids": resolved_ids,
            "expected_media_type": expected_type,
            "cardinality": cardinality,
            "resolution": resolution,
            "confidence": confidence,
            "candidates": candidates,
        })
    supplied = copy.deepcopy(source.get("directives", []))
    directives = payload.get("directives")
    if not isinstance(directives, list):
        raise ValueError("intent resolver directives must be an array")
    if directives[:len(supplied)] != supplied:
        raise ValueError("intent resolver changed or reordered supplied directives")
    directives = _atomize_added_directives(directives, len(supplied))
    # Some models copy the word "empty" from schema prose. Normalize that
    # representation before the strict source-contract validator runs.
    for directive in directives[len(supplied):]:
        if isinstance(directive, dict) and str(directive.get("asset_id", "")).strip().lower() in {"empty", "none", "null"}:
            directive["asset_id"] = ""
    plan = payload.get("perception_plan")
    if not isinstance(plan, Mapping) or not isinstance(plan.get("assets"), list):
        raise ValueError("intent resolver perception_plan.assets must be an array")
    planned: set[str] = set()
    plan_by_id: dict[str, dict[str, Any]] = {}
    normalized_plan = []
    hard_by_asset: dict[str, list[str]] = {}
    for directive in directives:
        if not isinstance(directive, Mapping) or str(directive.get("priority", "")).lower() != "hard":
            continue
        directive_asset = str(directive.get("asset_id", "")).strip()
        if directive_asset:
            hard_by_asset.setdefault(directive_asset, []).extend(
                str(value).strip() for value in directive.get("scope", []) if str(value).strip()
            )

    def evidence_requirements(item: Mapping[str, Any], asset_id: str) -> list[dict[str, Any]]:
        raw = item.get("evidence_requirements")
        if not isinstance(raw, list):
            raw = item.get("analyze", [])
        requirements: list[dict[str, Any]] = []
        for value in raw:
            if isinstance(value, Mapping):
                claim = str(value.get("claim", value.get("target", ""))).strip()
                proposed = str(value.get("priority", "")).strip().lower()
                region_or_time = str(value.get("region_or_time", "")).strip()
            else:
                claim, proposed, region_or_time = str(value).strip(), "", ""
            if not claim:
                continue
            # The model may suggest a priority, but only an explicit hard directive
            # is allowed to create retry-triggering evidence.
            claim_dimension = _scope_dimension(claim)
            hard_scopes = hard_by_asset.get(asset_id, [])
            is_hard = any(
                _scope_dimension(scope) == claim_dimension != "other"
                or claim.casefold() in scope.casefold()
                or scope.casefold() in claim.casefold()
                for scope in hard_scopes if scope
            )
            # Audio perception is intentionally outside the visual provider.
            # Keep the requirement visible to later audio-capable stages, but
            # never spend a Qwen-VL retry trying to inspect voice or music.
            if claim_dimension in {"voice", "music"}:
                is_hard = False
                proposed = "optional"
            priority = "required" if is_hard else (proposed if proposed in {"useful", "optional"} else "useful")
            requirements.append({
                "claim": claim,
                "priority": priority,
                "source_asset_id": asset_id,
                "region_or_time": region_or_time,
                "retry_policy": "local_only" if priority == "required" else "none",
                "max_retries": 1 if priority == "required" else 0,
            })
        return requirements
    for index, item in enumerate(plan["assets"]):
        if not isinstance(item, Mapping):
            raise ValueError(f"perception_plan.assets[{index}] must be an object")
        asset_id = str(item.get("asset_id", "")).strip()
        if asset_id not in asset_ids:
            raise ValueError(f"invalid perception-plan asset_id: {asset_id}")
        if asset_id in planned:
            existing = plan_by_id[asset_id]
            for key in ("analyze", "do_not_infer"):
                known = {value.casefold() for value in existing[key]}
                for value in [str(v).strip() for v in item.get(key, []) if str(v).strip()]:
                    if value.casefold() not in known:
                        existing[key].append(value)
                        known.add(value.casefold())
            if not existing["user_claimed_category"]:
                existing["user_claimed_category"] = str(item.get("user_claimed_category", "")).strip()
            known_claims = {value["claim"].casefold() for value in existing["evidence_requirements"]}
            for requirement in evidence_requirements(item, asset_id):
                if requirement["claim"].casefold() not in known_claims:
                    existing["evidence_requirements"].append(requirement)
                    known_claims.add(requirement["claim"].casefold())
            continue
        planned.add(asset_id)
        normalized = {
            "asset_id": asset_id,
            "role": str(item.get("role", "reference")).strip() or "reference",
            "user_claimed_category": str(item.get("user_claimed_category", "")).strip(),
            "analyze": [str(v).strip() for v in item.get("analyze", []) if str(v).strip()],
            "evidence_requirements": evidence_requirements(item, asset_id),
            "do_not_infer": [str(v).strip() for v in item.get("do_not_infer", []) if str(v).strip()],
        }
        normalized_plan.append(normalized)
        plan_by_id[asset_id] = normalized
    # Every asset must receive a plan, even when the model omitted an irrelevant one.
    for asset_id in sorted(asset_ids - planned):
        normalized_plan.append({"asset_id": asset_id, "role": "reference", "user_claimed_category": "", "analyze": ["generation-relevant visible evidence"], "evidence_requirements": [{"claim":"generation-relevant visible evidence","priority":"optional","source_asset_id":asset_id,"region_or_time":"","retry_policy":"none","max_retries":0}], "do_not_infer": ["unsupported identity, brand, function, or user intent"]})
    resolved = normalize_source_request({
        **copy.deepcopy(dict(source)),
        "resolved_request": str(payload.get("resolved_request", "")).strip(),
        "directives": copy.deepcopy(directives),
        "completion_policy": copy.deepcopy(payload.get("completion_policy") or source.get("completion_policy")),
        "open_questions": [str(v).strip() for v in payload.get("open_questions", []) if str(v).strip()],
        "asset_mentions": normalized_mentions,
    })
    report = validate_source_request(resolved)
    if not report.passed:
        raise ValueError(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return {"source": resolved, "asset_mentions": normalized_mentions, "perception_plan": {"assets": normalized_plan}}


def resolve_intent(source: Mapping[str, Any], invoke: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    """Resolve intent with the configured reasoning provider and validate strictly."""
    return validate_intent_resolution(invoke(build_intent_prompt(source)), source)
