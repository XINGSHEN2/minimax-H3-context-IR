#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${CONTEXT_IR_IMAGE:-${CODEX_IMAGE:-yiwu_codex:latest}}"
container="${CONTEXT_IR_CONTAINER:-minimax_h3_context_ir}"
env_file="${CONTEXT_IR_ENV_FILE:-$project_dir/deploy/context_ir.env}"
web_host="${CONTEXT_IR_WEB_HOST:-0.0.0.0}"
web_port="${CONTEXT_IR_WEB_PORT:-38080}"
mode="${1:-foreground}"
pid_file="$project_dir/outputs/web.pid"
log_file="$project_dir/outputs/web.log"

if [[ -f "$env_file" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -z "${!key+x}" ]]; then export "$key=$value"; fi
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

if [[ "$mode" == "--status" ]]; then
  if docker exec "$container" sh -c "test -s '$pid_file' && kill -0 \$(cat '$pid_file')" 2>/dev/null; then
    echo "running: http://$web_host:$web_port"
    exit 0
  fi
  echo "stopped"
  exit 1
fi

if [[ "$mode" == "--stop" ]]; then
  if docker exec "$container" sh -c "test -s '$pid_file' && kill \$(cat '$pid_file') && rm -f '$pid_file'" 2>/dev/null; then
    echo "stopped"
  else
    echo "already stopped"
  fi
  exit 0
fi

docker_args=(exec)
if [[ "$mode" == "--daemon" ]]; then
  docker_args+=(-d)
else
  docker_args+=(-it)
fi

common_args=(
  -e OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  -e GITEE_AI_API_KEY="${GITEE_AI_API_KEY:-}" \
  -e YIWU_VLM_API_KEY_ENV="${YIWU_VLM_API_KEY_ENV:-GITEE_AI_API_KEY}" \
  -e YIWU_VLM_BASE_URL="${YIWU_VLM_BASE_URL:-http://127.0.0.1:9012}" \
  -e YIWU_VLM_MODEL="${YIWU_VLM_MODEL:-Qwen3-VL-32B-Instruct}" \
  -e CONTEXT_IR_VLM_PROVIDER="${CONTEXT_IR_VLM_PROVIDER:-local-qwen3-vl-32b}" \
  -e CONTEXT_IR_VIDEO_FRAME_COUNT="${CONTEXT_IR_VIDEO_FRAME_COUNT:-6}" \
  -e CONTEXT_IR_VIDEO_FPS="${CONTEXT_IR_VIDEO_FPS:-2}" \
  -e CONTEXT_IR_VIDEO_MAX_FRAMES="${CONTEXT_IR_VIDEO_MAX_FRAMES:-256}" \
  -e CONTEXT_IR_VLM_POLL_INTERVAL="${CONTEXT_IR_VLM_POLL_INTERVAL:-1}" \
  -e CONTEXT_IR_VLM_TIMEOUT_SECONDS="${CONTEXT_IR_VLM_TIMEOUT_SECONDS:-1800}" \
  -e CONTEXT_IR_VLM_OUTPUT_DIR="${CONTEXT_IR_VLM_OUTPUT_DIR:-$project_dir/outputs/qwen3-vl-32b}" \
  -e GLM_MODEL="${GLM_MODEL:-GLM-5.2}" \
  -e GLM_PROVIDER_ID="${GLM_PROVIDER_ID:-glm}" \
  -e GLM_RESPONSES_BASE_URL="${GLM_RESPONSES_BASE_URL:-http://127.0.0.1:38041/v1}" \
  -e GLM_HTTP_HOST="${GLM_HTTP_HOST:-litellm-poc.pgw.metax-tech.com}" \
  -e CONTEXT_IR_WEB_HOST="$web_host" \
  -e CONTEXT_IR_WEB_PORT="$web_port" \
  -w "$project_dir" \
  "$container"
)

if [[ "$mode" == "--daemon" ]]; then
  mkdir -p "$project_dir/outputs"
  docker "${docker_args[@]}" "${common_args[@]}" sh -c \
    "echo \$\$ > '$pid_file'; exec python -m backend.api --host '$web_host' --port '$web_port' >>'$log_file' 2>&1"
  sleep 0.4
  if docker exec "$container" sh -c "test -s '$pid_file' && kill -0 \$(cat '$pid_file')" 2>/dev/null; then
    echo "started: http://$web_host:$web_port"
    exit 0
  fi
  echo "failed to start; inspect $log_file" >&2
  exit 1
fi

exec docker "${docker_args[@]}" "${common_args[@]}" \
  python -m backend.api --host "$web_host" --port "$web_port"
