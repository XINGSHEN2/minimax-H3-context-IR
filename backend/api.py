#!/usr/bin/env python3
"""Dependency-free Web API and static frontend for the Context-IR studio."""

from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from backend.agent import preflight_reasoning_provider, reasoning_provider_config, run_agent


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
ASSETS = Path(os.environ.get("CONTEXT_IR_ASSETS_DIR", ROOT / "assets")).resolve()
OUTPUTS = Path(os.environ.get("CONTEXT_IR_OUTPUTS_DIR", ROOT / "outputs")).resolve()
MAX_UPLOAD_BYTES = int(os.environ.get("CONTEXT_IR_MAX_UPLOAD_BYTES", str(1024 * 1024 * 1024)))
ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp"},
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi"},
    "audio": {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"},
}
RESULT_FILES = {
    "media_analysis.json", "context_ir.json", "h3_prompt.txt",
    "h3_prompt_audit.json", "h3_request.json", "agent.log",
}
CASE_PATTERN = re.compile(r"^case_(\d{3,})$")
SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=int(os.environ.get("CONTEXT_IR_JOB_WORKERS", "1")))

PROGRESS_STAGES = {
    "intent": (0, 18, "正在解析用户意图"),
    "bindings": (1, 36, "正在分析素材绑定"),
    "timeline": (2, 58, "正在编排时间线"),
    "isolation": (3, 78, "正在检查引用隔离"),
    "prompt": (4, 90, "正在生成 H3 Prompt"),
}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"source", "output_dir"}}


def _update_job(job_id: str, **changes: Any) -> None:
    with JOBS_LOCK:
        JOBS[job_id].update(changes)
        snapshot = dict(JOBS[job_id])
    output_dir = Path(snapshot["output_dir"])
    if output_dir.is_dir():
        _write_json(output_dir / "web_job.json", _public_job(snapshot))


def _run_job(job_id: str) -> None:
    with JOBS_LOCK:
        job = dict(JOBS[job_id])
    _update_job(
        job_id,
        status="running",
        started_at=datetime.now().isoformat(timespec="seconds"),
        progress_stage=0,
        progress_percent=12,
        progress_label="正在启动 Context-IR 任务",
    )
    try:
        def report_progress(phase: str) -> None:
            stage, percent, label = PROGRESS_STAGES[phase]
            _update_job(
                job_id,
                progress_phase=phase,
                progress_stage=stage,
                progress_percent=percent,
                progress_label=label,
            )

        run_agent(
            job["source"],
            Path(job["output_dir"]),
            job.get("style_skill"),
            progress_callback=report_progress,
        )
        available = sorted(name for name in RESULT_FILES if (Path(job["output_dir"]) / name).is_file())
        _update_job(
            job_id,
            status="completed",
            completed_at=datetime.now().isoformat(timespec="seconds"),
            result_files=available,
            progress_stage=len(PROGRESS_STAGES),
            progress_percent=100,
            progress_label="H3 Prompt 已生成并通过审计",
        )
    except Exception as exc:
        _update_job(
            job_id,
            status="failed",
            completed_at=datetime.now().isoformat(timespec="seconds"),
            error=str(exc),
        )


def _next_case_id() -> str:
    ASSETS.mkdir(parents=True, exist_ok=True)
    highest = 0
    for path in ASSETS.iterdir():
        match = CASE_PATTERN.match(path.name) if path.is_dir() else None
        if match:
            highest = max(highest, int(match.group(1)))
    return f"case_{highest + 1:03d}"


def _safe_filename(filename: str, fallback: str) -> str:
    name = Path(filename or fallback).name
    cleaned = SAFE_NAME_PATTERN.sub("_", name).strip("._")
    return cleaned or fallback


def _asset_type(filename: str, declared: str = "") -> str:
    suffix = Path(filename).suffix.lower()
    if declared in ALLOWED_EXTENSIONS and suffix in ALLOWED_EXTENSIONS[declared]:
        return declared
    for media_type, extensions in ALLOWED_EXTENSIONS.items():
        if suffix in extensions:
            return media_type
    raise ValueError(f"Unsupported media file: {filename}")


