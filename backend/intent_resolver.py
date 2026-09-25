"""User-intent resolution before multimodal perception.

This stage decides what each asset must be inspected for.  It never claims to
see media content; visual facts remain the perception provider's responsibility.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Mapping

from backend.contracts import normalize_source_request, validate_source_request


INTENT_SCOPE_RULES = "用户只描述某个镜头时，要求只约束这个镜头。除非用户明确要求一镜到底、不能加镜头、完全锁定分镜或严格复刻，否则不要把局部要求扩大到全片。未说明内容的硬切需要下一段画面；片尾硬切可以直接结束。不确定时记录疑问，不把猜测写成用户要求。"

INTENT_COMPLETION_RULES = "保留用户指定的内容、顺序、时间、素材用途和结尾。未指定的表演、机位、衔接动作通常留给后续创作；严格复刻或局部编辑的锁定范围除外。本阶段只标记哪些内容开放，不新增事件、镜头或禁令。"

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
    return f"""你负责在看素材之前理解用户需求，并给视觉模型写逐素材检查计划。你只能读取用户文字和素材清单；不能声称已经看见、听见或识别素材内容。

{INTENT_SCOPE_RULES}
{INTENT_COMPLETION_RULES}

按下面顺序处理：
1. 用 resolved_request 忠实、简短地整理用户要生成什么。保留明确的内容、动作、顺序、时长、结尾和素材用途；未说清的地方不要擅自补成事实。
2. 把明确要求写进 directives。每条只管一个方面，例如人物身份、服装、产品、动作、运镜、剪辑节奏、场景、声音、风格、首帧或尾帧。不要把不同方面塞进同一条，也不要把推测写成硬要求。原有 directives 必须原样保留。用户泛指多名参与者时，不要只选第一个人；视频里的表情和表演节奏属于动作，不属于固定身份。
3. 找出用户文字中提到的每张图、每段视频和音频，在 asset_mentions 中保留原话并对应素材编号。单数引用只能对应一个素材；确实不确定时列出候选并写入 open_questions，不要猜。素材类型必须与用户说法一致。
4. 为每份素材写 perception_plan。role 只表示用户指定的用途；没指定就写 unspecified_reference，不根据文件名猜用途。analyze 要列出与用户目标有关、能从画面核实的具体问题：整张画面的结构、人物或物品特征、文字、光线、位置关系，以及视频中的可见动作和时间。多格图片要逐格核对，不能把格子顺序当成播放顺序；相同品牌也不证明多张图里是同一件实物。图片不能证明运镜、动作过程或声音；视觉模型不能分析音频。用户所称的类别放进 user_claimed_category，不能当作已看见的事实。
5. do_not_infer 只阻止无依据的结论，不要让它遮住素材中实际可见的内容。evidence_requirements 只列确实需要核实的关键事实。用户要求互相冲突或素材引用不清时记录问题；缺少表演细节或补充镜头通常属于开放创作，不是禁令。

字段含义：transfer 是从参考素材继承属性，不是执行用户文字要求的动作；may_change 表示允许变化，不表示必须变化。素材只约束与它有关的内容；全局运镜、风格或声音要求不要随意挂到第一张图上。completion_policy.creative 在生成任务留有动作、机位或衔接空间时为 true；完全锁定且没有此类空间时为 false。保留严格复刻和局部编辑的边界。

只返回一个 JSON 对象，不要 Markdown。字段结构：
{{
  "resolved_request": "忠实简短的需求整理",
  "asset_mentions": [{{"source_text":"用户原话","resolved_asset_ids":["image_1"],"expected_media_type":"image|video|audio|empty","cardinality":"singular|plural","resolution":"exact|semantic|ambiguous|unresolved","confidence":1.0,"candidates":[]}}],
  "directives": [{{"directive_id":"d_1","asset_id":"image_1","target":"约束对象","operation":"preserve|replace|transfer|may_change|exclude","scope":["一项具体要求"],"priority":"hard|soft","provenance":"explicit_user"}}],
  "completion_policy": {{"technical":true,"conservative_semantic":true,"creative":true}},
  "perception_plan": {{"assets":[{{"asset_id":"image_1","role":"素材用途","user_claimed_category":"用户声称的类别或空字符串","analyze":["要核实的可见事实"],"evidence_requirements":[{{"claim":"需要核实的事实","priority":"required|useful|optional","region_or_time":"画面位置、原视频时间或空字符串","retry_policy":"local_only","max_retries":1}}],"do_not_infer":["不能从该素材推断的结论"]}}]}},
  "open_questions": []
}}

已有 directives（必须原样保留）：
{json.dumps(source.get('directives', []), ensure_ascii=False, indent=2)}

用户原始需求：
{source.get('user_request', '')}

素材清单：
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
