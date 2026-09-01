"""H3 request construction, submission, status query, and result retrieval."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class H3VideoClient:
    base_url: str = "http://127.0.0.1:30011"
    timeout_seconds: float = 60.0

    def _json(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"H3 service failed ({exc.code}): {detail}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("H3 service returned a non-object response")
        return result

    def submit(self, request_payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._json("POST", "/v1/videos", request_payload)

    def status(self, task_id: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/videos/{task_id}")

    def wait(self, task_id: str, *, timeout_seconds: float = 7200, poll_seconds: float = 5) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = self.status(task_id)
            state = str(status.get("status", status.get("state", ""))).lower()
            if state in {"completed", "succeeded", "done", "failed", "error", "cancelled"}:
                return status
            time.sleep(max(0.25, poll_seconds))
        raise TimeoutError(f"H3 generation timed out: {task_id}")


def default_h3_client() -> H3VideoClient:
    return H3VideoClient(
        base_url=os.environ.get("CONTEXT_IR_H3_BASE_URL", "http://127.0.0.1:30011"),
        timeout_seconds=float(os.environ.get("CONTEXT_IR_H3_REQUEST_TIMEOUT_SECONDS", "60")),
    )
