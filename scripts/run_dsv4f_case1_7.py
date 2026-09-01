#!/usr/bin/env python3
"""Compile Case 1-7 vague/detailed prompts with local dsv4f and reused VLM evidence."""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent import run_agent


DATA_ROOT = Path("/home/mx/shenxing/context-ir-ab-tests-20260820")
RUN_NAME = "D_dsv4f_atomic_20260825"
CASES = [
    "case_001_pump_multiref",
    "case_002_nail_state_transition",
    "case_003_nail_product_replacement",
    "case_004_nail_reference_isolation",
    "case_005_jewelry_reference_isolation",
    "case_006_cleaning_image_only",
    "case_007_perfume_image_only",
]


def main() -> int:
    started = time.perf_counter()
    jobs = [(case_name, variant) for case_name in CASES for variant in ("vague", "detailed")]

    def compile_one(case_name: str, variant: str) -> dict:
        case_dir = DATA_ROOT / case_name
        source_dir = case_dir / "B_context_ir" / variant
        output_dir = case_dir / RUN_NAME / variant
        item = {"case": case_name, "variant": variant, "output_dir": str(output_dir)}
        step_started = time.perf_counter()
        try:
            if (output_dir / "h3_prompt.txt").is_file() and (output_dir / "h3_prompt_audit.json").is_file():
                item.update(status="reused_passed", seconds=0.0)
                print(json.dumps(item, ensure_ascii=False), flush=True)
                return item
            source = json.loads((source_dir / "resolved_input.json").read_text(encoding="utf-8"))
            perception = source_dir / "media_analysis.json"
            if output_dir.exists():
                raise FileExistsError(f"output already exists: {output_dir}")
            run_agent(source, output_dir, None, perception_from=perception, intent_resolved=True)
            item.update(status="passed", seconds=round(time.perf_counter() - step_started, 3))
        except Exception as exc:
            item.update(status="failed", seconds=round(time.perf_counter() - step_started, 3), error=str(exc))
        print(json.dumps(item, ensure_ascii=False), flush=True)
        return item

    results = []
    workers = max(1, int(os.environ.get("CONTEXT_IR_DSV4F_CASE_WORKERS", "2")))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dsv4f-case") as executor:
        futures = [executor.submit(compile_one, case_name, variant) for case_name, variant in jobs]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: (CASES.index(item["case"]), ("vague", "detailed").index(item["variant"])))
    summary = {
        "schema_version": "dsv4f_case_suite.v1",
        "model": "deepseek-v4-flash",
        "base_url": "http://127.0.0.1:38042/v1",
        "perception": "reused B_context_ir media_analysis.v2",
        "total_seconds": round(time.perf_counter() - started, 3),
        "passed": sum(item["status"] in {"passed", "reused_passed"} for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "results": results,
    }
    summary_path = DATA_ROOT / f"{RUN_NAME}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(summary_path), "passed": summary["passed"], "failed": summary["failed"], "total_seconds": summary["total_seconds"]}, ensure_ascii=False), flush=True)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
