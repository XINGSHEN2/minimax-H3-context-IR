"""Replay locked IR through the production final compiler; no visual cache claims."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--direct-evidence", action="store_true",
                        help="Experimental one-call writing; does not emit or claim canonical IR")
    args = parser.parse_args()
    for line in (ROOT / "deploy/context_ir.env").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    os.environ.update({
        "CONTEXT_IR_LLM_PROVIDER": "deepseek",
        "CONTEXT_IR_LLM_RUNTIME": "direct",
        "DEEPSEEK_MODEL": "deepseek-v4-flash",
        "DEEPSEEK_RESPONSES_BASE_URL": "https://api.deepseek.com",
        "DEEPSEEK_CHAT_BASE_URL": "https://api.deepseek.com",
        "CONTEXT_IR_LLM_MAX_TOKENS": "65536",
        "CONTEXT_IR_DEEPSEEK_REASONING_EFFORT": "high",
    })
    from backend.agent import _run_final_director, reasoning_provider_config
    from backend.context_ir import build_h3_request, validate_context_ir

    args.output.mkdir(parents=True, exist_ok=False)
    read = lambda name: json.loads((args.baseline / name).read_text())
    source, draft = read("resolved_input.json"), read("context_ir.json")
    from backend.perception import sanitize_media_analysis_quality
    source["perception"] = sanitize_media_analysis_quality(read("media_analysis.json"))
    if not source["perception"].get("assets"):
        raise ValueError("comparison requires nonempty stored media evidence")
    before = json.dumps(draft, sort_keys=True, ensure_ascii=False)
    if args.direct_evidence:
        from backend.agent import CORE_SKILLS, _compact_final_editor_source, invoke_reasoning_json_with_retry
        # Use the original request and existing observations, not derived intent
        # or a previous answer. This isolates the extra semantic/compiler stages.
        original = read("input.json")
        original["perception"] = source.get("perception", {})
        evidence = _compact_final_editor_source(original)
        from backend.compact_writer import write_compact_prompt
        started = time.perf_counter()
        result = write_compact_prompt(
            evidence,
            lambda prompt: invoke_reasoning_json_with_retry(
                prompt, reasoning_provider_config(), args.output / "writer.log",
                list(CORE_SKILLS), retries=1,
            ),
        )
        prompt = result.get("h3_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("missing experimental h3_prompt")
        (args.output / "h3_prompt.txt").write_text(prompt)
        (args.output / "evidence_input.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        (args.output / "writer_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        metadata = {
            "scope": "experimental_direct_evidence_to_prompt", "baseline": str(args.baseline),
            "canonical_ir_generated": False, "production_contract_verified": False,
            "qwen_rerun": False, "intent_resolver_rerun": False,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "new_characters": len(prompt),
        }
        (args.output / "comparison_metadata.json").write_text(json.dumps(metadata, indent=2))
        print(json.dumps(metadata), flush=True)
        return
    warnings = [item.to_dict() for item in validate_context_ir(draft).issues
                if item.severity == "warning"]
    started = time.perf_counter()
    ir, prompt, metadata = _run_final_director(
        source, draft, (args.baseline / "h3_prompt.txt").read_text(), "",
        reasoning_provider_config(), args.output / "final_optimizer.log", warnings,
    )
    assert json.dumps(ir, sort_keys=True, ensure_ascii=False) == before
    (args.output / "h3_prompt.txt").write_text(prompt)
    artifacts = {
        "context_ir.json": ir,
        "llm_optimization.json": metadata,
        "h3_request.json": build_h3_request(ir, str(args.output / "h3_prompt.txt"),
                                            str(args.output / "h3_outputs")),
        "comparison_metadata.json": {
            "baseline": str(args.baseline), "scope": "final_realization_only",
            "semantic_ir_unchanged": True,
            "audio_replanned": False, "qwen_rerun": False,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "baseline_characters": len((args.baseline / "h3_prompt.txt").read_text()),
            "new_characters": len(prompt),
            "agent_sha256": hashlib.sha256((ROOT / "backend/agent.py").read_bytes()).hexdigest(),
        },
    }
    for name, data in artifacts.items():
        (args.output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps(artifacts["comparison_metadata.json"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
