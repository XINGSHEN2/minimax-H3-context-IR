#!/usr/bin/env python3
"""Wait for local Context-IR prompts and render their 480p H3 videos."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


TERMINAL = {"completed", "failed", "cancelled", "canceled"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected one JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return read_json_response(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {method} {path}: {detail}") from exc


def read_json_response(body: bytes) -> dict[str, Any]:
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("API response root must be an object")
    return value


def wait_for_variant(root: Path, case_id: str, variant: str, timeout_seconds: int) -> Path:
    variant_dir = root / case_id / "B_context_ir" / variant
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        prompt = variant_dir / "h3_prompt.txt"
        audit = variant_dir / "h3_prompt_audit.json"
        timings = variant_dir / "stage_timings.json"
        if prompt.is_file() and audit.is_file() and timings.is_file():
            if not read_json(audit).get("passed"):
                raise RuntimeError(f"Prompt audit failed: {audit}")
            return prompt
        suite_status = root / "local_ir_suite_status.json"
        if suite_status.is_file():
            case_status = read_json(suite_status).get("cases", {}).get(case_id, {})
            if case_status.get("status") == "failed":
                raise RuntimeError(f"Context-IR failed for {case_id}: {case_status}")
        time.sleep(10)
    raise TimeoutError(f"Timed out waiting for {case_id}/{variant}")


def build_request(prompt: Path, spec: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    case_dir = prompt.parents[2]
    conditions = []
    for asset in spec.get("assets", []):
        media_type = str(asset["media_type"])
        if media_type not in {"image", "video"}:
            continue
        conditions.append({
            "type": media_type,
            "uri": str((case_dir / str(asset["file"])).resolve()),
            "role": "reference",
        })
    task = spec.get("task", {})
    return {
        "task": "ref2va",
        "prompt_file": str(prompt.resolve()),
        "conditions": conditions,
        "target": {
            "short_edge": 480,
            "aspect_ratio": str(task.get("aspect_ratio", "9:16")),
            "duration_seconds": float(task.get("duration_seconds", 15)),
        },
        "seed": 42,
        "n": 1,
        "num_inference_steps": 20,
        "output_mode": "decoded_files",
        "output_path": str(output_dir.resolve()),
    }


def run_one(base_url: str, root: Path, case_id: str, variant: str, prompt: Path) -> dict[str, Any]:
    variant_dir = prompt.parent
    run_dir = variant_dir / "h3_480_15s_20steps"
    output_dir = run_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "result.json"
    if result_path.is_file():
        previous = read_json(result_path)
        if previous.get("status") == "completed":
            paths = previous.get("final", {}).get("file_paths", [])
            if paths and all(Path(item).is_file() and Path(item).stat().st_size > 0 for item in paths):
                print(f"SKIP completed {case_id}/{variant}", flush=True)
                return previous

    spec = read_json(root / case_id / "case_spec.json")
    payload = build_request(prompt, spec, output_dir)
    write_json(run_dir / "request.json", payload)
    started_at = now()
    started = time.perf_counter()
    submitted = api(base_url, "POST", "/v1/videos", payload)
    task_id = str(submitted["id"])
    write_json(run_dir / "submitted.json", submitted)
    print(f"SUBMITTED {case_id}/{variant} {task_id}", flush=True)

    final: dict[str, Any] | None = None
    poll_path = run_dir / "poll.jsonl"
    while time.perf_counter() - started < 7200:
        current = api(base_url, "GET", f"/v1/videos/{task_id}", timeout=30)
        with poll_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"observed_at": now(), **current}, ensure_ascii=False) + "\n")
        print(
            f"POLL {case_id}/{variant} status={current.get('status')} "
            f"step={current.get('current_step')}/{current.get('total_steps')}",
            flush=True,
        )
        if str(current.get("status")) in TERMINAL:
            final = current
            break
        time.sleep(5)
    if final is None:
        final = {"status": "timeout", "error": {"message": "Exceeded 7200 seconds"}}
    result = {
        "case_id": case_id,
        "variant": variant,
        "task_id": task_id,
        "status": final.get("status"),
        "wall_seconds": round(time.perf_counter() - started, 3),
        "started_at": started_at,
        "finished_at": now(),
        "request": payload,
        "submission": submitted,
        "final": final,
    }
    write_json(result_path, result)
    if result["status"] != "completed":
        raise RuntimeError(f"H3 failed for {case_id}/{variant}: {final}")
    paths = final.get("file_paths", [])
    if not paths or not all(Path(item).is_file() and Path(item).stat().st_size > 0 for item in paths):
        raise RuntimeError(f"H3 completed without verified decoded files: {case_id}/{variant}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("cases", nargs="+")
    parser.add_argument("--base-url", default="http://127.0.0.1:30011")
    parser.add_argument("--prompt-timeout-seconds", type=int, default=43200)
    args = parser.parse_args()
    health = api(args.base_url, "GET", "/health", timeout=30)
    if health.get("status") != "ok":
        raise RuntimeError(f"H3 service unhealthy: {health}")

    summary = []
    for case_id in args.cases:
        for variant in ("detailed", "vague"):
            prompt = wait_for_variant(args.root, case_id, variant, args.prompt_timeout_seconds)
            summary.append(run_one(args.base_url, args.root, case_id, variant, prompt))
            write_json(args.root / "local_ir_h3_480_summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
