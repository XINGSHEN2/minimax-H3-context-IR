"""Run the current public capability on Case5; evaluate visual content only."""
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

parser = argparse.ArgumentParser()
parser.add_argument('--case', choices=('case1', 'case2', 'case3', 'case5', 'action'), default='case5')
parser.add_argument('--case-dir', type=Path, help='Required for a case outside Feishu section 1.1')
parser.add_argument('--version', default='local_ir_' + datetime.now().strftime('%y%m%d_%H%M%S'))
args = parser.parse_args()
case = args.case
cases = {
    'case1': ('feishu_case1_budget64k_20260906', 'feishu_case1_formal_content_20260907'),
    'case2': ('feishu_case2_local_ir_2', 'feishu_case2_formal_content_20260907'),
    'case3': ('feishu_case3_authority_timing_20260905', 'feishu_case3_formal_content_20260907'),
    'case5': ('feishu_case5_policy_scope_20260905', 'feishu_case5_formal_content_20260907'),
    'action': ('feishu_action_audio_v2_20260905', 'feishu_action_formal_content_20260907'),
}
base = ROOT / 'outputs' / cases[case][0]
if not args.version.startswith('local_ir_') or Path(args.version).name != args.version:
    raise ValueError('version must be a local_ir_ prefixed directory name')
if args.case_dir is not None:
    case_dir = args.case_dir.resolve(strict=True)
elif case != 'action':
    case_dir = Path('/home/mx/shenxing/minimax-H3-data/minimax-H3-feishu-cases/1.商用级多场景生成/1.1 品牌大片与影视内容') / f'{case}-ref2va'
    case_dir = case_dir.resolve(strict=True)
else:
    raise ValueError('action requires its real --case-dir; do not write unrelated outputs')
out = case_dir / 'output' / args.version
if case == 'case2':
    source = json.loads((ROOT / 'assets/feishu_1_1/case2-ref2va/request.json').read_text())
    source['perception_provider'] = {
        'provider': 'local-qwen3-vl-32b', 'model': 'Qwen3-VL-32B-Instruct',
        'options': {'cache_enabled': False, 'single_pass_image_analysis': True},
    }
    payload = {'input_type': 'assets', 'source': source}
else:
    payload = {
        'input_type': 'media_analysis',
        'source': json.loads((base / 'input.json').read_text()),
        'media_analysis': json.loads((base / 'media_analysis.json').read_text()),
    }
assert not out.exists(), 'Do not overwrite or duplicate an existing attempt'
assert all(a['media_type'] in {'image', 'video'} for a in payload['source']['assets'])
if case == 'case3':
    fresh = json.loads((ROOT / 'outputs/feishu_case3_image_content_20260907/analysis.json').read_text())
    assert fresh['asset_id'] == 'image_2'
    payload['media_analysis']['assets'] = [
        fresh if a['asset_id'] == 'image_2' else a
        for a in payload['media_analysis']['assets']
    ]
    payload['source'].pop('perception', None)
started = time.perf_counter()
result = h3_prompt_generate(payload, output_dir=out)
(out / 'capability_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({'seconds': time.perf_counter() - started, 'output': str(out),
                  'evaluation_scope': 'visual_only',
                  'schema_version': result.get('schema_version')}), flush=True)
