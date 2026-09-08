"""Frozen-code, two-worker visual planning regression across five existing cases."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('/home/mx/shenxing/minimax-H3-context-IR')
FILES = ('backend/agent.py', 'backend/context_ir.py', 'backend/directive_binding.py')
def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}

expected = hashes()
baselines = {'case1': 'local_ir_260907_01', 'case2': 'local_ir_260907_01',
             'case3': 'local_ir_260907_01', 'case4': 'local_ir_260907_04_joint_focus',
             'case5': 'local_ir_260907_02_joint_focus_regression'}
version = 'local_ir_260907_06_release_candidate'

def run(case, baseline):
    if hashes() != expected:
        return {'case': case, 'status': 'not_started_code_changed'}
    command = [sys.executable, str(ROOT / 'scripts/replay_visual_planning.py'),
               '--case', case, '--baseline', baseline, '--version', version]
    print(json.dumps({'case': case, 'status': 'starting', 'version': version}), flush=True)
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    return {'case': case, 'exit_code': result.returncode,
            'code_unchanged': hashes() == expected,
            'stdout': result.stdout, 'stderr': result.stderr}

print(json.dumps({'frozen_code_hashes': expected, 'version': version,
                  'scope': 'visual_only; intent and perception reused; production planner'}), flush=True)
failed = False
with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(run, case, baseline) for case, baseline in baselines.items()]
    for future in as_completed(futures):
        result = future.result()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        failed |= result.get('exit_code', 1) != 0 or not result.get('code_unchanged', False)
raise SystemExit(1 if failed else 0)
