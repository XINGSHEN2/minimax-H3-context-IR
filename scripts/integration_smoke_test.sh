#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${MOCK_GLM_PORT:-38049}"
output="$root/outputs/smoke-mock-$(date +%Y%m%d-%H%M%S)"
log="$(mktemp /tmp/minimax-h3-context-ir-mock.XXXXXX.log)"

python3 "$root/scripts/mock_glm_responses.py" --port "$port" >"$log" 2>&1 &
mock_pid=$!
cleanup() {
  kill "$mock_pid" 2>/dev/null || true
  wait "$mock_pid" 2>/dev/null || true
  rm -f "$log"
}
trap cleanup EXIT

for _ in $(seq 1 30); do
  if python3 - "$port" 2>/dev/null <<'PY'
import socket, sys
with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=.2):
    pass
PY
  then
    break
  fi
  sleep .1
done

GLM_RESPONSES_BASE_URL="http://127.0.0.1:$port/v1" \
OPENAI_API_KEY="test-only-key" \
  bash "$root/deploy/run.sh" "$root/examples/request.example.json" --output-dir "$output"

python3 - "$output" <<'PY'
from pathlib import Path
import json, sys

root = Path(sys.argv[1])
required = ['input.json', 'media_analysis.json', 'agent.log', 'glm_raw_response.txt', 'context_ir.json', 'h3_prompt.txt', 'h3_prompt_audit.json', 'h3_request.json']
missing = [name for name in required if not (root / name).is_file()]
if missing:
    raise SystemExit(f'missing integration outputs: {missing}')
ir = json.loads((root / 'context_ir.json').read_text(encoding='utf-8'))
request = json.loads((root / 'h3_request.json').read_text(encoding='utf-8'))
audit = json.loads((root / 'h3_prompt_audit.json').read_text(encoding='utf-8'))
assert ir['schema_version'] == '0.1.0'
assert audit['passed'] is True
assert request['task'] == 'ref2va'
assert len(request['conditions']) == 5
print(json.dumps({'passed': True, 'output_dir': str(root), 'conditions': len(request['conditions'])}, ensure_ascii=False))
PY
