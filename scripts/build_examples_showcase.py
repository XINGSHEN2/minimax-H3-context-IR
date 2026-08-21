#!/usr/bin/env python3
"""Build a self-contained Raw / local IR / official IR video showcase."""
from __future__ import annotations
import argparse, json, shutil
from pathlib import Path

GROUPS={"raw":("A_raw","Raw"),"local_ir":("B_context_ir","本地 IR"),"official_ir":("C_official_context_ir","官方 IR")}
def first(root,pattern): return next(iter(sorted(root.glob(pattern))),None)
def copy(source,target):
    if not source or not source.is_file(): return None
    target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target); return target
def main():
    p=argparse.ArgumentParser();p.add_argument("source",type=Path);p.add_argument("target",type=Path);a=p.parse_args()
    source,target=a.source.resolve(),a.target.resolve();data=target/"data"
    if data.exists(): shutil.rmtree(data)
    data.mkdir(parents=True); cases=[]
    for case_dir in sorted(source.glob("case_*")):
        if not case_dir.is_dir(): continue
        spec_path=case_dir/"case_spec.json";spec=json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists() else {}
        item={"id":case_dir.name,"title":spec.get("title") or case_dir.name.replace("_"," "),"description":spec.get("description",""),"variants":{}}
        copy(spec_path, data/case_dir.name/"case_spec.json")
        source_assets=case_dir/"assets"
        if source_assets.is_dir():
            shutil.copytree(source_assets,data/case_dir.name/"assets",dirs_exist_ok=True)
        for variant in ("vague","detailed"):
            configured_prompt=spec.get("input_variants",{}).get(variant)
            prompt_candidates=[
                case_dir/str(configured_prompt) if configured_prompt else case_dir/"__missing__",
                case_dir/f"user_prompt_{variant}.txt",
                case_dir/"inputs"/f"{variant}.txt",
                case_dir/"prompts"/f"{variant}.txt",
                case_dir/"A_raw"/variant/"user_prompt.txt",
            ]
            user_prompt=next((x for x in prompt_candidates if x.is_file()),None);v={"groups":{}}
            for key,(folder,label) in GROUPS.items():
                root=case_dir/folder/variant;out=data/case_dir.name/variant/key
                video=copy(first(root,"h3_480_15s_20steps/output/*.mp4"),out/"result.mp4")
                h3=root/"h3_prompt.txt"
                if key=="raw" and not h3.exists(): h3=user_prompt
                prompt=copy(h3,out/"h3_prompt.txt");request=copy(root/"h3_480_15s_20steps"/"request.json",out/"request.json");ir=copy(root/"context_ir.json",out/"context_ir.json")
                rel=lambda x:x.relative_to(target).as_posix() if x else None
                v["groups"][key]={"label":label,"status":"ready" if video else "missing","video":rel(video),"prompt":rel(prompt),"request":rel(request),"context_ir":rel(ir)}
            item["variants"][variant]=v
        cases.append(item)
    (target/"cases.json").write_text(json.dumps({"generated_from":str(source),"cases":cases},ensure_ascii=False,indent=2),encoding="utf-8")
    ready=sum(g["status"]=="ready" for c in cases for v in c["variants"].values() for g in v["groups"].values())
    print(f"Built {len(cases)} cases, {ready}/{len(cases)*6} videos ready: {target}")
if __name__=="__main__": main()
