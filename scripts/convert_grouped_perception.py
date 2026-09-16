#!/usr/bin/env python3
"""Project one grouped-image Qwen result back onto its original asset IDs."""
from __future__ import annotations
import argparse,json
from copy import deepcopy
from pathlib import Path
from typing import Any,Mapping
from backend.perception import LocalQwen3VL32BProvider

def _sources(item: Mapping[str,Any], all_ids:list[str]) -> list[str]:
    value=item.get("source_asset_ids",[])
    if isinstance(value,list):
        found=[str(x) for x in value if str(x) in all_ids]
        if found: return found
    return list(all_ids)

def convert_grouped_result(source:Mapping[str,Any]) -> dict[str,Any]:
    grouped=source.get("grouped_image_analysis") or {}
    source_map=source.get("image_source_map") or {}
    asset_ids=[str(x) for x in source_map]
    observations={str(x.get("source_asset_id")):x for x in grouped.get("image_observations",[]) if isinstance(x,Mapping)}
    projected=[]
    for asset_id in asset_ids:
        observation=observations.get(asset_id,{})
        evidence=[]
        observation_eid=f"{asset_id}_whole_frame"
        evidence.append({"evidence_id":observation_eid,"kind":"frame","time_seconds":None,"bbox_normalized":[0.0,0.0,1.0,1.0],"description":str(observation.get("summary") or grouped.get("summary",""))})
        entities=[]
        for index,item in enumerate(grouped.get("entities",[]),1):
            if not isinstance(item,Mapping) or asset_id not in _sources(item,asset_ids): continue
            entity_id=str(item.get("entity_id") or f"entity_{index}")
            entity_eid=f"{asset_id}_{entity_id}"
            evidence.append({"evidence_id":entity_eid,"kind":"frame","time_seconds":None,"bbox_normalized":[0.0,0.0,1.0,1.0],"description":str(item.get("summary",""))})
            expanded=LocalQwen3VL32BProvider._expand_features(item)
            quantity=item.get("quantity")
            if isinstance(quantity,list) and len(quantity)>=2: expanded["quantity"]={"value":quantity[0],"confidence":float(quantity[1])}
            for values in expanded["attributes"].values():
                for feature in values: feature["evidence_ids"]=[entity_eid]
            entities.append({"entity_id":entity_id,"source_asset_ids":_sources(item,asset_ids),"evidence_ids":[entity_eid],**expanded})
        entity_ids={x["entity_id"] for x in entities}
        relations=[]
        for index,item in enumerate(grouped.get("relations",[]),1):
            if not isinstance(item,list) or len(item)<7: continue
            rid,typ,sid,oid,anchor,confidence,source_type=item[:7]
            rel_sources=[str(x) for x in item[7]] if len(item)>7 and isinstance(item[7],list) else []
            if rel_sources and asset_id not in rel_sources: continue
            if str(sid) not in entity_ids or str(oid) not in entity_ids: continue
            relations.append({"relation_id":str(rid or f"relation_{index}"),"type":str(typ),"subject_id":str(sid),"object_id":str(oid),"anchor":str(anchor),"spatial_constraints":{},"evidence_ids":[observation_eid],"confidence":float(confidence),"source":str(source_type),"source_asset_ids":rel_sources or [asset_id]})
        global_analysis=deepcopy(grouped.get("global_analysis") or {})
        for field in ("framing_layers","visible_text"):
            values=global_analysis.get(field,[])
            if isinstance(values,list):
                global_analysis[field]=[deepcopy(x) for x in values if not isinstance(x,Mapping) or asset_id in _sources(x,asset_ids)]
        uncertainties=[]
        uncertainties.extend(str(x) for x in grouped.get("uncertainties",[]))
        uncertainties.extend(str(x) for x in observation.get("uncertainties",[]))
        projected.append({"asset_id":asset_id,"summary":str(observation.get("summary") or grouped.get("summary","")),"global_analysis":global_analysis,"image_observation":deepcopy(observation),"evidence":evidence,"regions":[],"entities":entities,"relations":relations,"events":[],"technical":{"media_type":"image","analysis_pipeline":"grouped_image_projected","grouped_request_asset_ids":asset_ids},"transcript":"","uncertainties":list(dict.fromkeys(uncertainties))})
    video_analysis = source.get("video_analysis") if isinstance(source.get("video_analysis"), Mapping) else {}
    video_assets = video_analysis.get("assets", []) if isinstance(video_analysis.get("assets", []), list) else []
    projected.extend(deepcopy(item) for item in video_assets if isinstance(item, Mapping))
    image_requests = 1 if asset_ids else 0
    video_metrics = video_analysis.get("perception_metrics", {}) if isinstance(video_analysis.get("perception_metrics"), Mapping) else {}
    video_requests = int(video_metrics.get("request_count", len(video_assets)) or len(video_assets))
    return {"schema_version":"media_analysis.v1","provider":{"name":"Qwen3.8-27B","mode":"grouped_images_and_individual_videos"},"assets":projected,"missing_asset_ids":list(video_analysis.get("missing_asset_ids", [])),"perception_metrics":{"request_count":image_requests + video_requests},"experiment":{"mode":"qwen3.8_grouped_images_and_individual_videos","user_request":source.get("user_request","")}}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("input",type=Path); p.add_argument("output",type=Path); a=p.parse_args()
    source=json.loads(a.input.read_text(encoding="utf-8")); result=convert_grouped_result(source)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(a.output),"assets":len(result["assets"]),"entities_per_asset":[len(x["entities"]) for x in result["assets"]]},ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
