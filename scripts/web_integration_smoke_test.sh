#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
glm_port="${WEB_MOCK_GLM_PORT:-38098}"
web_port="${WEB_INTEGRATION_PORT:-38099}"
temporary="$(mktemp -d /tmp/context-ir-web-e2e.XXXXXX)"
mock_log="$temporary/mock.log"
web_log="$temporary/web.log"

python3 "$root/scripts/mock_glm_responses.py" --port "$glm_port" >"$mock_log" 2>&1 &
mock_pid=$!
GLM_RESPONSES_BASE_URL="http://127.0.0.1:$glm_port/v1" \
OPENAI_API_KEY="test-only-key" \
CONTEXT_IR_ASSETS_DIR="$temporary/assets" \
CONTEXT_IR_OUTPUTS_DIR="$temporary/outputs" \
python3 -m backend.api --host 127.0.0.1 --port "$web_port" >"$web_log" 2>&1 &
web_pid=$!
cleanup() {
  kill "$web_pid" "$mock_pid" 2>/dev/null || true
  wait "$web_pid" "$mock_pid" 2>/dev/null || true
  rm -rf "$temporary"
}
trap cleanup EXIT

for _ in $(seq 1 50); do
  curl -fsS "http://127.0.0.1:$web_port/api/health" >/dev/null 2>&1 && break
  sleep .1
done

response="$(curl -fsS -X POST "http://127.0.0.1:$web_port/api/jobs" \
  -F 'user_request=制作一个八秒的纯文本产品广告。' \
  -F 'task_type=t2va' \
  -F 'duration_seconds=8' \
  -F 'aspect_ratio=9:16' \
  -F 'generate_audio=true' \
  -F 'style=premium commercial' \
  -F 'asset_metadata=[]')"
job_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job"]["job_id"])' <<<"$response")"

status="queued"
for _ in $(seq 1 100); do
  job="$(curl -fsS "http://127.0.0.1:$web_port/api/jobs/$job_id")"
  status="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job"]["status"])' <<<"$job")"
  [[ "$status" == "completed" || "$status" == "failed" ]] && break
  sleep .1
done
[[ "$status" == "completed" ]] || { echo "$job"; cat "$web_log"; exit 1; }

for file in context_ir.json h3_prompt.txt h3_prompt_audit.json; do
  curl -fsS "http://127.0.0.1:$web_port/api/jobs/$job_id/files/$file" >"$temporary/$file"
  test -s "$temporary/$file"
done
python3 - "$temporary" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
ir = json.loads((root / 'context_ir.json').read_text(encoding='utf-8'))
audit = json.loads((root / 'h3_prompt_audit.json').read_text(encoding='utf-8'))
assert ir['schema_version'] == '0.1.0'
assert audit['passed'] is True
print(json.dumps({'passed': True, 'web_job': 'completed', 'result_tabs': 3}, ensure_ascii=False))
PY
