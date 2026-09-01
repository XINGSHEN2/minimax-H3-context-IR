"""Replaceable JSON-only LLM runtimes used by Context-IR compiler stages."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


class JsonLLMRuntime(Protocol):
    def invoke_json(
        self,
        prompt: str,
        *,
        system_parts: Sequence[str] = (),
        log_path: Path | None = None,
    ) -> dict[str, Any]: ...


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start < 0:
            raise ValueError("LLM response did not contain a JSON object")
        value, _ = json.JSONDecoder().raw_decode(stripped[start:])
    if not isinstance(value, dict):
        raise ValueError("LLM response root must be an object")
    return value


@dataclass(frozen=True)
class DirectChatRuntime:
    """OpenAI-compatible Chat Completions runtime with no tool dependency."""

    base_url: str
    model: str
    api_key_env: str
    timeout_seconds: float = 600.0
    host_header_env: str = ""

    def invoke_json(
        self,
        prompt: str,
        *,
        system_parts: Sequence[str] = (),
        log_path: Path | None = None,
    ) -> dict[str, Any]:
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            raise RuntimeError(f"missing LLM API key environment variable: {self.api_key_env}")
        system = "\n\n".join(part.strip() for part in system_parts if part.strip())
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": int(os.environ.get("CONTEXT_IR_LLM_MAX_TOKENS", "16384")),
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        endpoint = self.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self.host_header_env and os.environ.get(self.host_header_env):
            headers["Host"] = os.environ[self.host_header_env]
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            # Some compatible gateways do not implement response_format.
            incompatible_json_mode = any(
                marker in detail.casefold()
                for marker in ("response_format", "grammar", "json schema", "json_schema")
            )
            if exc.code in {400, 422, 501} and incompatible_json_mode:
                payload.pop("response_format", None)
                request = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
            else:
                raise RuntimeError(f"LLM Chat Completions failed ({exc.code}): {detail}") from exc
        choices = response_payload.get("choices") or []
        if not choices:
            raise RuntimeError("LLM Chat Completions returned no choices")
        message = choices[0].get("message") or {}
        raw = str(message.get("content") or "")
        repaired_raw = ""
        try:
            result = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as first_error:
            repair_payload = dict(payload)
            repair_payload.pop("response_format", None)
            repair_payload["messages"] = list(payload["messages"]) + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "The previous response is malformed JSON. Repair syntax only and return "
                        "the complete JSON object with no Markdown or explanation. Preserve all "
                        "semantic fields and values."
                    ),
                },
            ]
            repair_request = urllib.request.Request(
                endpoint,
                data=json.dumps(repair_payload, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(repair_request, timeout=self.timeout_seconds) as response:
                    repaired_payload = json.loads(response.read().decode("utf-8"))
                repaired_choices = repaired_payload.get("choices") or []
                repaired_raw = str((repaired_choices[0].get("message") or {}).get("content") or "")
                result = _extract_json(repaired_raw)
            except Exception as repair_error:
                raise ValueError(
                    f"LLM returned malformed JSON and repair failed: {first_error}; {repair_error}"
                ) from repair_error
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                json.dumps(
                    {"runtime": "direct_chat", "endpoint": endpoint, "model": self.model},
                    ensure_ascii=False,
                )
                + "\n"
                + raw
                + ("\n\n--- JSON REPAIR ---\n" + repaired_raw if repaired_raw else ""),
                encoding="utf-8",
            )
        return result


def direct_runtime_from_config(config: Mapping[str, str]) -> DirectChatRuntime:
    base_url = (
        os.environ.get(f"{config['selection'].upper()}_CHAT_BASE_URL")
        or os.environ.get("CONTEXT_IR_LLM_CHAT_BASE_URL")
        or config["base_url"]
    )
    return DirectChatRuntime(
        base_url=base_url,
        model=config["model"],
        api_key_env=config["api_key_env"],
        timeout_seconds=float(os.environ.get("CONTEXT_IR_LLM_TIMEOUT_SECONDS", "600")),
        host_header_env=config.get("http_host_env", ""),
    )
