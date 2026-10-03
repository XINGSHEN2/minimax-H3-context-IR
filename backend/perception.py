"""Joint image analysis and audiovisual analysis, with checked source references."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.perception_prompts import IMAGE_PROMPT, OMNI_PROMPT, RETRY_PROMPT

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import threading
import urllib.error
import urllib.request

@dataclass(frozen=True)
class PerceptionProviderConfig:
    provider: str = "qwen-multimodal"
    model: str = "Qwen3.8-27B"
    options: dict[str, Any] = field(default_factory=dict)


def split_qwen_message(message: Mapping[str, Any]) -> tuple[str, str]:
    """Return diagnostic reasoning and final text without parsing reasoning as evidence."""
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ValueError("Qwen message.content must be a string")
    reasoning = message.get("reasoning_content")
    if reasoning is not None:
        if not isinstance(reasoning, str):
            raise ValueError("Qwen message.reasoning_content must be a string")
        return reasoning.strip(), content.strip()
    if "</think>" in content:
        thinking, final = content.split("</think>", 1)
        return thinking.removeprefix("<think>").strip(), final.strip()
    if content.lstrip().startswith("<think>"):
        return content.lstrip().removeprefix("<think>").strip(), ""
    return "", content.strip()


_PLACEHOLDER_TEXT = {
    "generic visible category",
    "generic visible type",
    "open vocabulary type",
    "actual open-vocabulary category",
    "visible facts",
    "visible shot",
    "visible overview",
    "whole-image visible overview",
    "name",
    "value",
}


def _is_placeholder_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    folded = value.strip().casefold()
    if folded in _PLACEHOLDER_TEXT:
        return True
    # Older Qwen responses sometimes copied a placeholder and appended a comma
    # followed by plausible nouns (for example ``visible shot, cityscape``).
    # The prefix still proves that the model emitted the schema example rather
    # than a grounded observation, so the whole field is unusable evidence.
    return any(
        folded.startswith(placeholder + delimiter)
        for placeholder in _PLACEHOLDER_TEXT
        for delimiter in (",", ":", ";", " - ")
    )


def _sanitize_analysis_quality(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Drop literal schema placeholders and soft-invalid cross references.

    This is a truth/shape guard only.  It never fabricates replacement evidence.
    """
    cleaned = copy.deepcopy(dict(analysis))
    warnings: list[str] = []
    if _is_placeholder_text(cleaned.get("summary")):
        cleaned["summary"] = ""
        warnings.append("Dropped placeholder asset summary")

    entities: list[dict[str, Any]] = []
    for raw_entity in cleaned.get("entities", []):
        if not isinstance(raw_entity, Mapping):
            continue
        entity = dict(raw_entity)
        for key in ("category", "subcategory", "summary"):
            if _is_placeholder_text(entity.get(key)):
                entity[key] = ""
                warnings.append(f"Dropped placeholder entity {key}")
        attributes = entity.get("attributes")
        if isinstance(attributes, Mapping):
            filtered: dict[str, list[Any]] = {}
            for group, raw_features in attributes.items():
                features = []
                for feature in raw_features if isinstance(raw_features, list) else []:
                    if not isinstance(feature, Mapping):
                        continue
                    if _is_placeholder_text(feature.get("name")) or _is_placeholder_text(feature.get("value")):
                        warnings.append("Dropped placeholder entity feature")
                        continue
                    features.append(dict(feature))
                filtered[str(group)] = features
            entity["attributes"] = filtered
        has_attributes = any(entity.get("attributes", {}).values()) if isinstance(entity.get("attributes"), Mapping) else False
        if not any(str(entity.get(key, "")).strip() for key in ("category", "subcategory", "summary")) and not has_attributes:
            warnings.append(f"Dropped empty placeholder entity {entity.get('entity_id', '')}")
            continue
        entities.append(entity)
    cleaned["entities"] = entities
    known_ids = {str(item.get("entity_id", "")) for item in entities}

    events = []
    for raw_event in cleaned.get("events", []):
        if not isinstance(raw_event, Mapping):
            continue
        event = dict(raw_event)
        if _is_placeholder_text(event.get("action")):
            warnings.append(f"Dropped placeholder event {event.get('event_id', '')}")
            continue
        ids = [str(value) for value in event.get("entity_ids", []) if str(value) in known_ids]
        if ids != list(event.get("entity_ids", [])):
            warnings.append(f"Removed unknown entity references from event {event.get('event_id', '')}")
        event["entity_ids"] = ids
        events.append(event)
    cleaned["events"] = events

    relations = []
    for raw_relation in cleaned.get("relations", []):
        if not isinstance(raw_relation, Mapping):
            continue
        relation = dict(raw_relation)
        if str(relation.get("subject_id", "")) not in known_ids or str(relation.get("object_id", "")) not in known_ids:
            warnings.append(f"Dropped relation with unknown endpoint {relation.get('relation_id', '')}")
            continue
        relations.append(relation)
    cleaned["relations"] = relations

    technical = cleaned.setdefault("technical", {})
    if not isinstance(technical, dict):
        technical = {}
        cleaned["technical"] = technical
    usable = bool(str(cleaned.get("summary", "")).strip() or entities or events or cleaned.get("global_analysis"))
    media_type = str(technical.get("media_type") or cleaned.get("media_type") or "").lower()
    # An audio asset intentionally skipped by a visual provider is not a failed
    # visual analysis. This also repairs cached empty audio entries previously
    # mislabeled invalid_placeholder, without asserting signal availability or
    # inventing a transcript, duration, timbre, or any other audible evidence.
    audio_not_analyzed = media_type == "audio" and (
        technical.get("analysis_status") == "unsupported_by_visual_provider"
        or (not usable and not warnings)
    )
    technical["analysis_status"] = (
        "not_analyzed" if audio_not_analyzed
        else "degraded" if warnings and usable
        else "invalid_placeholder" if not usable
        else "observed"
    )
    technical["quality_warnings"] = warnings
    if warnings:
        cleaned.setdefault("uncertainties", []).extend(warnings)
    return cleaned


