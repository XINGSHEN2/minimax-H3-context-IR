"""Copy completed local-only prompt runs into their actual Feishu case versions."""
import hashlib
import json
from pathlib import Path
import shutil

REPO = Path('/home/mx/shenxing/minimax-H3-context-IR')
BASE = Path('/home/mx/shenxing/minimax-H3-data/minimax-H3-feishu-cases/1.商用级多场景生成/1.1 品牌大片与影视内容').resolve(strict=True)
RUNS = [
    (1, 'feishu_case1_formal_content_20260907', 'local_ir_260907_01'),
    (2, 'feishu_case2_formal_content_20260907', 'local_ir_260907_01'),
    (3, 'feishu_case3_formal_content_20260907', 'local_ir_260907_01'),
    (4, 'feishu_case4_formal_multiview_20260907', 'local_ir_260907_full_record'),
    (4, 'feishu_case4_formal_fresh_character_20260907', 'local_ir_260907_01'),
    (4, 'feishu_case4_formal_goal_coverage_20260907', 'local_ir_260907_02'),
    (4, 'feishu_case4_final_style_scope_20260907', 'local_ir_260907_03'),
    (5, 'feishu_case5_formal_content_20260907', 'local_ir_260907_full_record'),
]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for case, name, version in RUNS:
    source = REPO / 'outputs' / name
    target = BASE / f'case{case}-ref2va/output' / version
    assert target.resolve().is_relative_to(BASE)
    assert all((source / f).is_file() for f in ('context_ir.json', 'h3_prompt.txt', 'h3_request.json'))
    if target.exists():
        manifest = json.loads((target / 'archive_manifest.json').read_text())
        assert manifest['source_run'] == str(source)
        assert digest(target / 'h3_prompt.txt') == digest(source / 'h3_prompt.txt')
        print(json.dumps({'case': case, 'target': str(target), 'already_archived': True}, ensure_ascii=False))
        continue
    # Only trusted completed output directories; never traverse source symlinks.
    assert not any(p.is_symlink() for p in [source, *source.rglob('*')])
    shutil.copytree(source, target)
    assert digest(target / 'h3_prompt.txt') == digest(source / 'h3_prompt.txt')
    video_relation = 'See ../local_ir_260907: same prompt has a completed video.' if version.endswith('full_record') else 'No video generated from this prompt version.'
    manifest = {'source_run': str(source), 'case_directory': str(target.parent.parent),
                'prompt_sha256': digest(target / 'h3_prompt.txt'),
                'video_relationship': video_relation,
                'request_note': 'Historical h3_request paths preserved for provenance; rebuild request before a new submission.',
                'official_baseline': '../official_ir/'}
    (target / 'archive_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (target / 'VERSION_README.md').write_text(
        f'# {version}\n\n来源：`{name}`\n\n[H3 Prompt](h3_prompt.txt) · [Context-IR](context_ir.json)\n\n'
        f'{video_relation}\n\n官方只引用[已有结果](../official_ir/)。原始请求路径保留作记录，新生成前需重建请求。\n', encoding='utf-8')
    print(json.dumps({'case': case, 'target': str(target), 'copied': True}, ensure_ascii=False), flush=True)
