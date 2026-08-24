"""Replaceable multimodal perception provider contract.

Perception runs before the reasoning Agent. Providers normalize their output to
media_analysis.v2; Context-IR does not import any vendor SDK.  The v2 envelope
keeps visual facts, inferences, evidence locations, and confidence separate so
that the IR can make policy decisions without depending on a product category.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class PerceptionProviderConfig:
    provider: str = "local-qwen3-vl-32b"
    model: str = "Qwen3-VL-32B-Instruct"
    options: dict[str, Any] = field(default_factory=dict)


class PerceptionProvider(ABC):
    def __init__(self, config: PerceptionProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def analyze(self, assets: Sequence[Mapping[str, Any]], perception_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return a normalized media_analysis.v2 envelope."""


class CallablePerceptionProvider(PerceptionProvider):
    def __init__(
        self,
        config: PerceptionProviderConfig,
        transport: Callable[[PerceptionProviderConfig, Sequence[Mapping[str, Any]]], Mapping[str, Any]],
    ) -> None:
        super().__init__(config)
        self.transport = transport

    def analyze(self, assets: Sequence[Mapping[str, Any]], perception_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return normalize_media_analysis(self.transport(self.config, assets), assets, self.config)


class Qwen3OmniProvider(CallablePerceptionProvider):
    """Initial adapter name. The actual SDK/HTTP transport is injected."""


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
PERCEPTION_CACHE_SCHEMA_VERSION = "local-qwen3-vl-cache.v2"


def _canonical_entity_reference(value: Any, known_ids: set[str]) -> str:
    """Recover harmless Qwen ID punctuation drift such as entity3/entity_3."""
    candidate = str(value).strip()
    if candidate in known_ids:
        return candidate
    compact = re.sub(r"[^a-z0-9]+", "", candidate.casefold())
    matches = [item for item in known_ids if re.sub(r"[^a-z0-9]+", "", item.casefold()) == compact]
    return matches[0] if len(matches) == 1 else candidate
VISUAL_SYSTEM_PROMPT = (
    "You are a provider-neutral visual evidence extractor for a video-generation pipeline. "
    "Extract reusable evidence, not a generation prompt. Separate directly visible facts "
    "from visual inferences. Never decide what the user wants to preserve or replace. "
    "Never infer identity, brand claims, price, authorization, audio, dialogue, or intent. "
    "Use open-ended subcategories and attributes; do not assume a product domain. "
    "Every important attribute and relation needs field-level confidence and evidence IDs. "
    "Return exactly one JSON object and no Markdown."
)

LOCALIZATION_PROMPT = """Locate every distinct primary foreground object in this image.
Return only compact valid JSON: {"boxes":[["actual open-vocabulary category",x1,y1,x2,y2,confidence]]}
Coordinates use 0-1000: top-left [0,0], bottom-right [1000,1000].
Give one tight box per distinct object. Do not group separable objects. The category must name what the object actually is; never output the literal phrase 'open vocabulary'. No descriptions or Markdown."""

ATTRIBUTE_CROP_PROMPT = """The image is a labeled crop sheet made from one source image.
Each labeled cell contains exactly one primary object. Analyze cells independently and never merge content across cells.
Return only compact valid JSON: {"items":[{"object_id":"object_1","category":"actual open-vocabulary category","summary":"visible facts","features":[["color","name","value",0.9,"visible"]],"uncertainties":[],"confidence":0.9}]}
The first feature value must be exactly one of: geometry, color, material, surface, components, component_layout, orientation_cues, identity_markers, other. Never join group names with |. The fifth value must be exactly visible, inferred, or unresolved. The category must name the actual object type, never the literal phrase 'open vocabulary'. Each feature has exactly five values: group, name, value, confidence, source. Return 4-8 non-redundant reproduction-critical features per object and keep summaries under 18 words. Describe item-level differences. Identity markers are distinctive visible motifs, component arrangements, damage, text, or patterns, not a person's identity. Do not infer brand, price, user intent, audio, ownership, or use. Do not omit a label. Close the JSON before adding optional detail. Emit compact JSON without Markdown."""

COMPACT_VIDEO_TIMELINE_PROMPT = """Analyze this complete source video as provider-neutral visual evidence. Do not infer audio or user intent. Return only compact valid JSON:
{"summary":"visible overview","events":[{"event_id":"event_1","start_seconds":0.0,"end_seconds":1.0,"entity_ids":["entity_1"],"action":"visible shot, action, outfit and scene","transition_type":"cut","confidence":0.9}],"technical":{"duration_seconds":0.0,"framing":"","camera":"","visible_text":[]},"uncertainties":[]}
Use elapsed source-video seconds. Create a separate event for every shot, cut, outfit change, scene change, or distinct action; never merge several outfits, locations, or poses. Edited short videos normally need 4-12 chronological events covering the beginning through the ending. Entity IDs may be provisional but must use stable semantic IDs such as person_1, product_1, outfit_1, environment_1. Estimate confidence from 0.5-1.0. OCR only clearly legible text. Emit compact JSON without indentation or Markdown."""

COMPACT_VIDEO_ENTITY_PROMPT = """Analyze this complete source video as provider-neutral visual evidence. Do not infer audio, dialogue, identity, brand, price, ownership, intent, or user instructions. Return only compact valid JSON:
{"entities":[{"entity_id":"entity_1","category":"actual generic category","subcategory":"actual open vocabulary type","summary":"visible facts","quantity":[1,0.9],"features":[["color","name","value",0.9,"visible"]],"uncertainties":[]}],"relations":[["relation_1","type","entity_1","entity_2","visible anchor",0.9,"visible"]]}
The first feature value is exactly one of: geometry, color, material, surface, components, component_layout, orientation_cues, identity_markers, other. Never join group names with |. Return at most 8 high-value reusable entities, prioritizing people, the showcased product, outfit/garment variations, accessory groups, key props, environments, and visible text. Group related outfit changes or environments as variations/features when that avoids low-value entity proliferation. Do not enumerate incidental background objects.
Every relation endpoint must exactly match a declared entity_id. Return 4-8 concise reproduction-critical features per entity. Estimate confidence from 0.5-1.0 for visible/inferred facts; use 0 only when unresolved. Emit compact JSON without indentation or Markdown."""

RELATIONAL_IMAGE_PROMPT = """Analyze only the visible relationship, pose, grip, connection, orientation, and relative-scale evidence requested by the inspection plan. Do not perform exhaustive object cataloging or describe incidental background objects. Return only compact valid JSON:
{"summary":"visible relationship overview","entities":[{"entity_id":"entity_1","category":"generic visible type","summary":"brief visible facts","quantity":[1,0.9],"features":[["geometry|color|material|surface|components|component_layout|orientation_cues|identity_markers|other","name","value",0.9,"visible"]],"uncertainties":[]}],"relations":[["relation_1","connected_to|held_by|positioned_relative_to|scale_relative_to|other","entity_1","entity_2","visible anchor",0.9,"visible"]],"uncertainties":[]}
Declare at most 6 task-relevant entities and at most 8 relations. Every relation endpoint must match a declared entity_id. Keep features limited to facts necessary to understand the requested relationship. Do not infer function, performance, identity, brand, audio, ownership, or hidden connections. Emit compact JSON without Markdown."""


def _analysis_profile(asset: Mapping[str, Any], plan: Mapping[str, Any] | None) -> str:
    """Select the cheapest evidence pipeline that still satisfies the plan."""
    media_type = str(asset.get("media_type", ""))
    role = str((plan or {}).get("role", asset.get("user_role", ""))).lower()
    requested = " ".join(str(item) for item in (plan or {}).get("analyze", []) if str(item).strip()).lower()
    blocked = " ".join(str(item) for item in (plan or {}).get("do_not_infer", []) if str(item).strip()).lower()
    if media_type == "image":
        if any(token in role for token in ("identity", "product_appearance", "authoritative_product")):
            return "staged_detail"
        if any(token in role for token in ("connection", "motion", "pose", "usage", "scale", "style")):
            return "relational_one_shot"
        if any(token in requested for token in ("connect", "grip", "pose", "relative size", "orientation")):
            return "relational_one_shot"
        return "staged_detail"
    if media_type == "video":
        structural_role = any(token in role for token in ("motion", "camera", "rhythm", "structure"))
        structural_request = any(token in requested for token in ("action", "camera", "shot", "pacing", "transition"))
        appearance_requested = any(token in requested for token in ("identity", "outfit", "product appearance", "material", "logo", "scene detail"))
        appearance_blocked = any(token in blocked for token in ("identity", "product appearance", "outfit", "scene"))
        if structural_role and structural_request and not appearance_requested and appearance_blocked:
            return "timeline_only"
        return "timeline_and_entities"
    return "unsupported"


_EVIDENCE_STOPWORDS = {
    "visible", "evidence", "detail", "details", "property", "properties", "the", "and",
    "from", "with", "source", "reference", "image", "video", "asset", "generation", "relevant",
}


def _claim_terms(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", value.casefold())
        if len(token) >= 2 and token not in _EVIDENCE_STOPWORDS
    }


def _evidence_coverage(
    analysis: Mapping[str, Any], plan: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Cheap deterministic audit; it never calls a model or rejects an asset."""
    requirements = (plan or {}).get("evidence_requirements", [])
    if not isinstance(requirements, list):
        return []
    searchable = json.dumps({
        key: analysis.get(key)
        for key in ("summary", "evidence", "regions", "entities", "relations", "events", "technical", "transcript")
    }, ensure_ascii=False).casefold()
    coverage: list[dict[str, Any]] = []
    for index, value in enumerate(requirements, start=1):
        if not isinstance(value, Mapping):
            continue
        claim = str(value.get("claim", "")).strip()
        priority = str(value.get("priority", "useful")).lower()
        if priority not in {"required", "useful", "optional"}:
            priority = "useful"
        terms = _claim_terms(claim)
        matched = sorted(term for term in terms if term in searchable)
        # A non-empty, structured analysis is enough for broad optional requests;
        # required claims need at least one claim-specific lexical anchor.
        status = "covered" if matched else "missing"
        coverage.append({
            "requirement_id": f"requirement_{index}",
            "claim": claim,
            "priority": priority,
            "source_asset_id": str(value.get("source_asset_id", analysis.get("asset_id", ""))),
            "region_or_time": str(value.get("region_or_time", "")),
            "status": status,
            "matched_terms": matched,
            "retry_policy": "local_only" if priority == "required" else "none",
            "max_retries": 1 if priority == "required" else 0,
            "attempts": 0,
        })
    return coverage


def _required_supplements(coverage: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Only missing hard evidence is eligible for a bounded model request."""
    return [
        item for item in coverage
        if item.get("priority") == "required"
        and item.get("status") == "missing"
        and int(item.get("attempts", 0)) < min(1, int(item.get("max_retries", 1)))
    ]


def _close_truncated_json(text: str) -> dict[str, Any] | None:
    """Recover only a syntactically complete JSON prefix truncated at its tail."""
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack or (char == "}" and stack[-1] != "{") or (char == "]" and stack[-1] != "["):
                return None
            stack.pop()
    candidate = text.rstrip()
    if in_string or not candidate.endswith(("]", "}")):
        return None
    candidate += "".join("}" if char == "{" else "]" for char in reversed(stack))
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        value["_parse_recovery"] = "closed_truncated_tail"
        return value
    return None


def _json_object(text: str) -> dict[str, Any]:
    stripped = JSON_FENCE_PATTERN.sub("", text.strip())
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as original_error:
        # Qwen occasionally emits an open-vocabulary quantity label as a bare
        # JSON token, e.g. "quantity":[multiple,0.9]. Quoting only that value
        # is lossless and schema-directed; no semantic fields are reconstructed.
        quantity_repaired, quantity_repairs = re.subn(
            r'("quantity"\s*:\s*\[\s*)(multiple|several|many)(\s*,)',
            lambda match: match.group(1) + json.dumps(match.group(2)) + match.group(3),
            stripped,
            flags=re.IGNORECASE,
        )
        if quantity_repairs:
            try:
                value = json.loads(quantity_repaired)
                value["_parse_recovery"] = "bare_quantity_labels"
            except json.JSONDecodeError:
                value = None
        else:
            value = None
        if value is None and original_error.pos >= max(0, len(stripped) - 32):
            value = _close_truncated_json(stripped)
        if value is not None:
            pass
        else:
            start = stripped.find("{")
            if start < 0:
                raise ValueError("VLM response did not contain a JSON object")
            try:
                value, _ = json.JSONDecoder().raw_decode(stripped[start:])
            except json.JSONDecodeError:
                # Localization responses occasionally flatten later box entries, for
                # example: {"boxes":[["tire",0,0,500,500],"pump",...]}.
                # Recover only the documented box tuple shape; never repair semantic
                # analysis objects because a guessed repair could create false facts.
                if re.search(r'"boxes"\s*:', stripped):
                    matches = re.findall(
                        r'"([^"\\]+)"\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*'
                        r'(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*'
                        r'(-?\d+(?:\.\d+)?)(?:\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?))?',
                        stripped,
                    )
                    boxes = []
                    for label, x1, y1, x2, y2, confidence in matches:
                        box = [label, float(x1), float(y1), float(x2), float(y2)]
                        if confidence:
                            box.append(float(confidence))
                        boxes.append(box)
                    if boxes:
                        value = {"boxes": boxes, "_parse_recovery": "flattened_box_tuples"}
                    else:
                        raise original_error
                else:
                    raise original_error
    if isinstance(value, dict) and isinstance(value.get("boxes"), list):
        raw_boxes = value["boxes"]
        if raw_boxes and any(not isinstance(item, list) for item in raw_boxes):
            normalized_boxes = []
            index = 0
            while index < len(raw_boxes):
                item = raw_boxes[index]
                if isinstance(item, list):
                    normalized_boxes.append(item)
                    index += 1
                    continue
                if (
                    isinstance(item, str)
                    and index + 4 < len(raw_boxes)
                    and all(isinstance(raw_boxes[index + offset], (int, float)) for offset in range(1, 5))
                ):
                    box = [item, *raw_boxes[index + 1:index + 5]]
                    index += 5
                    if index < len(raw_boxes) and isinstance(raw_boxes[index], float) and 0 <= raw_boxes[index] <= 1:
                        box.append(raw_boxes[index])
                        index += 1
                    normalized_boxes.append(box)
                    continue
                index += 1
            if normalized_boxes:
                value["boxes"] = normalized_boxes
                value["_parse_recovery"] = "flattened_box_tuples"
    if not isinstance(value, dict):
        raise ValueError("VLM response root must be an object")
    return value


def _next_json_retry_token_budget(current: int, options: Mapping[str, Any]) -> int:
    """Increase only retry budgets so truncated JSON can reach its closing braces."""
    multiplier = max(1.0, float(options.get("json_retry_token_multiplier", 1.5)))
    ceiling = max(current, int(options.get("json_retry_max_tokens", 4096)))
    expanded = max(current + 256, math.ceil(current * multiplier))
    return min(ceiling, expanded)


def _image_url(source: str) -> str:
    if source.startswith(("http://", "https://", "data:")):
        return source
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"visual asset not found: {path}")
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"unsupported image extension: {path.suffix}")
    mime_type, _ = mimetypes.guess_type(str(path))
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type or 'image/jpeg'};base64,{encoded}"


