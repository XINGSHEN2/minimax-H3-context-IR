"""Test fresh image evidence through the same one-call writer, preserving provenance."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path('/home/mx/shenxing/minimax-H3-context-IR')
sys.path.insert(0, str(ROOT))
for line in (ROOT / 'deploy/context_ir.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('\"\''))
os.environ.update({
    'CONTEXT_IR_LLM_PROVIDER': 'deepseek', 'CONTEXT_IR_LLM_RUNTIME': 'direct',
    'DEEPSEEK_MODEL': 'deepseek-v4-flash',
    'DEEPSEEK_RESPONSES_BASE_URL': 'https://api.deepseek.com',
    'DEEPSEEK_CHAT_BASE_URL': 'https://api.deepseek.com',
    'CONTEXT_IR_LLM_MAX_TOKENS': '65536', 'CONTEXT_IR_DEEPSEEK_REASONING_EFFORT': 'high',
})
from backend.agent import CORE_SKILLS, _compact_final_editor_source, invoke_reasoning_json_with_retry, reasoning_provider_config
from backend.compact_writer import write_compact_prompt
from backend.perception import sanitize_media_analysis_quality

baseline = ROOT / 'outputs/feishu_case3_authority_timing_20260905'
fresh = ROOT / 'outputs/feishu_case3_image_content_20260907/analysis.json'
out = ROOT / 'outputs' / (sys.argv[1] if len(sys.argv) > 1 else 'feishu_case3_fresh_image_prompt_20260907')
out.mkdir(exist_ok=False)
source = json.loads((baseline / 'input.json').read_text())
media = json.loads((baseline / 'media_analysis.json').read_text())
replacement = json.loads(fresh.read_text())
for i, asset in enumerate(media['assets']):
    if asset['asset_id'] == replacement['asset_id']:
        media['assets'][i] = replacement
        break
else:
    raise ValueError('Replacement asset missing in baseline')
source['perception'] = sanitize_media_analysis_quality(media)
evidence = _compact_final_editor_source(source)
def save(name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
save('evidence_input.json', evidence)
save('provenance.json', {'baseline': str(baseline), 'fresh_analysis': str(fresh),
     'fresh_sha256': hashlib.sha256(fresh.read_bytes()).hexdigest(),
     'image_1_reused': True, 'image_2_reanalyzed': True})
start = time.perf_counter()
result = write_compact_prompt(evidence, lambda prompt: invoke_reasoning_json_with_retry(
    prompt, reasoning_provider_config(), out / 'writer.log', list(CORE_SKILLS), retries=0))
save('writer_result.json', result)
(out / 'h3_prompt.txt').write_text(result['h3_prompt'])
save('timing.json', {'writer_seconds': time.perf_counter()-start, 'canonical_ir_generated': False})
print(json.dumps({'output': str(out), 'writer_seconds': time.perf_counter()-start}), flush=True)
