"""Exercise the public capability using approved Case4 text/evidence only."""
import json
import os
from pathlib import Path
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
    'CONTEXT_IR_LLM_MAX_TOKENS': '65536', 'CONTEXT_IR_DEEPSEEK_REASONING_EFFORT': 'high',
})
from backend.capabilities import h3_prompt_generate

base = ROOT / 'outputs/feishu_case4_scoped_projection_20260906'
out = ROOT / 'outputs/feishu_case4_formal_multiview_20260907'
payload = {'input_type': 'media_analysis',
    'source': json.loads((base / 'input.json').read_text()),
    'media_analysis': json.loads((base / 'media_analysis.json').read_text())}
assert not any(a['media_type'] == 'audio' for a in payload['source']['assets'])
start = time.perf_counter()
result = h3_prompt_generate(payload, output_dir=out)
(out / 'capability_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({'seconds': time.perf_counter()-start, 'output': str(out),
                  'schema_version': result.get('schema_version')}), flush=True)
