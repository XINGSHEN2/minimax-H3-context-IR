"""Read-only verification of archived candidates against current contracts."""
import json
from pathlib import Path
import sys

ROOT = Path('/home/mx/shenxing/minimax-H3-context-IR')
sys.path.insert(0, str(ROOT))
from backend.context_ir import validate_context_ir, audit_h3_prompt_contract

cases = Path('/home/mx/shenxing/minimax-H3-data/minimax-H3-feishu-cases')
image_section = cases / '1.商用级多场景生成/1.1 品牌大片与影视内容'
paths = [image_section / f'case{i}-ref2va/output/local_ir_260907_06_release_candidate' for i in range(1, 6)]
paths.append(cases / '2. 原生多模态理解与生成/2.2 角色、动作与镜头参考/case1-ref2va/output/local_ir_260907_07_camera_scope_fix')
for path in paths:
    ir = json.loads((path / 'context_ir.json').read_text())
    prompt = (path / 'h3_prompt.txt').read_text()
    ir_report = validate_context_ir(ir)
    prompt_report = audit_h3_prompt_contract(ir, prompt)
    assert ir_report.passed, (str(path), ir_report.to_dict())
    assert prompt_report.passed, (str(path), prompt_report.to_dict())
    official = path.parent / 'official_ir/official_ir_prompt.txt'
    assert official.is_file(), official
    assert all(a.get('media_type', a.get('type')) in {'image', 'video'} for a in ir['assets'])
    print(json.dumps({'path': str(path), 'ir_passed': True, 'prompt_contract_passed': True, 'original_official': str(official), 'prompt_words': len(prompt.split())}), flush=True)
