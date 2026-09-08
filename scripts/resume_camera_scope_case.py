"""Replay the failed real draft unchanged, then run the public final-writing route."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path('/home/mx/shenxing/minimax-H3-context-IR')
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
from backend.context_ir import compile_context_ir, validate_context_ir
from backend.capabilities import h3_prompt_generate

parser = argparse.ArgumentParser()
parser.add_argument('previous', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
assert not args.output.exists()
source = json.loads((args.previous / 'resolved_input.json').read_text())
draft = json.loads((args.previous / 'agent.semantic_repair.1.log').read_text().split('\n', 1)[1])
started = time.perf_counter()
ir = compile_context_ir(draft, source)
report = validate_context_ir(ir)
assert report.passed, report.to_dict()
print(json.dumps({'draft_compiled': True, 'warnings': report.to_dict().get('warnings')}), flush=True)
result = h3_prompt_generate({'input_type': 'context_ir', 'context_ir': ir}, output_dir=args.output)
for name in ['input.json', 'resolved_input.json', 'media_analysis.json', 'intent_resolution.json', 'perception_plan.json']:
    shutil.copy2(args.previous / name, args.output / name)
(args.output / 'reused_draft.json').write_text(json.dumps(draft, ensure_ascii=False, indent=2))
provenance = {
    'previous_attempt': str(args.previous), 'resume_reason': 'camera keyword false-positive hard gate',
    'intent': 'reused', 'perception': 'reused', 'planning': 'reused_unchanged_failed_draft',
    'seconds_compile_and_final_writing': time.perf_counter() - started,
    'code_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ['backend/agent.py', 'backend/context_ir.py', 'backend/directive_binding.py']},
}
(args.output / 'resume_provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2))
print(json.dumps(provenance), flush=True)
