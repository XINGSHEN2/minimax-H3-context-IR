#!/usr/bin/env python3
"""Compile an H3 prompt from Qwen-only perception without the intent-resolver LLM."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
from backend.agent import preflight_reasoning_provider, reasoning_provider_config
from backend.compiler import compile_prompt

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("case_dir",type=Path)
    parser.add_argument("--perception",type=Path,required=True)
    parser.add_argument("--baseline-evidence",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    case_dir=args.case_dir.resolve(); output_dir=args.output_dir.resolve()
    evidence=json.loads(args.baseline_evidence.resolve().read_text(encoding="utf-8"))
    perception=json.loads(args.perception.resolve().read_text(encoding="utf-8"))
    media_paths=sorted(path for path in (case_dir/"assets").iterdir() if path.is_file())
    baseline_assets=evidence.get("assets",[])
    if len(media_paths)!=len(baseline_assets):
        raise ValueError(f"asset count mismatch: {len(media_paths)} files != {len(baseline_assets)} baseline assets")
    assets=[]
    for item,path in zip(baseline_assets,media_paths):
        assets.append({"asset_id":item["asset_id"],"media_type":item["media_type"],"uri":str(path),"label":item.get("label") or path.name,"user_role":item.get("user_role")})
    source={"schema_version":"context_request.v1","user_request":evidence["user_request"],"resolved_request":evidence.get("resolved_request") or evidence["user_request"],"task":evidence["task"],"assets":assets,"directives":evidence.get("directives",[]),"completion_policy":evidence.get("completion_policy",{"technical":True,"conservative_semantic":True,"creative":False}),"asset_mentions":evidence.get("asset_mentions",[]),"open_questions":[],"perception":perception}
    reasoning=reasoning_provider_config(); preflight_reasoning_provider(reasoning)
    timings={"schema_version":"context_ir_stage_timings.v1","perception_reused":True,"perception_mode":"qwen_only","stages_seconds":{"intent_resolver":0.0,"perception":float(perception.get("experiment",{}).get("elapsed_seconds",0.0))}}
    started=time.perf_counter()
    (output_dir/"qwen_only_source.json").write_text(json.dumps(source,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return compile_prompt(source,output_dir,reasoning,timings,started)
if __name__=="__main__": raise SystemExit(main())
