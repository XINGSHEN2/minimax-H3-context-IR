"""Controlled internal-stage replay; not a fresh end-to-end API benchmark."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path('/home/mx/shenxing/minimax-H3-context-IR')
DATA = Path('/home/mx/shenxing/minimax-H3-data/minimax-H3-feishu-cases/1.商用级多场景生成/1.1 品牌大片与影视内容')
sys.path.insert(0, str(ROOT))
for line in (ROOT / 'deploy/context_ir.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('\"\''))
os.environ.update({
    'CONTEXT_IR_LLM_PROVIDER': 'deepseek', 'CONTEXT_IR_LLM_RUNTIME': 'direct',
    'DEEPSEEK_MODEL': 'deepseek-v4-flash',
    'DEEPSEEK_RESPONSES_BASE_URL': 'https://api.deepseek.com',
    'DEEPSEEK_CHAT_BASE_URL': 'https://api.deepseek.com',
    'CONTEXT_IR_LLM_MAX_TOKENS': '65536',
    'CONTEXT_IR_DEEPSEEK_REASONING_EFFORT': 'high',
})
from backend.agent import run_agent

parser = argparse.ArgumentParser()
parser.add_argument('--case', choices=['case1', 'case2', 'case3', 'case4', 'case5'], required=True)
parser.add_argument('--baseline', required=True)
parser.add_argument('--version', required=True)
parser.add_argument('--compact-planner', action='store_true', help='Experimental shorter instructions; public runtime unchanged')
args = parser.parse_args()
if args.compact_planner:
    import backend.agent as agent_module
    from backend.compact_planner import build_compact_planning_prompt
    agent_module.build_prompt = build_compact_planning_prompt
for value in (args.baseline, args.version):
    if Path(value).name != value or not value.startswith('local_ir_'):
        raise ValueError('Only local_ir_ version names within this Case are allowed')
case_dir = (DATA / (args.case + '-ref2va')).resolve(strict=True)
baseline = (case_dir / 'output' / args.baseline).resolve(strict=True)
out = case_dir / 'output' / args.version
if out.exists():
    raise FileExistsError(out)
source = json.loads((baseline / 'resolved_input.json').read_text())
source['perception'] = json.loads((baseline / 'media_analysis.json').read_text())
assert all(a['media_type'] in ('image', 'video') for a in source['assets'])
manifest = {
    'evaluation_scope': 'visual_only', 'run_type': 'controlled_internal_stage_replay',
    'intent_reused': True, 'perception_reused': True,
    'planner_variant': 'compact_experimental' if args.compact_planner else 'production',
    'baseline': str(baseline), 'output': str(out),
    'source_hashes': {name: hashlib.sha256((baseline / name).read_bytes()).hexdigest()
                      for name in ('resolved_input.json', 'media_analysis.json')},
    'code_hashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in ('backend/agent.py', 'backend/context_ir.py')},
}
if args.compact_planner:
    manifest['code_hashes']['backend/compact_planner.py'] = hashlib.sha256(
        (ROOT / 'backend/compact_planner.py').read_bytes()).hexdigest()
started = time.perf_counter()
try:
    status = run_agent(source, out, None, intent_resolved=True,
                       progress_callback=lambda phase: print(phase, flush=True))
    manifest['status'] = status
finally:
    manifest['elapsed_seconds'] = time.perf_counter() - started
    if out.is_dir():
        (out / 'experiment_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print(json.dumps(manifest, ensure_ascii=False), flush=True)
raise SystemExit(status)
