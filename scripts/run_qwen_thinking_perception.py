#!/usr/bin/env python3
"""Run Qwen3.8 thinking-only perception without the text LLM intent resolver."""
from __future__ import annotations
import argparse, json, threading, time, uuid
from pathlib import Path
from typing import Any, Mapping
from backend.perception import LocalQwen3VL32BProvider, PerceptionProviderConfig

class RecordingThinkingProvider(LocalQwen3VL32BProvider):
    def __init__(self, config: PerceptionProviderConfig, response_dir: Path) -> None:
        super().__init__(config); self.response_dir=response_dir; self.response_dir.mkdir(parents=True,exist_ok=True); self.response_lock=threading.Lock()
    def _request_json(self, method: str, path: str, payload: Mapping[str, Any] | None=None, timeout: float=30.0, base_url: str | None=None) -> dict[str, Any]:
        response=super()._request_json(method,path,payload,timeout,base_url)
        message=((response.get("choices") or [{}])[0].get("message") or {})
        record={"endpoint":(base_url or "")+path,"model":(payload or {}).get("model"),"enable_thinking":((payload or {}).get("chat_template_kwargs") or {}).get("enable_thinking"),"reasoning_content":message.get("reasoning_content"),"content":message.get("content"),"usage":response.get("usage"),"x_task_id":response.get("x_task_id")}
        with self.response_lock:
            (self.response_dir/f"{time.time_ns()}_{uuid.uuid4().hex}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return response

def media_type(path: Path) -> str:
    return "video" if path.suffix.lower() in {".mp4",".mov",".mkv",".avi",".webm",".m4v"} else "image"

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("case_dir",type=Path); parser.add_argument("--output-dir",type=Path,required=True); args=parser.parse_args()
    case_dir=args.case_dir.resolve(); output_dir=args.output_dir.resolve(); output_dir.mkdir(parents=True,exist_ok=False)
    user_request=(case_dir/"prompt.txt").read_text(encoding="utf-8").strip()
    paths=sorted(path for path in (case_dir/"assets").iterdir() if path.is_file())
    assets=[{"asset_id":f"{media_type(path)}_{index}","media_type":media_type(path),"uri":str(path),"user_role":"reference"} for index,path in enumerate(paths,start=1)]
    plan={"mode":"qwen_thinking_direct","user_request":user_request,"assets":[{"asset_id":asset["asset_id"],"role":asset["user_role"],"user_claimed_category":"","analyze":["先理解整张素材的结构，再识别重要主体、场景、关系、动作和可见文字","结合用户原始需求确定观察重点，但只输出素材中可见或明确标为不确定的证据",f"用户原始需求：{user_request}"],"evidence_requirements":[],"do_not_infer":["不要把用户需求当成可见事实","不要推断品牌、身份、所有权、声音或未展示的动作"]} for asset in assets]}
    config=PerceptionProviderConfig(provider="local-qwen3-vl-32b",model="Qwen3.8-27B",options={"image_base_url":"http://10.6.157.43:9012","video_base_url":"http://10.6.157.43:9012","asset_upload_base_url":"http://10.0.96.114:30100","output_dir":str(output_dir/"qwen_work"),"cache_enabled":False,"max_parallel_assets":0,"single_pass_image_analysis":True,"single_pass_video_analysis":True,"max_tokens":6000,"relational_image_max_tokens":6000,"video_single_pass_max_tokens":6000,"enable_thinking":True,"temperature":0.0,"timeout_seconds":1800,"video_fps":2.0,"video_max_frames":256})
    provider=RecordingThinkingProvider(config,output_dir/"raw_responses"); started=time.perf_counter(); result=provider.analyze(assets,plan)
    result["experiment"]={"mode":"qwen3.8_thinking_without_text_llm","elapsed_seconds":round(time.perf_counter()-started,3),"user_request":user_request}
    (output_dir/"perception_plan.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output_dir/"media_analysis.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"output_dir":str(output_dir),"assets":len(assets),"elapsed_seconds":result["experiment"]["elapsed_seconds"],"requests":result.get("perception_metrics",{}).get("request_count")},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
