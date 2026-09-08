"""Fresh local-Qwen perception of the Case4 character board, no retries."""
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
from backend.perception import LocalQwen3VL32BProvider, PerceptionProviderConfig

base = ROOT / 'outputs/feishu_case4_formal_multiview_20260907'
out = ROOT / 'outputs/feishu_case4_image_content_20260907'
out.mkdir(exist_ok=False)
request = json.loads((base / 'input.json').read_text())
plans = json.loads((base / 'perception_plan.json').read_text())
asset = next(a for a in request['assets'] if a['asset_id'] == 'image_2')
plan = next(a for a in plans['assets'] if a['asset_id'] == 'image_2')
provider = LocalQwen3VL32BProvider(PerceptionProviderConfig(options={
    'output_dir': str(out), 'json_parse_retries': 0,
}))
(out / 'test_input.json').write_text(json.dumps({'asset': asset, 'plan': plan}, ensure_ascii=False, indent=2))
started = time.perf_counter()
try:
    result = provider._analyze_image_relational(asset, Path(asset['uri']), plan)
    (out / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'seconds': time.perf_counter()-started, 'output': str(out)}), flush=True)
finally:
    (out / 'timing.json').write_text(json.dumps({'seconds': time.perf_counter()-started, 'cache': False, 'json_retries': 0}))