def sanitize_media_analysis_quality(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the same quality gate to caller-supplied or cached media evidence."""
    cleaned = copy.deepcopy(dict(payload))
    cleaned["assets"] = [
        _sanitize_analysis_quality(item)
        for item in cleaned.get("assets", [])
        if isinstance(item, Mapping)
    ]
    return cleaned


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
            "global_analysis": dict(item.get("global_analysis", {})) if isinstance(item.get("global_analysis"), Mapping) else {},
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


class QwenTransport:
    def __init__(self, config: PerceptionProviderConfig) -> None:
        self.config = config
        self._uploaded_media: dict[tuple[str, int, int], str] = {}
        self._upload_lock = threading.Lock()


    def _media_url(self, media_path: Path) -> str:
        upload_base = str(self.config.options.get("asset_upload_base_url", "")).rstrip("/")
        source = media_path.expanduser().resolve()
        if not upload_base:
            return source.as_uri()
        stat = source.stat()
        key = (str(source), stat.st_size, stat.st_mtime_ns)
        with self._upload_lock:
            if key in self._uploaded_media:
                return self._uploaded_media[key]
            # curl streams the multipart body, including large source videos.
            escaped = str(source).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))
            timeout = float(self.config.options.get("asset_upload_timeout_seconds", 600))
            response = subprocess.run(
                ["curl", "--silent", "--show-error", "--fail-with-body",
                 "--connect-timeout", "15", "--max-time", str(timeout),
                 "--request", "POST", upload_base + "/v1/assets",
                 "--form", 'file=@"' + escaped + '"'],
                capture_output=True, text=True, timeout=timeout + 5, check=False,
            )
            if response.returncode:
                raise RuntimeError(f"Asset upload failed ({response.returncode}): {response.stderr[:500]} {response.stdout[:500]}")
            try:
                value = json.loads(response.stdout)
                url = value.get("url", "") if isinstance(value, dict) else ""
            except (ValueError, TypeError) as exc:
                raise RuntimeError("Asset upload returned invalid JSON") from exc
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                raise RuntimeError("Asset upload did not return an HTTP(S) url")
            self._uploaded_media[key] = url
            return url


    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        endpoint = (base_url or str(self.config.options.get("base_url", "http://127.0.0.1:9012"))).rstrip("/") + path
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
            raise RuntimeError(f"Qwen HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Qwen connection failed: {exc.reason}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Qwen returned a non-object response")
        return value


SCHEMA = "media_analysis.v3"
PROMPT_VERSION = "multimodal.v2"


def _array(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must contain objects")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def _time(item, duration):
    value = item.get("time_range")
    if value is None:
        item["time_range"] = None
        item.setdefault("timing_status", "unknown")
        return
    if (not isinstance(value, list) or len(value) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
            or duration is None or not 0 <= value[0] < value[1] <= duration):
        item["rejected_time_range"] = value
        item["time_range"] = None
        item["timing_status"] = "invalid_model_time"
        item["timing_warning"] = f"模型时间超出素材范围或格式不正确；素材时长 {duration} 秒，未定位。"
        return
    item["timing_status"] = "model_estimate"


def validate_analysis(raw, assets, metadata):
    """Validate raw or saved v3 data. Never clamp timestamps or infer identity."""
    if not isinstance(raw, dict):
        raise ValueError("analysis must be an object")
    result = copy.deepcopy(raw)
    expected = {a["asset_id"]: a for a in assets}
    items = _array(result.get("assets"), "assets")
    ids = [a.get("asset_id") for a in items]
    if len(ids) != len(expected) or any(not isinstance(i, str) for i in ids) or set(ids) != set(expected):
        raise ValueError("analysis must include each input asset_id exactly once")
    entities_by_asset = {}
    for item in items:
        aid = item["asset_id"]
        kind = expected[aid]["media_type"]
        meta = metadata.get(aid, {})
        duration = meta.get("duration_seconds")
        item.update(media_type=kind, status="complete", technical=copy.deepcopy(meta))
        _text(item.get("summary"), "summary")
        if not isinstance(item.get("uncertainties"), list) or any(not isinstance(x, str) for x in item["uncertainties"]):
            raise ValueError("uncertainties must be an array of strings")
        visual = item.get("visual")
        if not isinstance(visual, dict):
            raise ValueError("visual must be an object")
        entities = _array(visual.get("entities"), "entities")
        mapping = {}
        for entity in entities:
            eid = _text(entity.get("entity_id"), "entity_id")
            if eid in mapping:
                raise ValueError("duplicate entity_id")
            mapping[eid] = eid if eid.startswith(aid + ":") else aid + ":" + eid
            _text(entity.get("summary"), "entity summary")
            for feature in _array(entity.get("features", []), "features"):
                _text(feature.get("name"), "feature name")
                _text(feature.get("value"), "feature value")
                if feature.get("source") not in {"observed", "inferred", "uncertain"}:
                    raise ValueError("invalid feature source")
        entities_by_asset[aid] = mapping
        for entity in entities:
            entity["entity_id"] = mapping[entity["entity_id"]]
        def entity_ref(value):
            if not isinstance(value, str) or value not in mapping:
                raise ValueError(f"unknown entity in {aid}: {value}")
            return mapping[value]
        for rel in _array(visual.get("relations"), "relations"):
            rel["subject_id"] = entity_ref(rel.get("subject_id"))
            rel["object_id"] = entity_ref(rel.get("object_id"))
        event_map = {}
        events = _array(visual.get("events"), "events")
        for event in events:
            eid = _text(event.get("event_id"), "event_id")
            if eid in event_map:
                raise ValueError("duplicate event_id")
            event_map[eid] = eid if eid.startswith(aid + ":") else aid + ":" + eid
            event["event_id"] = event_map[eid]
            if not isinstance(event.get("entity_ids"), list):
                raise ValueError("entity_ids must be an array")
            event["entity_ids"] = [entity_ref(i) for i in event["entity_ids"]]
            _text(event.get("action"), "action")
            _time(event, duration)
        _array(visual.get("visible_text"), "visible_text")
        if kind == "image" and events:
            raise ValueError("static images cannot have timed events")
        if kind == "audio" and any(visual.get(k) for k in ("entities", "relations", "events", "visible_text")):
            raise ValueError("audio-only input cannot contain visual observations")
        audio = item.get("audio")
        if not isinstance(audio, dict):
            raise ValueError("audio must be an object")
        expected_status = "not_applicable" if kind == "image" else ("analyzed" if meta.get("has_audio") else "no_track")
        if audio.get("status") != expected_status:
            raise ValueError(f"audio.status must be {expected_status}")
        audio["audio_id"] = aid + ":audio" if expected_status == "analyzed" else None
        audio["source_asset_id"] = aid
        audio["source_type"] = "embedded_audio" if kind == "video" else kind
        segment_map = {}
        for key in ("speech_segments", "sound_events"):
            for seg in _array(audio.get(key), key):
                if expected_status != "analyzed":
                    raise ValueError("sound reported for input without audio")
                sid = _text(seg.get("segment_id"), "segment_id")
                if sid in segment_map:
                    raise ValueError("duplicate audio segment_id")
                segment_map[sid] = sid if sid.startswith(aid + ":") else aid + ":" + sid
                seg["segment_id"] = segment_map[sid]
                _text(seg.get("text" if key == "speech_segments" else "description"), key)
                _time(seg, duration)
        for link in _array(item.get("audio_visual_links"), "audio_visual_links"):
            if kind != "video" or link.get("segment_id") not in segment_map or link.get("event_id") not in event_map:
                raise ValueError("audio_visual_links references an unknown segment or event")
            link["segment_id"] = segment_map[link["segment_id"]]
            link["event_id"] = event_map[link["event_id"]]
    for relation in _array(result.get("cross_asset_relations"), "cross_asset_relations"):
        refs = _array(relation.get("references"), "references")
        if len(refs) < 2:
            raise ValueError("cross-image relation needs at least two references")
        for ref in refs:
            aid, eid = ref.get("asset_id"), ref.get("entity_id")
            if aid not in expected or expected[aid]["media_type"] != "image":
                raise ValueError(f"unknown image reference: {aid}")
            if eid is not None:
                if eid not in entities_by_asset[aid]:
                    raise ValueError(f"unknown entity {eid} in {aid}; use a declared entity ID, or null for the whole image")
                ref["entity_id"] = entities_by_asset[aid][eid]
            else:
                ref["entity_id"] = None
    result["schema_version"] = SCHEMA
    result["assets"] = sorted(items, key=lambda x: list(expected).index(x["asset_id"]))
    return result


def probe(asset):
    if asset["media_type"] == "image":
        return {}
    data = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", asset["uri"],
    ], timeout=30))
    duration = float(data["format"]["duration"])
    types = {s["codec_type"] for s in data.get("streams", [])}
    if not math.isfinite(duration) or not 0 < duration <= 30:
        raise ValueError("Omni currently supports media up to 30 seconds")
    if asset["media_type"] not in types:
        raise ValueError("declared media type is absent from the input")
    return {"duration_seconds": duration, "has_audio": "audio" in types}


def response_shape(assets, metadata):
    return {"assets": [{"asset_id": a["asset_id"], "summary": "实际内容",
        "entities": [["person_1", "person", "外观和衣着"]],
        "relations": [], "visible_text": [], "events": [], "speech": [], "sounds": [],
        "links": [], "uncertainties": []} for a in assets], "cross_asset_relations": []}


COMPACT_FORMAT = """用下面的数组格式减少字段开销，不减少实际观察内容。动作按阶段记录，对白逐句保留；不要增加字段或改变数组项数。
entities 每项：[实体ID,类别,外观与特征]。
relations 每项：[主体ID,客体ID,可见关系]。
visible_text 每项：[原文,位置]。
events 每项：[事件ID,开始秒,结束秒,[实体ID],可见动作、前后状态或镜头变化]。
speech 每项：[片段ID,开始秒,结束秒,说话者ID,实际原话]。
sounds 每项：[片段ID,开始秒,结束秒,music或effect或ambience,实际声音]。
links 每项：[声音片段ID,视觉事件ID,对应依据]。
开始秒和结束秒不确定时都写 null。图片的 events、speech、sounds、links 留空。
独立音频的 entities、relations、visible_text、events、links 留空。
cross_asset_relations 每项：{\"description\":\"图片之间的关系\",\"references\":[{\"asset_id\":\"图片ID\",\"entity_id\":\"该图实体ID\"}]}。比较整张图的风格或文字时 entity_id 写 null，不用字段名代替实体ID。不能确认同一主体时只写入 uncertainties。
"""


def expand_compact(raw, group, metadata):
    if not isinstance(raw, dict):
        raise ValueError("response must be an object")
    result = copy.deepcopy(raw)
    by_id = {a["asset_id"]: a for a in group}
    for item in _array(result.get("assets"), "assets"):
        aid = item.get("asset_id")
        if aid not in by_id:
            raise ValueError("unknown asset_id")
        if "visual" in item:
            continue
        def rows(key, width):
            value = item.get(key, [])
            if not isinstance(value, list) or any(not isinstance(v, list) or len(v) != width for v in value):
                raise ValueError(f"{key}: each row needs {width} values")
            return value
        def span(a, b):
            return None if a is None and b is None else [a, b]
        item["visual"] = {
            "entities": [{"entity_id": i, "category": k, "summary": text, "features": []}
                         for i, k, text in rows("entities", 3)],
            "relations": [{"subject_id": a, "object_id": b, "description": text, "source": "observed"}
                          for a, b, text in rows("relations", 3)],
            "visible_text": [{"text": text, "region": region} for text, region in rows("visible_text", 2)],
            "events": [{"event_id": i, "time_range": span(a, b), "entity_ids": ids, "action": text}
                       for i, a, b, ids, text in rows("events", 5)]}
        kind = by_id[aid]["media_type"]
        status = "not_applicable" if kind == "image" else ("analyzed" if metadata[aid].get("has_audio") else "no_track")
        item["audio"] = {"status": status,
            "speech_segments": [{"segment_id": i, "time_range": span(a, b), "speaker_id": speaker, "text": text}
                                for i, a, b, speaker, text in rows("speech", 5)],
            "sound_events": [{"segment_id": i, "time_range": span(a, b), "kind": k, "description": text}
                             for i, a, b, k, text in rows("sounds", 5)]}
        item["audio_visual_links"] = [{"segment_id": a, "event_id": b, "description": text}
                                     for a, b, text in rows("links", 3)]
        for key in ("entities", "relations", "visible_text", "events", "speech", "sounds", "links"):
            item.pop(key, None)
    result.setdefault("cross_asset_relations", [])
    return result


class MultimodalPerception:
    def __init__(self, options=None):
        self.options = options or {}
        self.transport = QwenTransport(PerceptionProviderConfig(options={
            "asset_upload_base_url": self.options.get("asset_upload_base_url") or os.getenv("QWEN_ASSET_UPLOAD_BASE_URL", "http://10.42.1.1:30100")
        }))

    def analyze(self, source, output_dir):
        assets = source.get("assets", [])
        ids = [a.get("asset_id") for a in assets]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("asset IDs must be nonempty and unique")
        if any(a.get("media_type") not in {"image", "video", "audio"} for a in assets):
            raise ValueError("unsupported media type")
        images = [a for a in assets if a["media_type"] == "image"]
        if len(images) > 8:
            raise ValueError("joint image analysis supports at most 8 images; reduce the input count")
        metadata = {a["asset_id"]: probe(a) for a in assets}
        groups = ([images] if images else []) + [[a] for a in assets if a["media_type"] != "image"]
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        def analyze_group(pair):
            index, group = pair
            directory = output_dir / f"request_{index:02d}"
            directory.mkdir(exist_ok=True)
            image = group[0]["media_type"] == "image"
            url = self.options.get("image_base_url") or os.getenv("QWEN_IMAGE_UNDERSTAND_BASE_URL", "http://10.42.1.1:9012")
            model = self.options.get("image_model") or os.getenv("QWEN_IMAGE_MODEL", "Qwen3.8-27B")
            if not image:
                url = self.options.get("omni_base_url") or os.getenv("QWEN_OMNI_BASE_URL", "http://10.42.1.1:9013")
                model = self.options.get("omni_model") or os.getenv("QWEN_OMNI_MODEL", "Qwen3-Omni-30B-A3B-Instruct")
            manifest = [{k: a[k] for k in ("asset_id", "media_type", "label", "original_filename", "user_role") if k in a}
                        | metadata[a["asset_id"]] for a in group]
            shape = response_shape(group, metadata)
            prompt = (IMAGE_PROMPT if image else OMNI_PROMPT) + "\n用户原始需求：\n" + source["user_request"]
            prompt += "\n素材清单（duration_seconds 是实测总时长）：\n" + json.dumps(manifest, ensure_ascii=False)
            prompt += "\n" + COMPACT_FORMAT + "\n返回格式：\n" + json.dumps(shape, ensure_ascii=False)
            content = [{"type": "text", "text": prompt}]
            for a in group:
                uri = a["uri"]
                media_url = uri if uri.startswith(("http://", "https://")) else self.transport._media_url(Path(uri))
                key = {"image": "image_url", "video": "video_url", "audio": "audio_url"}[a["media_type"]]
                content += [{"type": "text", "text": "asset_id=" + a["asset_id"]}, {"type": key, key: {"url": media_url}}]
            for attempt in range(2):
                payload = {"model": model, "messages": [{"role": "user", "content": content}],
                           "max_tokens": 8192 if image else 2048, "temperature": 0, "stream": False}
                if group[0]["media_type"] == "video":
                    for option, field in (("omni_fps", "fps"), ("omni_video_max_pixels", "video_max_pixels")):
                        if option in self.options:
                            payload[field] = self.options[option]
                if image:
                    payload["chat_template_kwargs"] = {"enable_thinking": False}
                (directory / f"request_{attempt}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                response = self.transport._request_json("POST", "/v1/chat/completions", payload,
                    timeout=float(self.options.get("timeout_seconds", 1800)), base_url=url.rstrip("/").removesuffix("/v1"))
                (directory / f"response_{attempt}.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
                try:
                    _, final = split_qwen_message(response["choices"][0]["message"])
                    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", final.strip())
                    # Repair only duplicated quotes before JSON field names. Never change values.
                    repaired = re.sub(r'([,{]\s*)"\s+"([a-zA-Z_][a-zA-Z_0-9]*)"\s*:', r'\1"\2":', text)
                    parsed = json.loads(repaired)
                    if repaired != text:
                        (directory / f"format_repair_{attempt}.txt").write_text("Removed duplicate quotes before field names; values unchanged.", encoding="utf-8")
                    parsed.setdefault("cross_asset_relations", [])
                    result = validate_analysis(expand_compact(parsed, group, metadata), group, metadata)
                    result["provider"] = {"model": model, "task_id": response.get("x_task_id"), "attempts": attempt + 1}
                    return result
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    (directory / f"validation_{attempt}.txt").write_text(str(exc), encoding="utf-8")
                    if attempt:
                        raise ValueError(f"Analysis failed for {[a['asset_id'] for a in group]}: {exc}") from exc
                    content[0]["text"] = prompt + "\n" + RETRY_PROMPT + str(exc)[:500]
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(groups)))) as executor:
            results = list(executor.map(analyze_group, enumerate(groups)))
        merged = {"assets": [a for r in results for a in r["assets"]],
                  "cross_asset_relations": [r for result in results for r in result["cross_asset_relations"]]}
        merged = validate_analysis(merged, assets, metadata)
        merged.update(prompt_version=PROMPT_VERSION, providers=[r["provider"] for r in results], missing_asset_ids=[])
        (output_dir / "media_analysis.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return merged