def _extract_video_frames(path: Path, target_dir: Path, count: int) -> list[tuple[float, Path]]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to analyze local videos") from exc
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError("imageio-ffmpeg is required to analyze local videos") from exc

    reader = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgb24")
    try:
        metadata = next(reader)
    except (StopIteration, OSError, RuntimeError) as exc:
        raise RuntimeError(f"could not decode video: {path}") from exc
    width, height = metadata.get("size") or (0, 0)
    fps = float(metadata.get("fps") or 0.0)
    duration = float(metadata.get("duration") or 0.0)
    if width <= 0 or height <= 0 or fps <= 0 or duration <= 0:
        reader.close()
        raise RuntimeError(f"could not determine video metadata: {path}")

    # Duration-aware base sampling.  Zero means automatic: approximately one
    # observation per second, with enough coverage for short clips.  Providers
    # may still supply denser timestamped perception_frames around known cuts.
    count = round(duration) if count <= 0 else count
    count = max(8, min(count, 24))

    margin = min(0.25, duration * 0.03)
    span = max(0.0, duration - 2 * margin)
    timestamps = [margin + span * index / (count - 1) for index in range(count)]
    target_indices = [max(0, round(timestamp * fps)) for timestamp in timestamps]
    targets: dict[int, list[tuple[int, float]]] = {}
    for slot, (frame_index, timestamp) in enumerate(zip(target_indices, timestamps, strict=True), start=1):
        targets.setdefault(frame_index, []).append((slot, timestamp))

    captured: dict[int, tuple[float, Path]] = {}
    target_dir.mkdir(parents=True, exist_ok=True)
    max_target = max(targets)
    try:
        for frame_index, frame_bytes in enumerate(reader):
            if frame_index in targets:
                source = Image.frombytes("RGB", (width, height), frame_bytes)
                source.thumbnail((768, 768), Image.Resampling.LANCZOS)
                for slot, timestamp in targets[frame_index]:
                    frame = target_dir / f"frame_{slot:03d}.jpg"
                    source.save(frame, "JPEG", quality=88, optimize=True)
                    captured[slot] = (timestamp, frame)
            if frame_index >= max_target:
                break
    finally:
        reader.close()
    result = [captured[slot] for slot in sorted(captured)]
    if not result:
        raise RuntimeError(f"no frames could be sampled from video: {path}")
    return result


