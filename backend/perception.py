"""Replaceable multimodal perception provider contract.

Perception runs before the Codex/GLM reasoning Agent. Providers normalize their
output to media_analysis.v1; Context-IR does not import any vendor SDK.
"""

from __future__ import annotations

import base64
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
    def analyze(self, assets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Return a normalized media_analysis.v1 envelope."""


class CallablePerceptionProvider(PerceptionProvider):
    def __init__(
        self,
        config: PerceptionProviderConfig,
        transport: Callable[[PerceptionProviderConfig, Sequence[Mapping[str, Any]]], Mapping[str, Any]],
    ) -> None:
        super().__init__(config)
        self.transport = transport

    def analyze(self, assets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return normalize_media_analysis(self.transport(self.config, assets), assets, self.config)


class Qwen3OmniProvider(CallablePerceptionProvider):
    """Initial adapter name. The actual SDK/HTTP transport is injected."""


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
VISUAL_SYSTEM_PROMPT = (
    "You are a visual evidence extractor for a video-generation pipeline. "
    "Report only directly visible facts. Never infer identity, brand claims, "
    "price, authorization, hidden materials, audio, dialogue, or intent. "
    "Return exactly one JSON object and no Markdown."
)


def _json_object(text: str) -> dict[str, Any]:
    stripped = JSON_FENCE_PATTERN.sub("", text.strip())
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start < 0:
            raise ValueError("VLM response did not contain a JSON object")
        value, _ = json.JSONDecoder().raw_decode(stripped[start:])
    if not isinstance(value, dict):
        raise ValueError("VLM response root must be an object")
    return value


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

    count = max(2, min(count, 12))
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
) -> str:
    media_type = str(asset.get("media_type", "image"))
    temporal = ""
    event_example = (
        '{"start_seconds": 0.0, "end_seconds": 0.0, "text": "visible change or action"}'
    )
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
        event_example = (
            '{"start_seconds": 3.0, "end_seconds": 6.5, '
            '"text": "visible change or action in that original-video time range"}'
        )
    return f"""
Analyze asset {asset.get('asset_id')} ({media_type}).{temporal}
Return this exact JSON shape:
{{
  "asset_id": {json.dumps(str(asset.get('asset_id', '')))},
  "observations": [{{"text": "directly visible fact"}}],
  "entities": [{{"type": "person|clothing|product|scene|text|other", "description": "visible attributes only"}}],
  "events": [{event_example}],
  "audio": {{}},
  "technical": {{"media_type": {json.dumps(media_type)}, "framing": "", "camera": "", "visible_text": []}},
  "transcript": "",
  "confidence": 0.0,
  "uncertainties": []
}}
Do not invent OCR characters that are not clearly legible. Audio and transcript must remain empty.
""".strip()


class GiteeQwen3VLProvider(PerceptionProvider):
    """Gitee OpenAI-compatible Qwen3-VL adapter producing media_analysis.v1."""

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

    def analyze(self, assets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        analyses = []
        context = tempfile.TemporaryDirectory(prefix="context-ir-vlm-") if self.work_dir is None else None
        temp_root = self.work_dir or Path(context.name)
        try:
            for asset in assets:
                if asset.get("media_type") == "audio":
                    analyses.append({
                        "asset_id": str(asset.get("asset_id", "")),
                        "observations": [], "entities": [], "events": [], "audio": {},
                        "technical": {"media_type": "audio", "analysis_status": "unsupported_by_visual_provider"},
                        "transcript": "", "confidence": None,
                        "uncertainties": ["Audio content was not analyzed by the visual perception provider"],
                    })
                    continue
                image_urls, timestamps = self._visual_inputs(asset, temp_root)
                content = [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
                content.append({"type": "text", "text": _analysis_prompt(asset, timestamps)})
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

    def _analyze_visual(self, asset: Mapping[str, Any]) -> dict[str, Any]:
        media_type = str(asset.get("media_type", ""))
        source = Path(str(asset.get("uri", ""))).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"local Qwen3-VL media path does not exist: {source}")
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
            + _analysis_prompt(asset, [], video_duration_seconds=duration)
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

    def analyze(self, assets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        analyses = []
        for asset in assets:
            if asset.get("media_type") == "audio":
                analyses.append({
                    "asset_id": str(asset.get("asset_id", "")),
                    "observations": [], "entities": [], "events": [], "audio": {},
                    "technical": {"media_type": "audio", "analysis_status": "unsupported_by_visual_provider"},
                    "transcript": "", "confidence": None,
                    "uncertainties": ["Audio content was not analyzed by the visual perception provider"],
                })
                continue
            analysis = self._analyze_visual(asset)
            analysis["asset_id"] = str(asset.get("asset_id", ""))
            analyses.append(analysis)
        return normalize_media_analysis({"assets": analyses}, assets, self.config)


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
        normalized.append({
            "asset_id": asset_id,
            "observations": list(item.get("observations", [])),
            "entities": list(item.get("entities", [])),
            "events": list(item.get("events", [])),
            "audio": dict(item.get("audio", {})),
            "technical": dict(item.get("technical", {})),
            "transcript": str(item.get("transcript", "")),
            "confidence": item.get("confidence"),
            "uncertainties": list(item.get("uncertainties", [])),
        })
    return {
        "schema_version": "media_analysis.v1",
        "provider": {"name": config.provider, "model": config.model, "options": config.options},
        "assets": normalized,
        "missing_asset_ids": sorted(known - seen),
    }


PERCEPTION_PROVIDERS = PerceptionProviderRegistry()
PERCEPTION_PROVIDERS.register("qwen3-omni", Qwen3OmniProvider)
PERCEPTION_PROVIDERS.register("gitee-qwen3-vl", GiteeQwen3VLProvider)
PERCEPTION_PROVIDERS.register("local-qwen3-vl-32b", LocalQwen3VL32BProvider)
