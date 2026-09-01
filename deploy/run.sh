#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${CONTEXT_IR_IMAGE:-${CODEX_IMAGE:-yiwu_codex:latest}}"
container="${CONTEXT_IR_CONTAINER:-minimax_h3_context_ir}"
env_file="${CONTEXT_IR_ENV_FILE:-$project_dir/deploy/context_ir.env}"

# Match yiwu_codex's file-based runtime configuration without committing
# secrets. Existing exported environment variables keep precedence.
if [[ -f "$env_file" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -z "${!key+x}" ]]; then
      export "$key=$value"
    fi
  done < <(grep -Ev '^[[:space:]]*(#|$)' "$env_file")
fi

if ! docker image inspect "$image" >/dev/null 2>&1; then
  echo "Missing Docker image: $image" >&2
  exit 2
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$container"; then
  docker start "$container" >/dev/null
else
  docker run -d -it \
    --name "$container" \
    --network=host \
    --security-opt seccomp=unconfined \
    --security-opt apparmor=unconfined \
    -v "$project_dir:$project_dir" \
    -w "$project_dir" \
    "$image" /bin/bash >/dev/null
fi

host_uid="$(id -u)"
host_gid="$(id -g)"
set +e
docker exec \
  -e OPENAI_API_KEY \
  -e DEEPSEEK_API_KEY \
  -e LITELLM_API_KEY="${LITELLM_API_KEY:-${OPENAI_API_KEY:-}}" \
  -e GITEE_AI_API_KEY \
  -e YIWU_VLM_API_KEY_ENV="${YIWU_VLM_API_KEY_ENV:-GITEE_AI_API_KEY}" \
  -e YIWU_VLM_BASE_URL="${YIWU_VLM_BASE_URL:-http://127.0.0.1:9012}" \
  -e QWEN_IMAGE_UNDERSTAND_BASE_URL="${QWEN_IMAGE_UNDERSTAND_BASE_URL:-http://127.0.0.1:9012}" \
  -e QWEN_VIDEO_UNDERSTAND_BASE_URL="${QWEN_VIDEO_UNDERSTAND_BASE_URL:-http://127.0.0.1:9012}" \
  -e YIWU_VLM_MODEL="${YIWU_VLM_MODEL:-Qwen3-VL-32B-Instruct}" \
  -e CONTEXT_IR_VLM_PROVIDER="${CONTEXT_IR_VLM_PROVIDER:-local-qwen3-vl-32b}" \
  -e CONTEXT_IR_VIDEO_FRAME_COUNT="${CONTEXT_IR_VIDEO_FRAME_COUNT:-6}" \
  -e CONTEXT_IR_VIDEO_FPS="${CONTEXT_IR_VIDEO_FPS:-2}" \
  -e CONTEXT_IR_VIDEO_MAX_FRAMES="${CONTEXT_IR_VIDEO_MAX_FRAMES:-256}" \
  -e CONTEXT_IR_VLM_POLL_INTERVAL="${CONTEXT_IR_VLM_POLL_INTERVAL:-1}" \
  -e CONTEXT_IR_VLM_TIMEOUT_SECONDS="${CONTEXT_IR_VLM_TIMEOUT_SECONDS:-1800}" \
  -e CONTEXT_IR_VLM_OUTPUT_DIR="${CONTEXT_IR_VLM_OUTPUT_DIR:-$project_dir/outputs/qwen3-vl-32b}" \
  -e CONTEXT_IR_VLM_CACHE_ENABLED="${CONTEXT_IR_VLM_CACHE_ENABLED:-1}" \
  -e GLM_MODEL="${GLM_MODEL:-GLM-5.2}" \
  -e GLM_PROVIDER_ID="${GLM_PROVIDER_ID:-glm}" \
  -e GLM_RESPONSES_BASE_URL="${GLM_RESPONSES_BASE_URL:-http://127.0.0.1:38041/v1}" \
  -e GLM_HTTP_HOST="${GLM_HTTP_HOST:-litellm-poc.pgw.metax-tech.com}" \
  -e CONTEXT_IR_LLM_PROVIDER="${CONTEXT_IR_LLM_PROVIDER:-deepseek_litellm}" \
  -e CONTEXT_IR_LLM_STREAM_IDLE_TIMEOUT_MS="${CONTEXT_IR_LLM_STREAM_IDLE_TIMEOUT_MS:-600000}" \
  -e CONTEXT_IR_LLM_MAX_TOKENS="${CONTEXT_IR_LLM_MAX_TOKENS:-16384}" \
  -e CONTEXT_IR_SEMANTIC_REPAIR_ATTEMPTS="${CONTEXT_IR_SEMANTIC_REPAIR_ATTEMPTS:-1}" \
  -e DEEPSEEK_LITELLM_MODEL="${DEEPSEEK_LITELLM_MODEL:-deepseek-v4-flash}" \
  -e DEEPSEEK_LITELLM_PROVIDER_ID="${DEEPSEEK_LITELLM_PROVIDER_ID:-deepseek_litellm}" \
  -e DEEPSEEK_LITELLM_RESPONSES_BASE_URL="${DEEPSEEK_LITELLM_RESPONSES_BASE_URL:-http://litellm-poc.pgw.metax-tech.com/v1}" \
  -e DEEPSEEK_LITELLM_HTTP_HOST="${DEEPSEEK_LITELLM_HTTP_HOST:-}" \
  -e DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}" \
  -e DEEPSEEK_PROVIDER_ID="${DEEPSEEK_PROVIDER_ID:-deepseek}" \
  -e DEEPSEEK_RESPONSES_BASE_URL="${DEEPSEEK_RESPONSES_BASE_URL:-https://api.deepseek.com}" \
  -w "$project_dir" \
  "$container" python agent.py "$@"
status=$?
set -e

# The SDK image runs as root. Return only this project's generated/cache files
# to the invoking host user so subsequent runs can inspect or remove them.
docker exec "$container" sh -c \
  "if [ -d '$project_dir/outputs' ]; then chown -R '$host_uid:$host_gid' '$project_dir/outputs'; fi; \
   if [ -d '$project_dir/__pycache__' ]; then chown -R '$host_uid:$host_gid' '$project_dir/__pycache__'; fi" \
  >/dev/null 2>&1 || true

exit "$status"
