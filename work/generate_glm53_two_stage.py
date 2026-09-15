import os,sys,json,time,threading,urllib.request,shutil,hashlib,traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path('/home/xingshen/minimax-H3-context-IR');sys.path.insert(0,str(ROOT))
from backend.agent import invoke_reasoning_json,CORE_SKILLS
from backend.prompt_instructions import build_content_outline_prompt,build_shots_from_outline_prompt,build_h3_from_plan_prompt
from backend.compiler import transport_issues,prepare_writer_evidence,COMPILER_REVISION
BASE=Path('/home/xingshen/minimax-H3-data/minimax-H3-feishu-cases/1.商用级多场景生成/1.1 品牌大片与影视内容')
VERSION='glm53_three_stage_stream_v2'
CASES=[int(x) for x in sys.argv[1:]] or list(range(1,6))
for n in CASES:assert not (BASE/f'case{n}-ref2va/output'/VERSION).exists(),VERSION+' already exists'
for line in (ROOT/'deploy/context_ir.env').read_text().splitlines():
 if '=' in line and not line.lstrip().startswith('#'):
  k,v=line.split('=',1);os.environ[k.strip()]=v.strip().strip(chr(34)+chr(39))
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','CONTEXT_IR_LLM_CHAT_BASE_URL','DEEPSEEK_CHAT_BASE_URL']:os.environ.pop(k,None)
os.environ.update(CONTEXT_IR_LLM_RUNTIME='direct',CONTEXT_IR_LLM_MAX_TOKENS='16384',CONTEXT_IR_LLM_TIMEOUT_SECONDS='1800',CONTEXT_IR_LLM_THINKING='disabled',CONTEXT_IR_LLM_STREAM='1',CONTEXT_IR_LLM_JSON_MODE='0')
os.environ.pop('CONTEXT_IR_DEEPSEEK_REASONING_EFFORT',None)
config={'selection':'glm','base_url':'https://llm-gw.kai.metax-tech.com/v1','model':'sha/GLM-5.3','api_key_env':'LITELLM_API_KEY','http_host_env':''}
out=ROOT/'work'/('glm53_two_stage_'+time.strftime('%Y%m%d_%H%M%S'));out.mkdir();(ROOT/'work/latest_glm53_two_stage.txt').write_text(str(out));shutil.copyfile(__file__,out/'run.py')
for name in ['prompt_instructions.py','compiler.py','agent.py']:shutil.copyfile(ROOT/'backend'/name,out/name)
def save(p,j):p.write_text(json.dumps(j,ensure_ascii=False,indent=2))
local=threading.local();original=urllib.request.urlopen
def capture(req,*a,**kw):
 if isinstance(req,urllib.request.Request) and req.data:
  local.calls+=1;save(local.folder/f'request_{local.calls}.json',json.loads(req.data))
 return original(req,*a,**kw)
urllib.request.urlopen=capture

def run(n):
 p=BASE/f'case{n}-ref2va/output'/VERSION;p.mkdir();local.folder=p;local.calls=0;t=time.time();m={'version':VERSION,'case':n,'status':'running','output':str(p),'model':'sha/GLM-5.3','stream':True,'thinking':False,'max_tokens_per_call':16384,'compiler_revision':COMPILER_REVISION,'reused_perception':True,'workflow':'three_streaming_requests_outline_shots_h3'};save(out/f'case{n}.json',m)
 try:
  src=p.parent/'v25/evidence_input.json';raw=json.loads(src.read_text());e=prepare_writer_evidence(raw);save(p/'evidence_input.json',e);m['source_evidence_sha256']=hashlib.sha256(src.read_bytes()).hexdigest()
  outline_prompt=build_content_outline_prompt(e);(p/'outline_instructions.txt').write_text(outline_prompt)
  outlined=invoke_reasoning_json(outline_prompt,config,p/'outline_planner.log',[]);save(p/'outline_result.json',outlined)
  outline=outlined.get('outline');assert isinstance(outline,dict),'planner returned no outline';save(p/'frozen_outline.json',outline)
  shots_prompt=build_shots_from_outline_prompt(e,outline);(p/'shot_plan_instructions.txt').write_text(shots_prompt)
  shot_result=invoke_reasoning_json(shots_prompt,config,p/'shot_planner.log',[]);save(p/'shot_plan_result.json',shot_result)
  shots=shot_result.get('shots');assert isinstance(shots,list) and shots,'planner returned no shots';plan=dict(outline);plan['shots']=shots;save(p/'frozen_content_plan.json',plan)
  h3_prompt=build_h3_from_plan_prompt(e,plan);(p/'h3_compiler_instructions.txt').write_text(h3_prompt)
  compiled=invoke_reasoning_json(h3_prompt,config,p/'h3_compiler.log',['h3-prompt-writing'])
  j={'content_plan':plan,'h3_prompt':compiled.get('h3_prompt'),'uncertainties':outlined.get('uncertainties',[])+shot_result.get('uncertainties',[])};save(p/'compilation_result.json',j);errors,warnings=transport_issues(j,e);save(p/'h3_prompt_audit.json',{'errors':errors,'warnings':warnings,'semantic_quality_verified':False,'llm_calls':3})
  if isinstance(j.get('h3_prompt'),str):(p/'h3_prompt.txt').write_text(j['h3_prompt'])
  save(p/'content_plan.json',plan);save(p/'story_outline.json',plan.get('developments',[]));save(p/'storyboard.json',plan.get('shots',[]));save(p/'uncertainties.json',j.get('uncertainties',[]))
  m.update(status='needs_review' if errors else 'generated',errors=errors,warnings=warnings,shots=len(plan.get('shots',[])),chars=len(j.get('h3_prompt','')))
 except Exception as exc:
  (p/'error.txt').write_text(traceback.format_exc())
  m.update(status='error',error_type=type(exc).__name__,error=str(exc)[:2000])
 m.update(calls=local.calls,seconds=round(time.time()-t,1));save(p/'manifest.json',m);save(out/f'case{n}.json',m);print(n,m['status'],flush=True)
with ThreadPoolExecutor(max_workers=1) as pool:list(pool.map(run,CASES))
