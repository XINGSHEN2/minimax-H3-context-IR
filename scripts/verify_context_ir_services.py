#!/usr/bin/env python3
"""Verify Context-IR providers without printing credentials."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def call(url: str, headers: dict[str, str], payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw[:500]}
        return exc.code, body


def text_from_response(body: dict) -> str:
    if body.get("output_text"):
        return str(body["output_text"])
    texts = []
    for item in body.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                texts.append(str(content["text"]))
    if texts:
        return " ".join(texts)
    message = ((body.get("choices") or [{}])[0].get("message") or {})
    return str(message.get("content") or "")


def main() -> int:
    env = load_env(Path(sys.argv[1]))
    result: dict[str, object] = {}
    gitee_status, gitee_body = call(
        env.get("YIWU_VLM_BASE_URL", "https://ai.gitee.com/v1").rstrip("/") + "/chat/completions",
        {"Authorization": "Bearer " + env.get("GITEE_AI_API_KEY", "")},
        {
            "model": env.get("YIWU_VLM_MODEL", "Qwen3-VL-30B-A3B-Instruct"),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://gitee-ai.su.bcebos.com/samples/images/doc_markdown.png"}},
                    {"type": "text", "text": "Describe the visible image in one short sentence."},
                ],
            }],
            "stream": False,
            "max_tokens": 128,
            "temperature": 0.1,
            "top_k": 1,
            "enable_thinking": False,
        },
    )
    gitee_text = text_from_response(gitee_body)
    result["vlm"] = {
        "passed": gitee_status == 200 and bool(gitee_text.strip()),
        "status": gitee_status,
        "model": gitee_body.get("model", env.get("YIWU_VLM_MODEL")),
        "sample": gitee_text[:180].replace("\n", " "),
        "error_type": ((gitee_body.get("error") or {}).get("type") if isinstance(gitee_body.get("error"), dict) else "") or "",
    }

    glm_status, glm_body = call(
        env.get("GLM_RESPONSES_BASE_URL", "http://127.0.0.1:38041/v1").rstrip("/") + "/responses",
        {
            "Authorization": "Bearer " + env.get("OPENAI_API_KEY", ""),
            "Host": env.get("GLM_HTTP_HOST", "litellm-poc.pgw.metax-tech.com"),
        },
        {
            "model": env.get("GLM_MODEL", "GLM-5.2"),
            "input": "Reply with OK only.",
            "max_output_tokens": 32,
            "stream": False,
        },
    )
    glm_text = text_from_response(glm_body)
    result["glm"] = {
        "passed": glm_status == 200 and bool(glm_text.strip()),
        "status": glm_status,
        "model": glm_body.get("model", env.get("GLM_MODEL")),
        "sample": glm_text[:180].replace("\n", " "),
        "error_type": ((glm_body.get("error") or {}).get("type") if isinstance(glm_body.get("error"), dict) else "") or "",
        "error_message": str((glm_body.get("error") or {}).get("message", ""))[:240] if isinstance(glm_body.get("error"), dict) else str(glm_body.get("message", ""))[:240],
    }
    if not result["glm"]["passed"]:
        chat_status, chat_body = call(
            env.get("GLM_RESPONSES_BASE_URL", "http://127.0.0.1:38041/v1").rstrip("/") + "/chat/completions",
            {
                "Authorization": "Bearer " + env.get("OPENAI_API_KEY", ""),
                "Host": env.get("GLM_HTTP_HOST", "litellm-poc.pgw.metax-tech.com"),
            },
            {
                "model": env.get("GLM_MODEL", "GLM-5.2"),
                "messages": [{"role": "user", "content": "Reply with OK only."}],
                "max_tokens": 32,
                "stream": False,
            },
        )
        chat_text = text_from_response(chat_body)
        result["glm_chat_fallback"] = {
            "passed": chat_status == 200 and bool(chat_text.strip()),
            "status": chat_status,
            "model": chat_body.get("model", env.get("GLM_MODEL")),
            "sample": chat_text[:180].replace("\n", " "),
            "error_message": str((chat_body.get("error") or {}).get("message", ""))[:240] if isinstance(chat_body.get("error"), dict) else str(chat_body.get("message", ""))[:240],
        }
    result["passed"] = bool(result["vlm"]["passed"] and result["glm"]["passed"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
