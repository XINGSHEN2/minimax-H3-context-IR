import copy
import json
from unittest.mock import patch
import pytest
from backend.capabilities import h3_prompt_generate, video_generate
from backend.contracts import build_h3_request

@pytest.mark.parametrize("input_type", ["assets", "asset_descriptions", "media_analysis"])
def test_public_inputs_use_v20_and_preserve_evidence(tmp_path, monkeypatch, input_type):
    monkeypatch.setenv("CONTEXT_IR_LLM_PROVIDER", "deepseek_litellm")
    monkeypatch.setenv("LITELLM_API_KEY", "unit-test-key")
    source = {"user_request": "Keep the red bottle and reveal its label.",
              "task": {"type": "ref2va", "duration_seconds": 5, "aspect_ratio": "16:9"},
              "assets": [{"asset_id": "image_1", "media_type": "image", "uri": "/tmp/bottle.png"}]}
    analysis = {"schema_version": "media_analysis.v2", "assets": [
        {"asset_id": "image_1", "summary": "A red bottle with a label", "entities": []}]}
    payload = {"input_type": input_type, "source": source}
    if input_type == "media_analysis": payload["media_analysis"] = analysis
    if input_type == "asset_descriptions": payload["asset_descriptions"] = [
        {"asset_id": "image_1", "description": "A red bottle with a label"}]
    before = copy.deepcopy(payload)
    answer = {"content_plan": {"bindings": [{"asset_id": "image_1"}],
              "shots": [{"start_seconds": 0, "end_seconds": 5}]},
              "h3_prompt": "<Picture 1> Reveal the label on the red bottle.", "uncertainties": []}
    def resolve(source, invoke):
        resolved = copy.deepcopy(source)
        resolved["resolved_request"] = resolved["user_request"]
        return {"source": resolved, "perception_plan": {"assets": []}}
    with patch("backend.agent.preflight_reasoning_provider"), \
         patch("backend.agent.resolve_intent", side_effect=resolve) as intent, \
         patch("backend.agent.PERCEPTION_PROVIDERS.create") as provider, \
         patch("backend.agent.invoke_reasoning_json", return_value=answer) as writer:
        provider.return_value.analyze.return_value = analysis
        result = h3_prompt_generate(payload, output_dir=tmp_path / "result")
        intent.assert_called_once()
        assert provider.return_value.analyze.call_count == (1 if input_type == "assets" else 0)
        writer.assert_called_once()
        assert writer.call_args.args[3] == ["h3-prompt-writing", "h3-shot-planning"]
        assert "red bottle" in writer.call_args.args[0]
    assert payload == before
    assert result["context_ir"]["schema_version"] == "h3_compilation.light.v1"
    assert result["h3_request"]["conditions"][0]["uri"] == "/tmp/bottle.png"
    assert result["h3_prompt_audit"]["passed"]
    assert result["h3_prompt_audit"]["semantic_quality_verified"] is False
    assert not (tmp_path / "result" / "llm_optimization.json").exists()

@pytest.mark.parametrize("mode,frames", [("t2va", []), ("i2va", [0]), ("l2va", [-1]), ("fl2va", [0,-1])])
def test_h3_task_serialization(mode, frames):
    source = {"task": {"type": mode, "duration_seconds": 5, "aspect_ratio": "16:9"},
              "assets": [{"asset_id": str(i), "media_type": "image", "uri": f"/tmp/{i}.png", "frame_index": frame}
                         for i, frame in enumerate(frames)]}
    request = build_h3_request(source, "/tmp/prompt.txt", "/tmp/video")
    assert [c["frame_index"] for c in request["conditions"]] == frames
    assert request["task"] == mode

def test_legacy_ir_input_is_rejected():
    with pytest.raises(ValueError, match="input_type must be"):
        h3_prompt_generate({"input_type": "context_ir", "context_ir": {}})

def test_video_submission_remains_explicit():
    from unittest.mock import Mock
    client = Mock()
    client.submit.return_value = {"task_id": "test"}
    client.wait.return_value = {"status": "completed"}
    request = {"task": "t2va", "prompt_file": "/tmp/prompt.txt"}
    result = video_generate({"h3_request": request}, client=client, wait=True)
    client.submit.assert_called_once_with(request)
    client.wait.assert_called_once_with("test")
    assert result["result"]["status"] == "completed"

@pytest.mark.parametrize("changes", [
    {"task": {}},
    {"task": {"type": "ref2va", "duration_seconds": float("nan"), "aspect_ratio": "16:9"}},
    {"assets": [{"asset_id": "image_1", "media_type": "image"}]},
    {"task": {"type": "fl2va", "duration_seconds": 5, "aspect_ratio": "16:9"},
     "assets": [{"asset_id": "image_1", "media_type": "image", "uri": "/tmp/a.png", "frame_index": 0}]},
])
def test_invalid_inputs_fail_before_model_or_output(tmp_path, changes):
    from backend.agent import run_agent
    source = {"user_request": "Show a bottle", "task": {"type": "t2va", "duration_seconds": 5, "aspect_ratio": "16:9"}, "assets": []}
    source.update(changes)
    with patch("backend.agent.invoke_reasoning_json") as invoke:
        with pytest.raises(ValueError): run_agent(source, tmp_path / "result", None)
        invoke.assert_not_called()
    assert not (tmp_path / "result").exists()


def test_http_exposes_only_current_compiler(monkeypatch):
    import threading
    import urllib.request
    import urllib.error
    from http.server import ThreadingHTTPServer
    from backend.api import StudioHandler
    from backend.compiler import COMPILER_REVISION
    monkeypatch.setattr("backend.api._service_status", lambda: {})
    server = ThreadingHTTPServer(("127.0.0.1", 0), StudioHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=3) as response:
            assert json.load(response)["prompt_compiler"] == COMPILER_REVISION
        with urllib.request.urlopen(base + "/api/capabilities", timeout=3) as response:
            assert json.load(response)["h3_prompt_input_types"] == ["assets", "asset_descriptions", "media_analysis"]
        with urllib.request.urlopen(base + "/", timeout=3) as response:
            assert "v20" in response.read().decode()
        request = urllib.request.Request(base + "/api/h3/prompt", data=json.dumps({"input_type": "context_ir", "context_ir": {}}).encode(), headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=3)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