def _build_video_contact_sheet(frames: Sequence[tuple[float, Path]], target: Path) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except ImportError as exc:
        raise RuntimeError("Pillow is required to build video contact sheets") from exc

    frame_count = len(frames)
    columns = 2 if frame_count <= 4 else 3 if frame_count <= 6 else 4
    rows = math.ceil(frame_count / columns)
    cell_width = 384
    with Image.open(frames[0][1]) as first:
        source_width, source_height = first.size
    cell_height = max(216, min(512, round(cell_width * source_height / max(source_width, 1))))
    label_height = 34
    sheet = Image.new(
        "RGB",
        (columns * cell_width, rows * (cell_height + label_height)),
        "#101216",
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    for index, (timestamp, frame_path) in enumerate(frames):
        with Image.open(frame_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            fitted = ImageOps.contain(image, (cell_width, cell_height), Image.Resampling.LANCZOS)
        column = index % columns
        row = index // columns
        cell_top = row * (cell_height + label_height)
        left = column * cell_width + (cell_width - fitted.width) // 2
        top = cell_top + label_height + (cell_height - fitted.height) // 2
        sheet.paste(fitted, (left, top))
        draw.text(
            (column * cell_width + 10, cell_top + 7),
            f"#{index + 1}  {timestamp:.3f}s",
            font=font,
            fill=(220, 224, 232),
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, "JPEG", quality=90, optimize=True)
    return target


def _video_duration_seconds(path: Path) -> float | None:
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        duration = float(completed.stdout.strip())
        return duration if duration > 0 else None
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        return None


def _analysis_prompt(
    asset: Mapping[str, Any],
    timestamps: Sequence[float],
    video_duration_seconds: float | None = None,
    plan: Mapping[str, Any] | None = None,
) -> str:
    media_type = str(asset.get("media_type", "image"))
    temporal = ""
    event_example = '{"event_id":"event_1","time_range":[0.0,0.0],"entity_ids":[],"action":"visible change or action","state_before":{},"state_after":{},"transition_type":"none","evidence_ids":[],"confidence":0.0}'
    if timestamps:
        temporal = (
            " The images are chronological observations of one source video at seconds: "
            + ", ".join(f"{value:.3f}" for value in timestamps)
            + ". Describe the source video's visible progression and use those seconds for events; "
              "do not mention how the images were obtained."
        )
    elif media_type == "video":
        duration_rule = ""
        if video_duration_seconds is not None:
            duration_rule = (
                f" The original video duration is {video_duration_seconds:.3f} seconds. "
                f"All event times must be within 0.0-{video_duration_seconds:.3f}, and the "
                "event list must cover visible content across the complete video through its "
                "ending rather than stopping at the sampled-frame count."
            )
        temporal = (
            " Describe the video in chronological order and assign each event its approximate "
            "position on the original source-video timeline. The numeric start_seconds and "
            "end_seconds values must be elapsed wall-clock seconds from the beginning of the "
            "original video, not sampled-frame indices, event ordinals, decimal labels, or "
            "normalized progress. For example, an event visible from three seconds to six and "
            "a half seconds must be written as start_seconds 3.0 and end_seconds 6.5."
            + duration_rule
        )
        event_example = '{"event_id":"event_1","time_range":[3.0,6.5],"entity_ids":[],"action":"visible change or action in that original-video time range","state_before":{},"state_after":{},"transition_type":"none","evidence_ids":[],"confidence":0.0}'
    plan = plan or {}
    targeted = f"""
User-intent-derived analysis scope (this is not visual evidence):
- asset role: {plan.get('role', 'reference')}
- user-claimed category: {plan.get('user_claimed_category', '') or 'none'}
- inspect especially: {json.dumps(plan.get('analyze', []), ensure_ascii=False)}
- do not infer: {json.dumps(plan.get('do_not_infer', []), ensure_ascii=False)}
Treat the claimed category only as a search hypothesis. Report visible attributes,
supporting evidence, conflicts, alternatives, and confidence independently. Never
confirm a category from screen digits or text alone.
""".strip()
    return f"""
Analyze asset {asset.get('asset_id')} ({media_type}).{temporal}
{targeted}
This is a general evidence task. Analyze any important visible person, product,
garment, accessory, prop, animal, vehicle, environment, or text without assuming
a particular domain. Use stable entity IDs across the asset.

For each entity, extract generation-relevant evidence into these open attribute
groups when visible: geometry, color, material, surface, components,
component_layout, orientation_cues, identity_markers, and other. Do not fill a
group merely to satisfy the schema. Each attribute item uses name, value,
evidence_ids, confidence, source (visible|inferred|unresolved), and alternatives.
Mark identity markers critical only when they visibly distinguish the entity.

Relations use generic types such as worn_by, attached_to, held_by, placed_on,
inside, in_front_of, part_of, covers, interacts_with, or same_identity_as. A
relation must name subject_id, object_id, visible anchor/spatial constraints,
evidence_ids, confidence, and source. If a usage or attachment relation is only
plausible rather than visible, mark it inferred. Never turn inference into fact.

For multiple related items, record item-level variations instead of collapsing
them into one summary. For video, describe shots, actions, entity state changes,
reveals/replacements, and transition times. OCR only clearly legible text.

Return this exact media_analysis.v2 asset JSON shape:
{{
  "asset_id": {json.dumps(str(asset.get('asset_id', '')))},
  "summary": "concise directly supported summary",
  "evidence": [{{"evidence_id":"evidence_1","kind":"full_frame|frame|region|crop","time_seconds":null,"bbox_normalized":[0.0,0.0,1.0,1.0],"description":"what is visible here"}}],
  "regions": [{{"region_id":"region_1","evidence_id":"evidence_1","bbox_normalized":[0.0,0.0,1.0,1.0],"entity_ids":[],"analysis_priority":"low|medium|high","detail_request":"what closer inspection should resolve"}}],
  "entities": [{{"entity_id":"entity_1","category":"person|product|garment|accessory|prop|animal|vehicle|environment|text|unknown_object","subcategory":"open vocabulary","summary":"visible attributes only","quantity":{{"value":1,"confidence":0.0}},"attributes":{{"geometry":[],"color":[],"material":[],"surface":[],"components":[],"component_layout":[],"orientation_cues":[],"identity_markers":[],"other":[]}},"variations":[],"uncertainties":[]}}],
  "relations": [{{"relation_id":"relation_1","type":"open generic relation","subject_id":"entity_1","object_id":"entity_2","anchor":"visible attachment/contact/spatial anchor or empty","spatial_constraints":{{}},"evidence_ids":[],"confidence":0.0,"source":"visible|inferred|unresolved"}}],
  "events": [{event_example}],
  "technical": {{"media_type": {json.dumps(media_type)}, "duration_seconds": null, "framing": "", "camera": "", "visible_text": []}},
  "transcript": "",
  "uncertainties": []
}}
Audio and transcript must remain empty. Do not output user intent, bindings,
inheritance, preservation, replacement, or generation constraints.
""".strip()


class GiteeQwen3VLProvider(PerceptionProvider):
    """Gitee OpenAI-compatible Qwen3-VL adapter producing media_analysis.v2."""

    def __init__(
        self,
        config: PerceptionProviderConfig,
        completion_transport: Callable[[list[dict[str, Any]], PerceptionProviderConfig], str] | None = None,
        work_dir: Path | None = None,
    ) -> None:
        super().__init__(config)
        self.completion_transport = completion_transport or self._call_gitee
        self.work_dir = work_dir

    def _call_gitee(self, messages: list[dict[str, Any]], config: PerceptionProviderConfig) -> str:
        api_key_env = str(config.options.get("api_key_env", "GITEE_AI_API_KEY"))
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key environment variable: {api_key_env}")
        try:
            from openai import OpenAI
        except ImportError:
            return self._call_gitee_urllib(messages, config, api_key)
        client = OpenAI(
            base_url=str(config.options.get("base_url", "https://ai.gitee.com/v1")),
            api_key=api_key,
            default_headers={"X-Failover-Enabled": "true"},
        )
        kwargs = {
            "model": config.model,
            "messages": messages,
            "stream": bool(config.options.get("stream", False)),
            "max_tokens": int(config.options.get("max_tokens", 2048)),
            "temperature": float(config.options.get("temperature", 0.1)),
            "top_p": float(config.options.get("top_p", 1.0)),
            "frequency_penalty": 0,
            "extra_body": {"top_k": int(config.options.get("top_k", 1)), "enable_thinking": False},
        }
        response = client.chat.completions.create(**kwargs)
        if kwargs["stream"]:
            chunks = []
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            final = "".join(chunks)
        else:
            final = response.choices[0].message.content or ""
        if not final.strip():
            raise RuntimeError("Gitee VLM returned no final content")
        return final

    def _call_gitee_urllib(
        self,
        messages: list[dict[str, Any]],
        config: PerceptionProviderConfig,
        api_key: str,
    ) -> str:
        """Dependency-free fallback matching yiwu_codex's Gitee transport."""
        if bool(config.options.get("stream", False)):
            raise RuntimeError("Streaming Gitee VLM calls require the openai package")
        payload = {
            "model": config.model,
            "messages": messages,
            "stream": False,
            "max_tokens": int(config.options.get("max_tokens", 2048)),
            "temperature": float(config.options.get("temperature", 0.1)),
            "top_p": float(config.options.get("top_p", 1.0)),
            "frequency_penalty": 0,
            "top_k": int(config.options.get("top_k", 1)),
            "enable_thinking": False,
        }
        endpoint = str(config.options.get("base_url", "https://ai.gitee.com/v1")).rstrip("/") + "/chat/completions"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Failover-Enabled": "true",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=float(config.options.get("timeout_seconds", 300)),
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1500]
            raise RuntimeError(f"Gitee VLM HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gitee VLM connection failed: {exc.reason}") from exc
        final = result.get("choices", [{}])[0].get("message", {}).get("content") or ""
        if not str(final).strip():
            raise RuntimeError("Gitee VLM returned no final content")
        return str(final)

    def _visual_inputs(self, asset: Mapping[str, Any], temp_root: Path) -> tuple[list[str], list[float]]:
        media_type = str(asset.get("media_type", ""))
        uri = str(asset.get("uri", ""))
        if media_type == "image":
            return [_image_url(uri)], []
        if media_type == "video":
            supplied = asset.get("perception_frames") or asset.get("frame_uris")
            if isinstance(supplied, list) and supplied:
                urls, timestamps = [], []
                for index, item in enumerate(supplied):
                    if isinstance(item, Mapping):
                        urls.append(_image_url(str(item.get("uri", ""))))
                        timestamps.append(float(item.get("timestamp_seconds", index)))
                    else:
                        urls.append(_image_url(str(item)))
                        timestamps.append(float(index))
                return urls, timestamps
            if uri.startswith(("http://", "https://")):
                raise ValueError("remote video requires perception_frames with image URLs")
            path = Path(uri).expanduser().resolve()
            frames = _extract_video_frames(
                path,
                temp_root / str(asset.get("asset_id", "video")),
                int(self.config.options.get("video_frame_count", 6)),
            )
            contact_sheet = _build_video_contact_sheet(
                frames,
                temp_root / str(asset.get("asset_id", "video")) / "motion_contact_sheet.jpg",
            )
            return [_image_url(str(contact_sheet))], [timestamp for timestamp, _ in frames]
        return [], []

    def analyze(self, assets: Sequence[Mapping[str, Any]], perception_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        analyses = []
        plans = {str(item.get("asset_id", "")): item for item in (perception_plan or {}).get("assets", []) if isinstance(item, Mapping)}
        context = tempfile.TemporaryDirectory(prefix="context-ir-vlm-") if self.work_dir is None else None
        temp_root = self.work_dir or Path(context.name)
        try:
            for asset in assets:
                if asset.get("media_type") == "audio":
                    analyses.append({
                        "asset_id": str(asset.get("asset_id", "")),
                        "summary": "", "evidence": [], "regions": [], "entities": [],
                        "relations": [], "events": [],
                        "technical": {"media_type": "audio", "analysis_status": "unsupported_by_visual_provider"},
                        "transcript": "",
                        "uncertainties": ["Audio content was not analyzed by the visual perception provider"],
                    })
                    continue
                image_urls, timestamps = self._visual_inputs(asset, temp_root)
                content = [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
                content.append({"type": "text", "text": _analysis_prompt(asset, timestamps, plan=plans.get(str(asset.get("asset_id", ""))))})
                messages = [
                    {"role": "system", "content": VISUAL_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ]
                analysis = _json_object(self.completion_transport(messages, self.config))
                analysis["asset_id"] = str(asset.get("asset_id", ""))
                analyses.append(analysis)
        finally:
            if context is not None:
                context.cleanup()
        return normalize_media_analysis({"assets": analyses}, assets, self.config)


class LocalQwen3VL32BProvider(PerceptionProvider):
    """Local FIFO Qwen3-VL-32B service with native image/video path input."""

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        endpoint = str(self.config.options.get("base_url", "http://127.0.0.1:9012")).rstrip("/") + path
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1500]
            raise RuntimeError(f"Local Qwen3-VL HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Local Qwen3-VL connection failed: {exc.reason}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Local Qwen3-VL returned a non-object response")
        return value

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _cache_key(self, asset: Mapping[str, Any], plan: Mapping[str, Any] | None) -> str:
        source = Path(str(asset.get("uri", ""))).expanduser().resolve()
        profile = _analysis_profile(asset, plan)
        relevant_options = {
            key: self.config.options.get(key)
            for key in (
                "staged_image_analysis", "compact_video_analysis",
                "image_attribute_batch_size", "relational_image_max_tokens",
                "video_timeline_max_tokens", "video_entity_max_tokens",
                "video_fps", "video_max_frames", "max_tokens",
            )
        }
        material = {
            "schema": PERCEPTION_CACHE_SCHEMA_VERSION,
            "provider": self.config.provider,
            "model": self.config.model,
            "media_type": str(asset.get("media_type", "")),
            "profile": profile,
            "content_sha256": self._file_sha256(source),
            "plan": plan or {},
            "options": relevant_options,
        }
        encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _cache_path(self, cache_key: str) -> Path:
        output_root = Path(str(self.config.options.get(
            "output_dir", "/home/mx/shenxing/minimax-H3-context-IR/outputs/qwen3-vl-32b",
        ))).expanduser().resolve()
        cache_root = Path(str(self.config.options.get("cache_dir", output_root / "cache"))).expanduser().resolve()
        return cache_root / cache_key[:2] / f"{cache_key}.json"

    def _analyze_visual_cached(
        self,
        asset: Mapping[str, Any],
        plan: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], bool, str]:
        cache_enabled = bool(self.config.options.get("cache_enabled", True))
        cache_key = self._cache_key(asset, plan)
        cache_path = self._cache_path(cache_key)
        if cache_enabled and cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict):
                    return cached, True, cache_key
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        analysis = self._analyze_visual(asset, plan)
        if cache_enabled:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
            temporary.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, cache_path)
        return analysis, False, cache_key

    def _run_task(
        self,
        media_path: Path,
        prompt: str,
        output_dir: Path,
        max_new_tokens: int,
        _json_parse_attempt: int = 0,
        **parameters: Any,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "media_path": str(media_path.resolve()),
            "prompt": prompt,
            "output_dir": str(output_dir.resolve()),
            "max_new_tokens": max_new_tokens,
            "temperature": float(self.config.options.get("temperature", 0.0)),
            "top_p": float(self.config.options.get("top_p", 0.9)),
            **parameters,
        }
        submitted = self._request_json("POST", "/submit", payload)
        task_id = str(submitted.get("task_id", ""))
        if not task_id:
            raise RuntimeError("Local Qwen3-VL submit response did not contain task_id")
        deadline = time.monotonic() + float(self.config.options.get("timeout_seconds", 1800))
        poll_interval = max(0.25, float(self.config.options.get("poll_interval_seconds", 1.0)))
        while time.monotonic() < deadline:
            status = self._request_json("GET", f"/status/{task_id}")
            state = str(status.get("status", ""))
            if state == "done":
                files = status.get("output_files") or []
                if not files or not isinstance(files[0], Mapping):
                    raise RuntimeError("Local Qwen3-VL completed without an output file")
                response_path = Path(str(files[0].get("path", ""))).expanduser().resolve()
                if not response_path.is_file():
                    raise RuntimeError(f"Local Qwen3-VL output is missing: {response_path}")
                response_text = response_path.read_text(encoding="utf-8")
                try:
                    result = _json_object(response_text)
                except (ValueError, json.JSONDecodeError) as exc:
                    retry_limit = max(0, int(self.config.options.get("json_parse_retries", 2)))
                    if _json_parse_attempt >= retry_limit:
                        raise RuntimeError(
                            f"Local Qwen3-VL returned invalid JSON after {retry_limit + 1} attempts: {exc}"
                        ) from exc
                    retry_prompt = (
                        prompt
                        + "\nYour previous response was invalid or truncated JSON. Retry from scratch. "
                        + "Return only complete compact JSON in the exact requested schema. "
                        + "Use fewer words and fewer optional details so the closing braces fit."
                    )
                    retry_max_new_tokens = _next_json_retry_token_budget(
                        max_new_tokens,
                        self.config.options,
                    )
                    return self._run_task(
                        media_path,
                        retry_prompt,
                        output_dir.parent / f"{output_dir.name}_json_retry_{_json_parse_attempt + 1}",
                        retry_max_new_tokens,
                        _json_parse_attempt=_json_parse_attempt + 1,
                        **parameters,
                    )
                result["_task_id"] = task_id
                result["_input_media"] = dict(status.get("input_media", {}))
                return result
            if state in {"error", "cancelled"}:
                error = status.get("error") or {}
                message = error.get("message") if isinstance(error, Mapping) else str(error)
                raise RuntimeError(f"Local Qwen3-VL task {state}: {message or 'unknown error'}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Local Qwen3-VL task timed out: {task_id}")

    def _supplement_required_evidence(
        self,
        asset: Mapping[str, Any],
        requirement: Mapping[str, Any],
    ) -> tuple[dict[str, Any], float]:
        """Ask one bounded question about one missing hard-constraint fact."""
        source = Path(str(asset.get("uri", ""))).expanduser().resolve()
        claim = str(requirement.get("claim", "")).strip()
        region_or_time = str(requirement.get("region_or_time", "")).strip()
        media_type = str(asset.get("media_type", ""))
        prompt = (
            "Inspect only the following missing fact required by an explicit user constraint. "
            "Do not re-describe the whole asset and do not infer hidden content. "
            f"Question: {claim}. "
            + (f"Limit inspection to this region or source-time window: {region_or_time}. " if region_or_time else "")
            + 'Return only compact JSON: {"status":"observed|uncertain","answer":"brief visible evidence","confidence":0.0}. '
            "Use uncertain when the fact is not visibly supported."
        )
        output_root = Path(str(self.config.options.get(
            "output_dir", "/home/mx/shenxing/minimax-H3-context-IR/outputs/qwen3-vl-32b",
        ))).expanduser().resolve()
        parameters: dict[str, Any] = {}
        if media_type == "video":
            parameters.update(
                fps=float(self.config.options.get("supplemental_video_fps", self.config.options.get("video_fps", 2.0))),
                max_frames=int(self.config.options.get("supplemental_video_max_frames", 48)),
            )
        started = time.perf_counter()
        result = self._run_task(
            source, prompt,
            output_root / "supplemental" / str(asset.get("asset_id", "asset")) / str(requirement.get("requirement_id", "required")),
            int(self.config.options.get("supplemental_max_tokens", 256)),
            **parameters,
        )
        return result, time.perf_counter() - started

    @staticmethod
    def _localization_input(source: Path, target: Path) -> Path:
        from PIL import Image, ImageOps

        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        max_pixels = 224 * 224
        if image.width * image.height > max_pixels:
            scale = math.sqrt(max_pixels / (image.width * image.height))
            size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            image = image.resize(size, Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "JPEG", quality=95)
        return target

    @staticmethod
    def _attribute_sheet(
        source: Path,
        objects: Sequence[Mapping[str, Any]],
        target: Path,
    ) -> list[str]:
        from PIL import Image, ImageDraw, ImageFont, ImageOps

        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        cell_w, cell_h, label_h = 320, 420, 32
        columns = max(1, min(5, len(objects)))
        rows = math.ceil(len(objects) / columns)
        sheet = Image.new("RGB", (columns * cell_w, rows * (cell_h + label_h)), "#202020")
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default(size=20)
        object_ids = []
        for index, item in enumerate(objects):
            object_id = str(item["object_id"])
            object_ids.append(object_id)
            x1, y1, x2, y2 = [float(value) for value in item["bbox_normalized"]]
            inset = (x2 - x1) * 0.12
            x1, x2 = x1 + inset, x2 - inset
            box = (
                max(0, round(x1 * image.width)), max(0, round(y1 * image.height)),
                min(image.width, round(x2 * image.width)), min(image.height, round(y2 * image.height)),
            )
            crop = ImageOps.contain(image.crop(box), (cell_w, cell_h), Image.Resampling.LANCZOS)
            column, row = index % columns, index // columns
            left = column * cell_w + (cell_w - crop.width) // 2
            top = row * (cell_h + label_h) + label_h + (cell_h - crop.height) // 2
            sheet.paste(crop, (left, top))
            draw.text((column * cell_w + 8, row * (cell_h + label_h) + 5), object_id, font=font, fill="white")
        target.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(target, "JPEG", quality=94)
        return object_ids

    @staticmethod
    def _expand_features(item: Mapping[str, Any]) -> dict[str, Any]:
        groups = (
            "geometry", "color", "material", "surface", "components",
            "component_layout", "orientation_cues", "identity_markers", "other",
        )
        attributes: dict[str, list[dict[str, Any]]] = {group: [] for group in groups}
        for feature in item.get("features", []):
            if not isinstance(feature, list) or len(feature) not in {4, 5} or feature[0] not in attributes:
                continue
            group, name, value, confidence = feature[:4]
            source = feature[4] if len(feature) == 5 else "visible"
            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError):
                # Qwen occasionally omits the numeric confidence and shifts a
                # provenance token such as "visible" into its position. Keep
                # the rest of the entity evidence and discard only this
                # malformed feature instead of failing the whole asset run.
                continue
            attributes[str(group)].append({
                "name": str(name), "value": value, "evidence_ids": [],
                "confidence": confidence_value, "source": str(source), "alternatives": [],
            })
        try:
            entity_confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            entity_confidence = 0.0
        return {
            "category": str(item.get("category", "unknown_object")),
            "subcategory": str(item.get("subcategory", item.get("category", "unknown_object"))),
            "summary": str(item.get("summary", "")),
            "quantity": {"value": 1, "confidence": entity_confidence},
            "attributes": attributes,
            "variations": [],
            "uncertainties": list(item.get("uncertainties", [])),
        }

    def _analyze_image_staged(self, asset: Mapping[str, Any], source: Path, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        output_root = Path(str(self.config.options.get(
            "output_dir", "/home/mx/shenxing/minimax-H3-context-IR/outputs/qwen3-vl-32b",
        ))).expanduser().resolve()
        run_dir = output_root / "staged" / f"{asset.get('asset_id', 'image')}-{time.time_ns()}"
        localization_image = self._localization_input(source, run_dir / "localization_input.jpg")
        plan_text = json.dumps(plan or {}, ensure_ascii=False)
        guard = ("\nIntent-derived inspection plan (not visual evidence): " + plan_text
                 + "\nUse claimed categories only as hypotheses. Obey do_not_infer and report visible conflicts.")
        localized = self._run_task(localization_image, LOCALIZATION_PROMPT + guard, run_dir / "localization", 320)
        boxes = localized.get("boxes", [])
        objects = []
        for index, box in enumerate(boxes, start=1):
            if not isinstance(box, list) or len(box) < 5:
                continue
            category, x1, y1, x2, y2 = box[:5]
            confidence = box[5] if len(box) > 5 else 0.8
            coords = [max(0.0, min(1000.0, float(value))) for value in (x1, y1, x2, y2)]
            if coords[2] <= coords[0] or coords[3] <= coords[1]:
                continue
            objects.append({
                "object_id": f"object_{index}", "category": str(category),
                "confidence": float(confidence),
                "bbox_normalized": [round(value / 1000.0, 4) for value in coords],
            })
        if not objects:
            raise RuntimeError("Local Qwen3-VL localization returned no valid objects")

        details: dict[str, dict[str, Any]] = {}
        task_ids = [str(localized.get("_task_id", ""))]
        batch_size = max(1, min(5, int(self.config.options.get("image_attribute_batch_size", 3))))
        batches = [(offset, objects[offset:offset + batch_size]) for offset in range(0, len(objects), batch_size)]

        def analyze_batch(offset: int, batch: Sequence[Mapping[str, Any]]) -> tuple[int, list[str], list[Mapping[str, Any]], str]:
            batch = objects[offset:offset + batch_size]
            batch_dir = run_dir / f"attributes_{offset // batch_size + 1:02d}"
            sheet = batch_dir / "crops.jpg"
            expected_ids = self._attribute_sheet(source, batch, sheet)
            response = self._run_task(sheet, ATTRIBUTE_CROP_PROMPT + guard, batch_dir, 1800)
            items = response.get("items", [])
            actual_ids = [str(item.get("object_id", "")) for item in items if isinstance(item, Mapping)]
            if actual_ids != expected_ids:
                raise RuntimeError(f"Local Qwen3-VL attribute IDs mismatch: {actual_ids} != {expected_ids}")
            return offset, expected_ids, items, str(response.get("_task_id", ""))

        batch_workers = max(1, int(self.config.options.get("max_parallel_attribute_batches", 2)))
        batch_workers = min(batch_workers, len(batches)) if batches else 1
        if batch_workers == 1:
            batch_results = [analyze_batch(offset, batch) for offset, batch in batches]
        else:
            with ThreadPoolExecutor(max_workers=batch_workers, thread_name_prefix="qwen-attributes") as executor:
                batch_results = list(executor.map(lambda item: analyze_batch(*item), batches))
        for _, _, items, task_id in sorted(batch_results, key=lambda item: item[0]):
            task_ids.append(task_id)
            details.update({str(item["object_id"]): dict(item) for item in items})

        evidence, regions, entities = [], [], []
        for item in objects:
            object_id = str(item["object_id"])
            evidence_id = f"evidence_{object_id.removeprefix('object_')}"
            region_id = f"region_{object_id.removeprefix('object_')}"
            bbox = list(item["bbox_normalized"])
            evidence.append({
                "evidence_id": evidence_id, "kind": "region", "time_seconds": None,
                "bbox_normalized": bbox, "description": f"Localized {item['category']} {object_id}",
            })
            regions.append({
                "region_id": region_id, "evidence_id": evidence_id,
                "bbox_normalized": bbox, "entity_ids": [object_id],
                "analysis_priority": "high", "detail_request": "isolated object attributes",
            })
            entity = {"entity_id": object_id, **self._expand_features(details[object_id])}
            for values in entity["attributes"].values():
                for value in values:
                    value["evidence_ids"] = [evidence_id]
            entities.append(entity)
        return {
            "asset_id": str(asset.get("asset_id", "")),
            "summary": f"{len(entities)} distinct foreground objects localized and analyzed individually.",
            "evidence": evidence, "regions": regions, "entities": entities,
            "relations": [], "events": [],
            "technical": {
                "media_type": "image", "analysis_pipeline": "localize_then_isolated_attribute_batches",
                "localization_coordinate_system": "normalized_0_1", "task_ids": task_ids,
            },
            "transcript": "", "uncertainties": [],
        }

    def _analyze_image_relational(self, asset: Mapping[str, Any], source: Path, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        output_root = Path(str(self.config.options.get(
            "output_dir", "/home/mx/shenxing/minimax-H3-context-IR/outputs/qwen3-vl-32b",
        ))).expanduser().resolve()
        guard = (
            "\nIntent-derived inspection plan (not visual evidence): "
            + json.dumps(plan or {}, ensure_ascii=False)
            + "\nUse claimed categories only as hypotheses. Obey do_not_infer and report visible conflicts."
        )
        raw = self._run_task(
            source, RELATIONAL_IMAGE_PROMPT + guard,
            output_root / "relational_image",
            int(self.config.options.get("relational_image_max_tokens", 1000)),
        )
        evidence_id = "evidence_1"
        entities = []
        for index, item in enumerate(raw.get("entities", []), start=1):
            if not isinstance(item, Mapping):
                continue
            entity_id = str(item.get("entity_id") or f"entity_{index}")
            expanded = self._expand_features(item)
            quantity = item.get("quantity")
            if isinstance(quantity, list) and len(quantity) >= 2:
                expanded["quantity"] = {"value": quantity[0], "confidence": float(quantity[1])}
            for values in expanded["attributes"].values():
                for feature in values:
                    feature["evidence_ids"] = [evidence_id]
            entities.append({"entity_id": entity_id, **expanded})
        known_ids = {str(item["entity_id"]) for item in entities}
        relations = []
        for index, value in enumerate(raw.get("relations", []), start=1):
            if not isinstance(value, list) or len(value) < 7:
                continue
            relation_id, relation_type, subject_id, object_id, anchor, confidence, source_type = value[:7]
            subject_id = _canonical_entity_reference(subject_id, known_ids)
            object_id = _canonical_entity_reference(object_id, known_ids)
            if subject_id not in known_ids or object_id not in known_ids:
                continue
            relations.append({
                "relation_id": str(relation_id or f"relation_{index}"), "type": str(relation_type),
                "subject_id": subject_id, "object_id": object_id, "anchor": str(anchor),
                "spatial_constraints": {}, "evidence_ids": [evidence_id],
                "confidence": float(confidence), "source": str(source_type),
            })
        if not entities:
            raise RuntimeError("Local Qwen3-VL relational image analysis returned no entities")
        return {
            "asset_id": str(asset.get("asset_id", "")), "summary": str(raw.get("summary", "")),
            "evidence": [{
                "evidence_id": evidence_id, "kind": "frame", "time_seconds": None,
                "bbox_normalized": [0.0, 0.0, 1.0, 1.0],
                "description": str(raw.get("summary", "Visible relationship evidence")),
            }],
            "regions": [], "entities": entities, "relations": relations, "events": [],
            "technical": {
                "media_type": "image", "analysis_pipeline": "relational_one_shot",
                "task_ids": [str(raw.get("_task_id", ""))],
            },
            "transcript": "", "uncertainties": list(raw.get("uncertainties", [])),
        }

    def _analyze_video_compact(self, asset: Mapping[str, Any], source: Path, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        output_root = Path(str(self.config.options.get(
            "output_dir", "/home/mx/shenxing/minimax-H3-context-IR/outputs/qwen3-vl-32b",
        ))).expanduser().resolve()
        duration = _video_duration_seconds(source)
        duration_rule = ""
        if duration is not None:
            duration_rule = (
                f" The source duration is {duration:.3f} seconds. All event times must be within "
                f"0.0-{duration:.3f}, and the last event must reach the visible ending."
            )
        guard = ("\nIntent-derived inspection plan (not visual evidence): "
                 + json.dumps(plan or {}, ensure_ascii=False)
                 + "\nUse claimed categories only as hypotheses. Obey do_not_infer and report visible conflicts.")
        timeline_raw = self._run_task(
            source,
            COMPACT_VIDEO_TIMELINE_PROMPT + duration_rule + guard,
            output_root / "compact_video_timeline",
            int(self.config.options.get("video_timeline_max_tokens", 1200)),
            fps=float(self.config.options.get("video_fps", 2.0)),
            max_frames=int(self.config.options.get("video_max_frames", 256)),
        )
        if duration is None:
            detected_duration = timeline_raw.get("_input_media", {}).get("duration_seconds")
            if detected_duration is not None:
                duration = float(detected_duration)
        timeline_entity_ids = sorted({
            str(entity_id)
            for event in timeline_raw.get("events", [])
            if isinstance(event, (list, Mapping))
            for entity_id in (
                event.get("entity_ids", []) if isinstance(event, Mapping)
                else (event[3] if len(event) >= 4 and isinstance(event[3], list) else [])
            )
        })
        profile = _analysis_profile(asset, plan)
        if profile == "timeline_only":
            if not timeline_entity_ids:
                timeline_entity_ids = ["scene_1"]
            entity_raw = {
                "entities": [{
                    "entity_id": entity_id,
                    "category": entity_id.rsplit("_", 1)[0] or "visible_entity",
                    "subcategory": entity_id.rsplit("_", 1)[0] or "visible_entity",
                    "summary": "Timeline entity retained only for action and shot references.",
                    "quantity": [1, 0.5], "features": [],
                    "uncertainties": ["Detailed appearance analysis intentionally skipped for structural reference"],
                } for entity_id in timeline_entity_ids],
                "relations": [],
            }
        else:
            entity_prompt = COMPACT_VIDEO_ENTITY_PROMPT + guard
            if timeline_entity_ids:
                entity_prompt += (
                    " The timeline references these entity IDs: " + ", ".join(timeline_entity_ids)
                    + ". You must declare each of them using exactly the same ID."
                )
            entity_raw = self._run_task(
                source,
                entity_prompt,
                output_root / "compact_video_entities",
                int(self.config.options.get("video_entity_max_tokens", 2200)),
                fps=float(self.config.options.get("video_fps", 2.0)),
                max_frames=int(self.config.options.get("video_max_frames", 256)),
            )
        raw = {
            "summary": timeline_raw.get("summary", ""),
            "events": timeline_raw.get("events", []),
            "technical": timeline_raw.get("technical", {}),
            "uncertainties": timeline_raw.get("uncertainties", []),
            "entities": entity_raw.get("entities", []),
            "relations": entity_raw.get("relations", []),
        }

        events, evidence = [], []
        event_entity_ids: dict[str, list[str]] = {}
        for index, value in enumerate(raw.get("events", []), start=1):
            if isinstance(value, Mapping):
                event_id = value.get("event_id", f"event_{index}")
                start, end = value.get("start_seconds", 0.0), value.get("end_seconds", 0.0)
                entity_ids = value.get("entity_ids", [])
                action = value.get("action", "")
                transition = value.get("transition_type", "none")
                confidence = value.get("confidence", 0.8)
            elif isinstance(value, list) and len(value) >= 7:
                event_id, start, end, entity_ids, action, transition, confidence = value[:7]
            else:
                continue
            start_value, end_value = float(start), float(end)
            if duration is not None:
                start_value = max(0.0, min(duration, start_value))
                end_value = max(start_value, min(duration, end_value))
            ids = [str(item) for item in entity_ids] if isinstance(entity_ids, list) else []
            evidence_id = f"evidence_event_{index}"
            evidence.append({
                "evidence_id": evidence_id, "kind": "frame",
                "time_seconds": round((start_value + end_value) / 2, 3),
                "bbox_normalized": [0.0, 0.0, 1.0, 1.0], "description": str(action),
            })
            normalized_id = str(event_id or f"event_{index}")
            events.append({
                "event_id": normalized_id, "time_range": [start_value, end_value],
                "entity_ids": ids, "action": str(action), "state_before": {}, "state_after": {},
                "transition_type": str(transition), "evidence_ids": [evidence_id],
                "confidence": float(confidence),
            })
            for entity_id in ids:
                event_entity_ids.setdefault(entity_id, []).append(evidence_id)

        entities = []
        for index, item in enumerate(raw.get("entities", []), start=1):
            if not isinstance(item, Mapping):
                continue
            entity_id = str(item.get("entity_id") or f"entity_{index}")
            expanded = self._expand_features(item)
            quantity = item.get("quantity")
            if isinstance(quantity, list) and len(quantity) >= 2:
                expanded["quantity"] = {"value": quantity[0], "confidence": float(quantity[1])}
            evidence_ids = event_entity_ids.get(entity_id, [])
            for values in expanded["attributes"].values():
                for feature in values:
                    feature["evidence_ids"] = list(evidence_ids)
            entities.append({"entity_id": entity_id, **expanded})

        known_entity_ids = {str(item["entity_id"]) for item in entities}
        if not known_entity_ids:
            raise RuntimeError("Local Qwen3-VL compact video analysis returned no entities")
        entity_by_id = {str(item["entity_id"]): item for item in entities}
        aliases: dict[str, str] = {}
        for event in events:
            for timeline_id in event["entity_ids"]:
                if timeline_id in known_entity_ids or timeline_id in aliases:
                    continue
                semantic_prefix = timeline_id.rsplit("_", 1)[0].lower()
                candidates = []
                for entity_id, entity in entity_by_id.items():
                    searchable = " ".join((
                        str(entity.get("category", "")), str(entity.get("subcategory", "")),
                        str(entity.get("summary", "")),
                    )).lower()
                    if semantic_prefix and semantic_prefix in searchable:
                        candidates.append(entity_id)
                if len(candidates) == 1:
                    aliases[timeline_id] = candidates[0]
        unresolved_timeline_ids = sorted({
            timeline_id
            for event in events
            for timeline_id in event["entity_ids"]
            if timeline_id not in known_entity_ids and timeline_id not in aliases
        })
        for timeline_id in unresolved_timeline_ids:
            semantic_category = timeline_id.rsplit("_", 1)[0] or "unknown"
            evidence_ids = list(dict.fromkeys(event_entity_ids.get(timeline_id, [])))
            placeholder = self._expand_features({
                "category": semantic_category,
                "subcategory": semantic_category,
                "summary": "Visible timeline entity; detailed attributes were unresolved in the entity pass.",
                "confidence": 0.5,
                "features": [],
                "uncertainties": ["Detailed entity attributes were not returned by the compact entity pass"],
            })
            placeholder["quantity"] = {"value": 1, "confidence": 0.5}
            entities.append({"entity_id": timeline_id, **placeholder})
            known_entity_ids.add(timeline_id)
            entity_by_id[timeline_id] = entities[-1]
        event_entity_ids = {}
        for event in events:
            event["entity_ids"] = list(dict.fromkeys(
                aliases.get(entity_id, entity_id) for entity_id in event["entity_ids"]
            ))
            unknown = set(event["entity_ids"]) - known_entity_ids
            if unknown:
                raise RuntimeError(f"Local Qwen3-VL event references unknown entities: {sorted(unknown)}")
            for entity_id in event["entity_ids"]:
                event_entity_ids.setdefault(entity_id, []).extend(event["evidence_ids"])
        for entity in entities:
            aligned_evidence_ids = list(dict.fromkeys(event_entity_ids.get(str(entity["entity_id"]), [])))
            for values in entity["attributes"].values():
                for feature in values:
                    feature["evidence_ids"] = aligned_evidence_ids
        if duration is not None and events and duration - float(events[-1]["time_range"][1]) <= 1.0:
            events[-1]["time_range"][1] = duration

        relations = []
        for index, value in enumerate(raw.get("relations", []), start=1):
            if not isinstance(value, list) or len(value) < 7:
                continue
            relation_id, relation_type, subject_id, object_id, anchor, confidence, source_type = value[:7]
            subject_id = _canonical_entity_reference(subject_id, known_entity_ids)
            object_id = _canonical_entity_reference(object_id, known_entity_ids)
            if subject_id not in known_entity_ids or object_id not in known_entity_ids:
                raise RuntimeError(
                    f"Local Qwen3-VL relation references unknown entities: {subject_id}, {object_id}"
                )
            related_evidence = sorted(set(
                event_entity_ids.get(str(subject_id), []) + event_entity_ids.get(str(object_id), [])
            ))
            relations.append({
                "relation_id": str(relation_id or f"relation_{index}"), "type": str(relation_type),
                "subject_id": subject_id, "object_id": object_id, "anchor": str(anchor),
                "spatial_constraints": {}, "evidence_ids": related_evidence,
                "confidence": float(confidence), "source": str(source_type),
            })
        technical = dict(raw.get("technical", {}))
        technical.update({
            "media_type": "video",
            "analysis_pipeline": "compact_video_timeline_only" if profile == "timeline_only" else "compact_video_then_deterministic_expansion",
            "task_ids": [item for item in [str(timeline_raw.get("_task_id", "")), str(entity_raw.get("_task_id", ""))] if item],
        })
        if duration is not None:
            technical["duration_seconds"] = duration
        output_uncertainties = list(raw.get("uncertainties", []))
        if profile == "timeline_only":
            output_uncertainties.append("Detailed entity appearance pass intentionally skipped for structural reference")
        if unresolved_timeline_ids:
            output_uncertainties.append(
                "Compact entity pass omitted details for timeline entities: "
                + ", ".join(unresolved_timeline_ids)
            )
        return {
            "asset_id": str(asset.get("asset_id", "")), "summary": str(raw.get("summary", "")),
            "evidence": evidence, "regions": [], "entities": entities,
            "relations": relations, "events": events, "technical": technical,
            "transcript": "", "uncertainties": output_uncertainties,
        }

    def _analyze_visual(self, asset: Mapping[str, Any], plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        media_type = str(asset.get("media_type", ""))
        source = Path(str(asset.get("uri", ""))).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"local Qwen3-VL media path does not exist: {source}")
        if media_type == "image" and bool(self.config.options.get("staged_image_analysis", True)):
            if _analysis_profile(asset, plan) == "relational_one_shot":
                return self._analyze_image_relational(asset, source, plan)
            return self._analyze_image_staged(asset, source, plan)
        if media_type == "video" and bool(self.config.options.get("compact_video_analysis", True)):
            return self._analyze_video_compact(asset, source, plan)
        temporal_instruction = ""
        if media_type == "video":
            fps = float(self.config.options.get("video_fps", 2.0))
            temporal_instruction = (
                f"\n\nThis is the original source video decoded in chronological order at approximately {fps:g} fps. "
                "Describe visible progression, actions, cuts, camera changes, and scene changes. "
                "Use approximate source-video seconds for events. Do not analyze or infer audio."
            )
        duration = _video_duration_seconds(source) if media_type == "video" else None
        prompt = (
            VISUAL_SYSTEM_PROMPT
            + temporal_instruction
            + "\n\n"
            + _analysis_prompt(asset, [], video_duration_seconds=duration, plan=plan)
        )
        output_dir = Path(
            str(
                self.config.options.get(
                    "output_dir",
                    "/home/mx/shenxing/minimax-H3-context-IR/outputs/qwen3-vl-32b",
                )
            )
        ).expanduser().resolve()
        request_payload: dict[str, Any] = {
            "media_path": str(source),
            "prompt": prompt,
            "output_dir": str(output_dir),
            "max_new_tokens": int(self.config.options.get("max_tokens", 2048)),
            "temperature": float(self.config.options.get("temperature", 0.0)),
            "top_p": float(self.config.options.get("top_p", 0.9)),
        }
        if media_type == "video":
            request_payload.update(
                fps=float(self.config.options.get("video_fps", 2.0)),
                max_frames=int(self.config.options.get("video_max_frames", 256)),
            )
        submitted = self._request_json("POST", "/submit", request_payload)
        task_id = str(submitted.get("task_id", ""))
        if not task_id:
            raise RuntimeError("Local Qwen3-VL submit response did not contain task_id")
        deadline = time.monotonic() + float(self.config.options.get("timeout_seconds", 1800))
        poll_interval = max(0.25, float(self.config.options.get("poll_interval_seconds", 1.0)))
        while time.monotonic() < deadline:
            status = self._request_json("GET", f"/status/{task_id}")
            state = str(status.get("status", ""))
            if state == "done":
                files = status.get("output_files") or []
                if not files or not isinstance(files[0], Mapping):
                    raise RuntimeError("Local Qwen3-VL completed without an output file")
                response_path = Path(str(files[0].get("path", ""))).expanduser().resolve()
                if not response_path.is_file():
                    raise RuntimeError(f"Local Qwen3-VL output is missing: {response_path}")
                return _json_object(response_path.read_text(encoding="utf-8"))
            if state == "error":
                error = status.get("error") or {}
                message = error.get("message") if isinstance(error, Mapping) else str(error)
                raise RuntimeError(f"Local Qwen3-VL task failed: {message or 'unknown error'}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Local Qwen3-VL task timed out: {task_id}")

    def analyze(self, assets: Sequence[Mapping[str, Any]], perception_plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
        plans = {str(item.get("asset_id", "")): item for item in (perception_plan or {}).get("assets", []) if isinstance(item, Mapping)}
        analyses: list[dict[str, Any] | None] = [None] * len(assets)

        def analyze_one(index: int, asset: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
            plan = plans.get(str(asset.get("asset_id", "")))
            started = time.perf_counter()
            analysis, cache_hit, cache_key = self._analyze_visual_cached(asset, plan)
            analysis = dict(analysis)
            analysis["asset_id"] = str(asset.get("asset_id", ""))
            coverage = _evidence_coverage(analysis, plan)
            supplemental_attempts: list[dict[str, Any]] = []
            supplemental_elapsed = 0.0
            for requirement in _required_supplements(coverage):
                # Exactly one local attempt per missing required fact. Useful and
                # optional omissions never enter this branch.
                requirement["attempts"] = 1
                attempt_started = time.perf_counter()
                try:
                    supplemental, elapsed = self._supplement_required_evidence(asset, requirement)
                    supplemental_elapsed += elapsed
                    observed = str(supplemental.get("status", "")).lower() == "observed"
                    answer = str(supplemental.get("answer", "")).strip()
                    confidence = float(supplemental.get("confidence", 0.0) or 0.0)
                    requirement["status"] = "covered_after_supplement" if observed and answer else "unresolved"
                    requirement["supplemental_answer"] = answer
                    requirement["confidence"] = confidence
                    supplemental_attempts.append({
                        "requirement_id": requirement["requirement_id"], "reason": "required_evidence_missing",
                        "scope": requirement["region_or_time"], "status": requirement["status"],
                        "elapsed_seconds": round(elapsed, 3), "task_id": str(supplemental.get("_task_id", "")),
                    })
                except Exception as exc:
                    requirement["status"] = "unresolved"
                    supplemental_attempts.append({
                        "requirement_id": requirement["requirement_id"], "reason": "required_evidence_missing",
                        "scope": requirement["region_or_time"], "status": "failed",
                        "elapsed_seconds": round(time.perf_counter() - attempt_started, 3),
                        "error": str(exc)[:500],
                    })
                if requirement["status"] == "unresolved":
                    analysis.setdefault("uncertainties", []).append(
                        f"Required evidence remains uncertain after one local attempt: {requirement['claim']}"
                    )
            analysis["evidence_coverage"] = coverage
            analysis["supplemental_attempts"] = supplemental_attempts
            technical = analysis.setdefault("technical", {})
            if isinstance(technical, dict):
                technical["analysis_profile"] = _analysis_profile(asset, plan)
                technical["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                technical["cache_hit"] = cache_hit
                technical["cache_key"] = cache_key
                base_request_count = len(technical.get("task_ids", [])) or (0 if cache_hit else 1)
                technical["perception_metrics"] = {
                    "request_count": base_request_count + len(supplemental_attempts),
                    "retry_count": sum(1 for item in supplemental_attempts if item.get("status") == "failed"),
                    "supplemental_request_count": len(supplemental_attempts),
                    "supplemental_elapsed_seconds": round(supplemental_elapsed, 3),
                    "elapsed_seconds": technical["elapsed_seconds"],
                }
            return index, analysis

        visual_items: list[tuple[int, Mapping[str, Any]]] = []
        for index, asset in enumerate(assets):
            if asset.get("media_type") == "audio":
                analyses[index] = {
                    "asset_id": str(asset.get("asset_id", "")),
                    "summary": "", "evidence": [], "regions": [], "entities": [],
                    "relations": [], "events": [],
                    "technical": {"media_type": "audio", "analysis_status": "unsupported_by_visual_provider"},
                    "transcript": "",
                    "uncertainties": ["Audio content was not analyzed by the visual perception provider"],
                }
                continue
            visual_items.append((index, asset))

        max_workers = max(1, int(self.config.options.get("max_parallel_assets", 2)))
        max_workers = min(max_workers, len(visual_items)) if visual_items else 1
        if max_workers == 1:
            for index, asset in visual_items:
                result_index, analysis = analyze_one(index, asset)
                analyses[result_index] = analysis
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qwen-perception") as executor:
                futures = [executor.submit(analyze_one, index, asset) for index, asset in visual_items]
                for future in as_completed(futures):
                    result_index, analysis = future.result()
                    analyses[result_index] = analysis

        completed = [item for item in analyses if item is not None]
        normalized = normalize_media_analysis({"assets": completed}, assets, self.config)
        metrics = [item.get("technical", {}).get("perception_metrics", {}) for item in completed]
        normalized["perception_metrics"] = {
            "request_count": sum(int(item.get("request_count", 0)) for item in metrics),
            "retry_count": sum(int(item.get("retry_count", 0)) for item in metrics),
            "supplemental_request_count": sum(int(item.get("supplemental_request_count", 0)) for item in metrics),
            "elapsed_seconds": round(max((float(item.get("elapsed_seconds", 0)) for item in metrics), default=0.0), 3),
        }
        return normalized


class PerceptionProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., PerceptionProvider]] = {}

    def register(self, name: str, factory: Callable[..., PerceptionProvider]) -> None:
        key = name.strip().lower()
        if not key or key in self._factories:
            raise ValueError(f"invalid or duplicate provider: {name}")
        self._factories[key] = factory

    def create(self, config: PerceptionProviderConfig, **kwargs: Any) -> PerceptionProvider:
        try:
            factory = self._factories[config.provider.strip().lower()]
        except KeyError as exc:
            raise KeyError(f"unknown perception provider: {config.provider}") from exc
        return factory(config=config, **kwargs)

    def names(self) -> list[str]:
        return sorted(self._factories)


def normalize_media_analysis(
    raw: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
    config: PerceptionProviderConfig,
) -> dict[str, Any]:
    known = {str(asset.get("asset_id", "")) for asset in assets}
    analyses = raw.get("assets", raw.get("analyses", []))
    if not isinstance(analyses, list):
        raise ValueError("perception response must contain an assets list")
    normalized = []
    seen = set()
    for index, item in enumerate(analyses):
        if not isinstance(item, Mapping):
            raise ValueError(f"perception assets[{index}] must be an object")
        asset_id = str(item.get("asset_id", ""))
        if asset_id not in known or asset_id in seen:
            raise ValueError(f"unknown or duplicate perception asset_id: {asset_id}")
        seen.add(asset_id)
        # Accept legacy provider responses during rollout, but always expose v2.
        legacy_observations = item.get("observations", [])
        summary = str(item.get("summary", "")).strip()
        if not summary and isinstance(legacy_observations, list):
            summary = " ".join(
                str(value.get("text", "") if isinstance(value, Mapping) else value).strip()
                for value in legacy_observations
                if str(value).strip()
            )
        normalized.append({
            "asset_id": asset_id,
            "summary": summary,
            "evidence": list(item.get("evidence", [])),
            "regions": list(item.get("regions", [])),
            "entities": list(item.get("entities", [])),
            "relations": list(item.get("relations", [])),
            "events": list(item.get("events", [])),
            "technical": dict(item.get("technical", {})),
            "transcript": str(item.get("transcript", "")),
            "uncertainties": list(item.get("uncertainties", [])),
            "evidence_coverage": list(item.get("evidence_coverage", [])),
            "supplemental_attempts": list(item.get("supplemental_attempts", [])),
        })
    return {
        "schema_version": "media_analysis.v2",
        "provider": {"name": config.provider, "model": config.model, "options": config.options},
        "assets": normalized,
        "missing_asset_ids": sorted(known - seen),
    }


PERCEPTION_PROVIDERS = PerceptionProviderRegistry()
PERCEPTION_PROVIDERS.register("qwen3-omni", Qwen3OmniProvider)
PERCEPTION_PROVIDERS.register("gitee-qwen3-vl", GiteeQwen3VLProvider)
PERCEPTION_PROVIDERS.register("local-qwen3-vl-32b", LocalQwen3VL32BProvider)