def _save_upload(field: cgi.FieldStorage, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as stream:
        while True:
            chunk = field.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise ValueError(f"Upload exceeds {MAX_UPLOAD_BYTES} bytes")
            stream.write(chunk)
    if total == 0:
        destination.unlink(missing_ok=True)
        raise ValueError(f"Empty upload: {field.filename}")
    return total


def _field_text(form: cgi.FieldStorage, name: str, default: str = "") -> str:
    if name not in form:
        return default
    value = form[name]
    if isinstance(value, list):
        value = value[-1]
    return str(value.value).strip()


def _create_case(form: cgi.FieldStorage) -> tuple[str, dict[str, Any]]:
    user_request = _field_text(form, "user_request")
    if not user_request:
        raise ValueError("请填写视频需求")
    task_type = _field_text(form, "task_type", "ref2va").lower()
    if task_type not in {"t2va", "i2va", "fl2va", "l2va", "ref2va"}:
        raise ValueError("不支持的任务类型")
    duration = float(_field_text(form, "duration_seconds", "15"))
    if not 4 <= duration <= 15:
        raise ValueError("视频时长必须为 4–15 秒")
    aspect_ratio = _field_text(form, "aspect_ratio", "9:16")
    generate_audio = _field_text(form, "generate_audio", "true").lower() == "true"
    style = _field_text(form, "style", "premium commercial, photorealistic")
    metadata_text = _field_text(form, "asset_metadata", "[]")
    metadata = json.loads(metadata_text)
    if not isinstance(metadata, list):
        raise ValueError("asset_metadata 必须是数组")

    upload_fields = form["files"] if "files" in form else []
    if not isinstance(upload_fields, list):
        upload_fields = [upload_fields]
    if task_type != "t2va" and not upload_fields:
        raise ValueError("该任务至少需要一个素材")
    if len(upload_fields) != len(metadata):
        raise ValueError("素材文件与角色信息数量不一致")

    case_id = _next_case_id()
    case_dir = ASSETS / case_id
    for folder in ("images", "videos", "audio"):
        (case_dir / folder).mkdir(parents=True, exist_ok=True)
    counters = {"image": 0, "video": 0, "audio": 0}
    assets = []
    try:
        for index, (field, meta) in enumerate(zip(upload_fields, metadata), start=1):
            if not isinstance(meta, dict):
                raise ValueError("素材角色信息格式错误")
            media_type = _asset_type(field.filename or "", str(meta.get("media_type", "")))
            counters[media_type] += 1
            asset_id = f"{media_type}_{counters[media_type]}"
            suffix = Path(field.filename or "").suffix.lower()
            filename = _safe_filename(field.filename or f"{asset_id}{suffix}", f"{asset_id}{suffix}")
            folder = {"image": "images", "video": "videos", "audio": "audio"}[media_type]
            destination = case_dir / folder / filename
            if destination.exists():
                destination = destination.with_name(f"{destination.stem}_{counters[media_type]}{destination.suffix}")
            size = _save_upload(field, destination)
            role = str(meta.get("role", "reference")).strip() or "reference"
            label = str(meta.get("label", "")).strip() or role
            assets.append({
                "asset_id": asset_id,
                "media_type": media_type,
                "uri": str(destination),
                "label": label,
                "user_role": role,
                "original_filename": Path(field.filename or filename).name,
                "size_bytes": size,
            })
        source = {
            "user_request": user_request,
            "task": {
                "type": task_type,
                "duration_seconds": duration,
                "aspect_ratio": aspect_ratio,
                "generate_audio": generate_audio,
                "style": style,
            },
            "perception_provider": {
                "provider": os.environ.get("CONTEXT_IR_VLM_PROVIDER", "local-qwen3-vl-32b"),
                "model": os.environ.get("YIWU_VLM_MODEL", "Qwen3-VL-32B-Instruct"),
                "options": {
                    "base_url": os.environ.get("YIWU_VLM_BASE_URL", "http://127.0.0.1:9012"),
                    "api_key_env": os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY"),
                    "video_frame_count": int(os.environ.get("CONTEXT_IR_VIDEO_FRAME_COUNT", "6")),
                    "video_fps": float(os.environ.get("CONTEXT_IR_VIDEO_FPS", "2")),
                    "video_max_frames": int(os.environ.get("CONTEXT_IR_VIDEO_MAX_FRAMES", "256")),
                    "poll_interval_seconds": float(os.environ.get("CONTEXT_IR_VLM_POLL_INTERVAL", "1")),
                    "timeout_seconds": float(os.environ.get("CONTEXT_IR_VLM_TIMEOUT_SECONDS", "1800")),
                    "output_dir": os.environ.get("CONTEXT_IR_VLM_OUTPUT_DIR", str(OUTPUTS / "qwen3-vl-32b")),
                },
            },
            "assets": assets,
        }
        _write_json(case_dir / "request.json", source)
        (case_dir / "user_prompt.txt").write_text(user_request + "\n", encoding="utf-8")
        return case_id, source
    except Exception:
        shutil.rmtree(case_dir, ignore_errors=True)
        raise


def _service_status() -> dict[str, Any]:
    key_env = os.environ.get("YIWU_VLM_API_KEY_ENV", "GITEE_AI_API_KEY")
    vlm_provider = os.environ.get("CONTEXT_IR_VLM_PROVIDER", "local-qwen3-vl-32b")
    vlm_model = os.environ.get("YIWU_VLM_MODEL", "Qwen3-VL-32B-Instruct")
    if vlm_provider == "local-qwen3-vl-32b":
        endpoint = os.environ.get("YIWU_VLM_BASE_URL", "http://127.0.0.1:9012").rstrip("/") + "/health"
        try:
            with urllib.request.urlopen(endpoint, timeout=0.8) as response:
                local_health = json.loads(response.read().decode("utf-8"))
            vlm_ready = local_health.get("status") == "ok"
        except (OSError, ValueError, urllib.error.URLError):
            vlm_ready = False
        vlm = {
            "ready": vlm_ready,
            "label": "本地 Qwen3-VL-32B 已连接" if vlm_ready else "本地 Qwen3-VL-32B 未连接",
            "model": vlm_model,
        }
    else:
        vlm = {
            "ready": bool(os.environ.get(key_env)),
            "label": "Qwen3-VL 已配置" if os.environ.get(key_env) else "Qwen3-VL 密钥未配置",
            "model": vlm_model,
        }
    reasoning = reasoning_provider_config()
    llm_key_present = bool(os.environ.get(reasoning["api_key_env"]))
    try:
        preflight_reasoning_provider(reasoning, timeout=0.4)
        llm = {
            "ready": llm_key_present,
            "label": f"{reasoning['model']} 已配置" if llm_key_present else f"{reasoning['model']} 密钥未配置",
            "provider": reasoning["selection"],
            "model": reasoning["model"],
        }
    except Exception:
        llm = {
            "ready": False,
            "label": f"{reasoning['name']} 推理服务未连接",
            "provider": reasoning["selection"],
            "model": reasoning["model"],
        }
    return {
        "ready": vlm["ready"] and llm["ready"],
        "vlm": vlm,
        "llm": llm,
        "glm": llm,
    }


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "ContextIRStudio/0.1"

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else unquote(path.lstrip("/"))
        target = (FRONTEND / relative).resolve()
        try:
            target.relative_to(FRONTEND.resolve())
        except ValueError:
            self._error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not target.is_file():
            target = FRONTEND / "index.html"
        body = target.read_bytes()
        mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type + ("; charset=utf-8" if mime_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"ok": True, "services": _service_status()})
            return
        if path.startswith("/api/jobs/"):
            parts = path.strip("/").split("/")
            job_id = parts[2] if len(parts) >= 3 else ""
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id, {}))
            if not job:
                self._error(HTTPStatus.NOT_FOUND, "任务不存在")
                return
            if len(parts) == 5 and parts[3] == "files":
                filename = parts[4]
                if filename not in RESULT_FILES:
                    self._error(HTTPStatus.FORBIDDEN, "结果文件不可访问")
                    return
                target = Path(job["output_dir"]) / filename
                if not target.is_file():
                    self._error(HTTPStatus.NOT_FOUND, "结果尚未生成")
                    return
                body = target.read_bytes()
                mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime_type + ("; charset=utf-8" if mime_type.startswith("text/") or filename.endswith(".json") else ""))
                self.send_header("Content-Disposition", f'inline; filename="{filename}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json(HTTPStatus.OK, {"ok": True, "job": _public_job(job)})
            return
        self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/jobs":
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "上传内容为空或超过限制")
            return
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")},
            )
            case_id, source = _create_case(form)
            job_id = uuid.uuid4().hex[:12]
            output_dir = OUTPUTS / f"web-{case_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            job = {
                "job_id": job_id,
                "case_id": case_id,
                "status": "queued",
                "progress_stage": 0,
                "progress_percent": 8,
                "progress_label": "素材已上传，正在等待处理",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "result_files": [],
                "source": source,
                "output_dir": str(output_dir),
            }
            with JOBS_LOCK:
                JOBS[job_id] = job
            EXECUTOR.submit(_run_job, job_id)
            self._json(HTTPStatus.ACCEPTED, {"ok": True, "job": _public_job(job)})
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} {format % args}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="MiniMax-H3 Context-IR Web Studio")
    parser.add_argument("--host", default=os.environ.get("CONTEXT_IR_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CONTEXT_IR_WEB_PORT", "38080")))
    args = parser.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), StudioHandler)
    print(json.dumps({"ready": True, "url": f"http://{args.host}:{args.port}", "frontend": str(FRONTEND)}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        EXECUTOR.shutdown(wait=False, cancel_futures=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
