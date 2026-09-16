#!/usr/bin/env python3
"""Run Feishu 1.1 cases through Qwen-only perception and the v31 compiler."""
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
        run([sys.executable,str(ROOT/"scripts/compile_v31_qwen_only.py"),str(case_dir),"--perception",str(output/"media_analysis.json"),"--baseline-evidence",str(case_dir/"output/v31/evidence_input.json"),"--output-dir",str(output)])
    return 0
if __name__=="__main__": raise SystemExit(main())
