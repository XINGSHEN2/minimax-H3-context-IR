#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${WEB_SMOKE_PORT:-38089}"
log="$(mktemp /tmp/context-ir-web.XXXXXX.log)"
python3 -m backend.api --host 127.0.0.1 --port "$port" >"$log" 2>&1 &
server_pid=$!
cleanup() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
  rm -f "$log"
}
trap cleanup EXIT

for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$port/api/health" >/tmp/context-ir-health.json 2>/dev/null; then break; fi
  sleep .1
done

curl -fsS "http://127.0.0.1:$port/" >/tmp/context-ir-index.html
curl -fsS "http://127.0.0.1:$port/styles.css" >/tmp/context-ir-styles.css
curl -fsS "http://127.0.0.1:$port/app.js" >/tmp/context-ir-app.js
grep -q 'H3 Context Studio' /tmp/context-ir-index.html
grep -q '生成 Context-IR' /tmp/context-ir-index.html
grep -q '/api/jobs' /tmp/context-ir-app.js

python3 - <<'PY'
import json
from pathlib import Path
health = json.loads(Path('/tmp/context-ir-health.json').read_text())
assert health['ok'] is True
assert 'vlm' in health['services'] and 'glm' in health['services']
print(json.dumps({'passed': True, 'frontend': True, 'health': health['services']}, ensure_ascii=False))
PY
