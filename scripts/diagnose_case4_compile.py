"""Read-only replay of completed planner output; never invokes a model."""
import json
from pathlib import Path
import sys

root = Path('/home/mx/shenxing/minimax-H3-context-IR')
sys.path.insert(0, str(root))
from backend.context_ir import compile_context_ir, render_h3_prompt

directory = root / 'outputs/feishu_case4_formal_multiview_20260907'
header, body = (directory / 'agent.log').read_text().split('\n', 1)
source = json.loads((directory / 'resolved_input.json').read_text())
source['perception'] = json.loads((directory / 'media_analysis.json').read_text())
try:
    ir = compile_context_ir(json.loads(body), source)
    prompt = render_h3_prompt(ir)
    print(json.dumps({'compiled': True, 'prompt_characters': len(prompt)}))
except Exception as exc:
    print(json.dumps({'compiled': False, 'error_type': type(exc).__name__, 'error': str(exc)}, ensure_ascii=False))
