#!/usr/bin/env python3
"""Run numbered cases through Qwen-only perception and the v31 compiler."""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run(command):
    subprocess.run(command,cwd=ROOT,check=True)
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--base",type=Path,required=True); parser.add_argument("cases",nargs="+",type=int); args=parser.parse_args()
    base=args.base.resolve()
    for number in args.cases:
        case_dir=base/f"case{number}-ref2va"; output=case_dir/"output/v31-qwen_only"
        run([sys.executable,str(ROOT/"scripts/run_qwen_thinking_perception.py"),str(case_dir),"--output-dir",str(output)])
        candidates=[
            case_dir/"output/v31/evidence_input.json",
            case_dir/"output/local_ir_260909_20_prompts_65536_retry/evidence_input.json",
            case_dir/"output/local_ir_260909_20_prompts_65536/evidence_input.json",
            case_dir/"output/local_ir_260909_20_inheritance_fresh_qwen38/evidence_input.json",
            case_dir/"output/local_ir_260909_19_service_fresh_qwen38/evidence_input.json",
        ]
        baseline=next((path for path in candidates if path.is_file()),None)
        if baseline is None: raise FileNotFoundError(f"No baseline evidence_input.json for {case_dir}")
        run([sys.executable,str(ROOT/"scripts/compile_v31_qwen_only.py"),str(case_dir),"--perception",str(output/"media_analysis.json"),"--baseline-evidence",str(baseline),"--output-dir",str(output)])
    return 0
if __name__=="__main__": raise SystemExit(main())
