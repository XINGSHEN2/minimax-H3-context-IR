"""Recompile Case4 with fresh character evidence, rebuilding all bindings."""
import json
import os
from pathlib import Path
import sys
import time
import argparse
from datetime import datetime

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
from backend.capabilities import h3_prompt_generate
from backend.perception import sanitize_media_analysis_quality

base = ROOT / 'outputs/feishu_case4_formal_multiview_20260907'
parser = argparse.ArgumentParser()
parser.add_argument('--output-name', default='local_ir_' + datetime.now().strftime('%y%m%d_%H%M%S'))
args = parser.parse_args()
if Path(args.output_name).name != args.output_name or not args.output_name.startswith('local_ir_'):
    raise ValueError('output-name must be one local_ir_ prefixed directory name')
case_dir = Path('/home/mx/shenxing/minimax-H3-data/minimax-H3-feishu-cases/1.商用级多场景生成/1.1 品牌大片与影视内容/case4-ref2va').resolve(strict=True)
out = case_dir / 'output' / args.output_name
assert not out.exists(), 'Existing attempt must not be overwritten'
source = json.loads((base / 'input.json').read_text())
source.pop('perception', None)
analysis = json.loads((base / 'media_analysis.json').read_text())
fresh = json.loads((ROOT / 'outputs/feishu_case4_image_content_20260907/analysis.json').read_text())
assert fresh['asset_id'] == 'image_2'
analysis['assets'] = [fresh if a['asset_id'] == 'image_2' else a for a in analysis['assets']]
analysis = sanitize_media_analysis_quality(analysis)
assert len(next(a for a in analysis['assets'] if a['asset_id'] == 'image_2')['entities']) == 2
started = time.perf_counter()
result = h3_prompt_generate({'input_type': 'media_analysis', 'source': source,
                             'media_analysis': analysis}, output_dir=out)
(out / 'capability_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({'seconds': time.perf_counter()-started, 'output': str(out),
                  'evaluation_scope': 'visual_only'}), flush=True)
