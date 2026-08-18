#!/usr/bin/env python3
"""Test-only OpenAI Responses SSE stub for the Codex integration smoke test."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


IR = {
    "schema_version": "0.1.0",
    "runtime": {
        "perception_provider": {"name": "gitee-qwen3-vl", "model": "Qwen3-VL-30B-A3B-Instruct", "options": {}},
        "reasoning_provider": {"provider": "glm", "model": "GLM-5.2"},
        "generation_provider": {"provider": "minimax", "model": "MiniMax-H3"},
    },
    "intent": {
        "user_request": "让图片1中的女生穿图片2的衣服，参考视频1的动作跳舞，歌声参考音频1，最后展示图片3中的商品。",
        "resolved_request": "Create a dance-led product advertisement with isolated references",
        "assumptions": [],
        "uncertainties": ["Logo text has not been OCR verified"],
    },
    "task": {"type": "ref2va", "duration_seconds": 15, "aspect_ratio": "9:16", "generate_audio": True, "style": "premium commercial, photorealistic"},
    "assets": [
        {"asset_id":"image_1","media_type":"image","uri":"/data/image_1.png","label":"Picture 1"},
        {"asset_id":"image_2","media_type":"image","uri":"/data/image_2.png","label":"Picture 2"},
        {"asset_id":"image_3","media_type":"image","uri":"/data/image_3.png","label":"Picture 3"},
        {"asset_id":"video_1","media_type":"video","uri":"/data/video_1.mp4","label":"Video 1"},
        {"asset_id":"audio_1","media_type":"audio","uri":"/data/audio_1.wav","label":"Audio 1"},
    ],
    "asset_bindings": [
        {"binding_id":"b_identity","asset_id":"image_1","target":"Subject 1","role":"identity","priority":"hard","inherit":["face identity"],"exclude":["outfit","background"]},
        {"binding_id":"b_outfit","asset_id":"image_2","target":"Subject 1 outfit","role":"outfit","priority":"hard","inherit":["garment design"],"exclude":["person identity","background"]},
        {"binding_id":"b_product","asset_id":"image_3","target":"Product 1","role":"product","priority":"hard","inherit":["product geometry"],"exclude":["person","background"]},
        {"binding_id":"b_motion","asset_id":"video_1","target":"Subject 1 motion","role":"motion","priority":"soft","inherit":["body motion"],"exclude":["performer identity","outfit","scene"]},
        {"binding_id":"b_voice","asset_id":"audio_1","target":"Voice 1","role":"voice","priority":"soft","inherit":["vocal character","beat timing"],"exclude":["source noise"]},
    ],
    "isolation_rules": [
        {"binding_id":"b_identity","allow":["face identity"],"block":["outfit","background"]},
        {"binding_id":"b_outfit","allow":["garment design"],"block":["person identity","background"]},
        {"binding_id":"b_product","allow":["product geometry"],"block":["person","background"]},
        {"binding_id":"b_motion","allow":["body motion"],"block":["performer identity","outfit","scene"]},
        {"binding_id":"b_voice","allow":["vocal character","beat timing"],"block":["source noise"]},
    ],
    "constraints": {"preserve":["face identity","product geometry"],"allow_change":["lighting","background"],"prohibit":["identity drift","product deformation","unverified logo text"]},
    "timeline": [
        {"shot_id":"01","start_seconds":0,"end_seconds":3,"event":"Establish the subject and outfit","action":"Face camera","camera":"stable medium shot","lighting":"premium soft key","transition":"clean cut","asset_refs":["image_1","image_2"],"binding_refs":["b_identity","b_outfit"]},
        {"shot_id":"02","start_seconds":3,"end_seconds":8,"event":"Perform the referenced dance phrase","action":"Follow body motion","camera":"controlled follow","lighting":"consistent","transition":"beat aligned","asset_refs":["video_1","audio_1"],"binding_refs":["b_motion","b_voice"]},
        {"shot_id":"03","start_seconds":8,"end_seconds":12,"event":"Present the product","action":"Readable product pose","camera":"move to close-up","lighting":"product highlights","transition":"motivated cut","asset_refs":["image_3"],"binding_refs":["b_product"]},
        {"shot_id":"04","start_seconds":12,"end_seconds":15,"event":"Product hero ending","action":"Hold stable","camera":"macro push-in","lighting":"controlled highlights","transition":"final hold","asset_refs":["image_3"],"binding_refs":["b_product"]},
    ],
    "audio_plan": {"voice":"Follow Audio 1 vocal character","music":"Beat-led premium track","sound_effects":"Subtle movement accents","ambient_sound":"Restrained studio tone","sync_rules":["Dance accents align to beat timing"]},
    "generation_description": {"cinematography":"Clean commercial framing","lighting":"Soft premium light","materials":"Accurate textile and product surfaces","performance":"Controlled confident movement","continuity":"Stable identity, outfit, and product geometry"},
}


def event(name: str, data: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/responses":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        output = json.dumps(IR, ensure_ascii=False)
        now = int(time.time())
        response_id = "resp_context_ir_smoke"
        message = {"id":"msg_context_ir_smoke","type":"message","status":"completed","role":"assistant","content":[{"type":"output_text","text":output,"annotations":[],"logprobs":[]}]}
        response = {
            "id": response_id, "object": "response", "created_at": now,
            "status": "completed", "error": None, "incomplete_details": None,
            "instructions": None, "max_output_tokens": None,
            "model": request.get("model", "sglang-pd"), "output": [message],
            "parallel_tool_calls": True, "previous_response_id": None,
            "reasoning": {"effort":"low","summary":None}, "store": False,
            "temperature": None, "text": {"format":{"type":"text"}},
            "tool_choice": "auto", "tools": request.get("tools", []),
            "top_p": None, "truncation": "disabled",
            "usage": {"input_tokens":1,"input_tokens_details":{"cached_tokens":0},"output_tokens":1,"output_tokens_details":{"reasoning_tokens":0},"total_tokens":2},
            "user": None, "metadata": {},
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        events = [
            ("response.created", {"type":"response.created","response":{**response,"status":"in_progress","output":[]}}),
            ("response.output_item.added", {"type":"response.output_item.added","output_index":0,"item":{**message,"status":"in_progress","content":[]}}),
            ("response.content_part.added", {"type":"response.content_part.added","item_id":message["id"],"output_index":0,"content_index":0,"part":{"type":"output_text","text":"","annotations":[],"logprobs":[]}}),
            ("response.output_text.delta", {"type":"response.output_text.delta","item_id":message["id"],"output_index":0,"content_index":0,"delta":output,"logprobs":[]}),
            ("response.output_text.done", {"type":"response.output_text.done","item_id":message["id"],"output_index":0,"content_index":0,"text":output,"logprobs":[]}),
            ("response.content_part.done", {"type":"response.content_part.done","item_id":message["id"],"output_index":0,"content_index":0,"part":message["content"][0]}),
            ("response.output_item.done", {"type":"response.output_item.done","output_index":0,"item":message}),
            ("response.completed", {"type":"response.completed","response":response}),
        ]
        for name, data in events:
            self.wfile.write(event(name, data))
            self.wfile.flush()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=38049)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
