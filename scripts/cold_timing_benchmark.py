#!/usr/bin/env python3
"""Run Context-IR cases sequentially with Qwen cache disabled."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT = Path("/home/mx/shenxing/minimax-H3-context-IR")
DATA = Path("/home/mx/shenxing/context-ir-ab-tests-20260820")
BENCHMARK = DATA / "_benchmarks" / "context_ir_nocache_case2_retry_20260824"
RUNTIME = PROJECT / "outputs" / "context_ir_nocache_case2_retry_20260824"
CASES = ("case_002_nail_state_transition",)
VARIANTS = ("detailed", "vague")

sys.path.insert(0, str(PROJECT / "scripts"))
from run_ab_suite import build_source, read_json, write_json  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize_perception(path: Path) -> dict:
    value = read_json(path)
    assets = []
    for item in value.get("assets", []):
        technical = item.get("technical", {})
        assets.append({
            "asset_id": item.get("asset_id"),
            "analysis_profile": technical.get("analysis_profile"),
            "cache_hit": technical.get("cache_hit"),
            "elapsed_seconds": technical.get("elapsed_seconds"),
            "perception_metrics": technical.get("perception_metrics", {}),
            "supplemental_attempts": item.get("supplemental_attempts", []),
        })
    return {"aggregate": value.get("perception_metrics", {}), "assets": assets}


def persist(report: dict) -> None:
    write_json(BENCHMARK / "benchmark_report.json", report)


def main() -> int:
    if BENCHMARK.exists():
        raise FileExistsError(f"Benchmark output already exists: {BENCHMARK}")
    BENCHMARK.mkdir(parents=True)
    report = {
        "schema_version": "context_ir_cold_timing_benchmark.v1",
        "started_at": utc_now(),
        "qwen_cache_enabled": False,
        "perception_reuse": False,
        "execution": "sequential",
        "runs": [],
    }
    persist(report)
    environment = os.environ.copy()
    environment["CONTEXT_IR_VLM_CACHE_ENABLED"] = "0"
    for case_id in CASES:
        case_dir = DATA / case_id
        spec = read_json(case_dir / "case_spec.json")
        for variant in VARIANTS:
            run_dir = RUNTIME / case_id / variant
            input_path = run_dir.parent / f"{variant}_input.json"
            write_json(input_path, build_source(case_dir, spec, variant))
            entry = {
                "case_id": case_id,
                "variant": variant,
                "status": "running",
                "started_at": utc_now(),
                "output_dir": str(run_dir),
            }
            report["runs"].append(entry)
            persist(report)
            started = time.perf_counter()
            try:
                with (run_dir.parent / f"{variant}.log").open("w", encoding="utf-8") as log:
                    subprocess.run(
                        ["bash", str(PROJECT / "deploy" / "run.sh"), str(input_path), "--output-dir", str(run_dir)],
                        cwd=PROJECT,
                        env=environment,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
                entry["wall_seconds"] = round(time.perf_counter() - started, 3)
                entry["stage_timings"] = read_json(run_dir / "stage_timings.json")
                entry["perception"] = summarize_perception(run_dir / "media_analysis.json")
                entry["audit_passed"] = bool(read_json(run_dir / "h3_prompt_audit.json").get("passed"))
                entry["status"] = "completed"
            except Exception as exc:
                entry["wall_seconds"] = round(time.perf_counter() - started, 3)
                entry["status"] = "failed"
                entry["error"] = str(exc)
                persist(report)
                raise
            finally:
                entry["finished_at"] = utc_now()
                persist(report)
    report["finished_at"] = utc_now()
    report["total_wall_seconds"] = round(sum(float(item.get("wall_seconds", 0)) for item in report["runs"]), 3)
    persist(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
