#!/usr/bin/env python3
"""Run vague/detailed Context-IR A/B cases with shared perception evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ASSETS = ROOT / "assets" / "ab_tests_20260820"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected one JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def project_asset(case_id: str, relative: str) -> Path:
    filename = Path(relative).name
    preferred = PROJECT_ASSETS / case_id / "assets" / filename
    if preferred.is_file():
        return preferred
    matches = sorted(PROJECT_ASSETS.rglob(filename))
    if len(matches) != 1:
        raise FileNotFoundError(f"Cannot uniquely map {case_id}/{relative}: {matches}")
    return matches[0]


def build_source(case_dir: Path, spec: dict[str, Any], variant: str) -> dict[str, Any]:
    prompt_path = case_dir / str(spec["input_variants"][variant])
    assets = []
    for item in spec.get("assets", []):
        label = str(item.get("role", "reference"))
        if item.get("limitations"):
            label += "; " + str(item["limitations"])
        assets.append({
            "asset_id": str(item["asset_id"]),
            "media_type": str(item["media_type"]),
            "uri": str(project_asset(str(spec["case_id"]), str(item["file"]))),
            "label": label,
        })
    task = dict(spec["task"])
    task.setdefault("style", "")
    return {
        "schema_version": "context_request.v1",
        "user_request": prompt_path.read_text(encoding="utf-8").strip(),
        "task": task,
        "assets": assets,
        "directives": [],
        "completion_policy": {
            "technical": True,
            "conservative_semantic": True,
            "creative": False,
        },
        "resolved_request": "",
        "open_questions": [],
    }


def run_one(input_path: Path, output_path: Path, perception_from: Path | None = None) -> None:
    command = ["bash", str(ROOT / "deploy" / "run.sh"), str(input_path), "--output-dir", str(output_path)]
    if perception_from is not None:
        command.extend(["--perception-from", str(perception_from)])
    subprocess.run(command, cwd=ROOT, check=True)
    audit = read_json(output_path / "h3_prompt_audit.json")
    if not audit.get("passed"):
        raise RuntimeError(f"Prompt audit failed: {output_path}")


def publish_candidate(case_dir: Path, candidate: Path, revision: str) -> None:
    current = case_dir / "B_context_ir"
    if current.exists():
        archive = case_dir / "_archive"
        archive.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        current.rename(archive / f"B_context_ir_pre_{revision}_{stamp}")
    candidate.rename(current)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("cases", nargs="+")
    parser.add_argument("--revision", default="a4b925e")
    args = parser.parse_args()

    status_path = args.base / "local_ir_suite_status.json"
    status = {"revision": args.revision, "cases": {}}
    for case_id in args.cases:
        case_dir = args.base / case_id
        spec = read_json(case_dir / "case_spec.json")
        input_dir = case_dir / "_run_inputs" / args.revision
        detailed_input = input_dir / "detailed.json"
        vague_input = input_dir / "vague.json"
        write_json(detailed_input, build_source(case_dir, spec, "detailed"))
        write_json(vague_input, build_source(case_dir, spec, "vague"))

        candidate = case_dir / f"B_context_ir_candidate_{args.revision}"
        if candidate.exists():
            raise FileExistsError(f"Candidate already exists: {candidate}")
        status["cases"][case_id] = {"status": "running", "phase": "detailed"}
        write_json(status_path, status)
        try:
            run_one(detailed_input, candidate / "detailed")
            status["cases"][case_id]["phase"] = "vague"
            write_json(status_path, status)
            run_one(vague_input, candidate / "vague", candidate / "detailed" / "media_analysis.json")
            publish_candidate(case_dir, candidate, args.revision)
            status["cases"][case_id] = {"status": "completed", "output": str(case_dir / "B_context_ir")}
        except Exception as exc:
            status["cases"][case_id] = {"status": "failed", "error": str(exc), "candidate": str(candidate)}
            write_json(status_path, status)
            raise
        write_json(status_path, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
