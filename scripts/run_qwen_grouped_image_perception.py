#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,time
from pathlib import Path
from backend.perception import RELATIONAL_IMAGE_PROMPT,PerceptionProviderConfig,_json_object
from scripts.run_qwen_thinking_perception import RecordingThinkingProvider,media_type

GROUP_PROMPT='''

这是同一用户任务中的多张参考图片。消息中的图片顺序与下面的 source_asset_id 顺序完全一致。请先逐图观察，再进行跨图归并。
额外规则：
1. 每个 entity 必须增加 source_asset_ids 数组，列出支持该实体的图片编号。
2. 每个 relation、framing_layer 和 visible_text 也增加 source_asset_ids。
3. 只有外观、结构或上下文存在充分一致证据时，才把跨图内容归为同一实体；证据不足时保持分离，并写入 uncertainties。
4. 图片排列顺序不是时间、镜头或动作顺序。
5. 多视角参考可以合并互补特征；冲突特征必须分别记录来源，不得静默覆盖。
6. 九宫格、拼图或分镜板先逐格解析，再判断格子之间是否是同一主体。
7. 输出增加 image_observations 数组，每项格式为 {"source_asset_id":"image_1","summary":"该图独立观察","entity_ids":[],"uncertainties":[]}。
只返回一个完整 JSON 对象。'''

def main():
 p=argparse.ArgumentParser(); p.add_argument('case_dir',type=Path); p.add_argument('--output-dir',type=Path,required=True); a=p.parse_args()
 case=a.case_dir.resolve(); out=a.output_dir.resolve(); out.mkdir(parents=True,exist_ok=False)
 prompt=(case/'prompt.txt').read_text().strip(); paths=sorted(x for x in (case/'assets').iterdir() if x.is_file())
 images=[x for x in paths if media_type(x)=='image']; videos=[x for x in paths if media_type(x)=='video']
 cfg=PerceptionProviderConfig(provider='local-qwen3-vl-32b',model='Qwen3.8-27B',options={'image_base_url':os.environ['QWEN_IMAGE_UNDERSTAND_BASE_URL'],'video_base_url':os.environ['QWEN_VIDEO_UNDERSTAND_BASE_URL'],'asset_upload_base_url':os.environ['QWEN_ASSET_UPLOAD_BASE_URL'],'output_dir':str(out/'qwen_work'),'cache_enabled':False,'max_parallel_assets':0,'single_pass_video_analysis':True,'video_single_pass_max_tokens':6000,'enable_thinking':True,'temperature':0.0,'timeout_seconds':7200,'video_fps':2.0,'video_max_frames':256})
 provider=RecordingThinkingProvider(cfg,out/'raw_responses')
 result={'schema_version':'grouped-image-v1','user_request':prompt,'image_source_map':{},'grouped_image_analysis':None,'video_analysis':None}
 if images:
  ids=[f'image_{i}' for i in range(1,len(images)+1)]; result['image_source_map']={k:str(v) for k,v in zip(ids,images)}
  guide='\n图片编号与文件名：'+json.dumps({k:v.name for k,v in zip(ids,images)},ensure_ascii=False)+'\n用户原始需求：'+prompt
  content=[{'type':'text','text':RELATIONAL_IMAGE_PROMPT+GROUP_PROMPT+guide}]
  for path in images: content.append({'type':'image_url','image_url':{'url':provider._media_url(path)}})
  payload={'model':cfg.model,'messages':[{'role':'user','content':content}],'max_tokens':8000,'stream':False,'temperature':0.0,'top_p':0.9}
  response=provider._request_json('POST','/v1/chat/completions',payload,7200,cfg.options['image_base_url'])
  text=str(response['choices'][0]['message']['content']); final=text.split('</think>',1)[1].strip() if '</think>' in text else text
  result['grouped_image_analysis']=_json_object(final)
 if videos:
  assets=[{'asset_id':f'video_{i}','media_type':'video','uri':str(path),'user_role':'reference'} for i,path in enumerate(videos,1)]
  plan={'mode':'qwen_thinking_direct','user_request':prompt,'assets':[{'asset_id':x['asset_id'],'role':'reference','analyze':['逐段分析该视频的可见主体、动作、场景、镜头与变化',f'用户原始需求：{prompt}'],'evidence_requirements':[],'do_not_infer':['不要把用户需求当成可见事实']} for x in assets]}
  result['video_analysis']=provider.analyze(assets,plan)
 (out/'grouped_media_analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'output':str(out),'images':len(images),'videos':len(videos)},ensure_ascii=False))
if __name__=='__main__': main()
