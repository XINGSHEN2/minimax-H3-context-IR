"""Stable atomic and composed capabilities exposed by Context-IR.

Internal compiler phases remain separately testable, while callers receive a
small set of durable service interfaces rather than model-specific internals.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.context_ir import (
    audit_h3_prompt,
    build_h3_request,
    render_h3_prompt,
    validate_context_ir,
)
from backend.perception import PERCEPTION_PROVIDERS, PerceptionProviderConfig, normalize_media_analysis
from backend.video_generation import H3VideoClient, default_h3_client


CAPABILITY_SCHEMA_VERSION = "context_ir_capabilities.v1"
H3_PROMPT_OUTPUT_VERSION = "h3_prompt_generate.v1"


def _provider(config: PerceptionProviderConfig):
    return PERCEPTION_PROVIDERS.create(config)


def _single_asset_understand(
    asset: Mapping[str, Any],
    config: PerceptionProviderConfig,
    analysis_directive: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    asset_copy = copy.deepcopy(dict(asset))
    plan = None
    if analysis_directive is not None:
        directive = copy.deepcopy(dict(analysis_directive))
        directive["asset_id"] = str(asset_copy.get("asset_id", ""))
        plan = {"assets": [directive]}
    return _provider(config).analyze([asset_copy], plan)


def image_understand(asset: Mapping[str, Any], config: PerceptionProviderConfig, analysis_directive: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if asset.get("media_type") != "image":
        raise ValueError("image_understand requires media_type=image")
    return _single_asset_understand(asset, config, analysis_directive)


def video_understand(asset: Mapping[str, Any], config: PerceptionProviderConfig, analysis_directive: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if asset.get("media_type") != "video":
        raise ValueError("video_understand requires media_type=video")
    return _single_asset_understand(asset, config, analysis_directive)


def audio_understand(asset: Mapping[str, Any], config: PerceptionProviderConfig, analysis_directive: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if asset.get("media_type") != "audio":
        raise ValueError("audio_understand requires media_type=audio")
    # Provider adapters must report unsupported evidence explicitly; they may not
    # silently let a visual model claim to hear audio.
    return _single_asset_understand(asset, config, analysis_directive)


def media_evidence_normalize(raw: Mapping[str, Any], assets: list[Mapping[str, Any]], config: PerceptionProviderConfig) -> dict[str, Any]:
    return normalize_media_analysis(raw, assets, config)


def _prepare_asset_descriptions(
    source: Mapping[str, Any],
    descriptions: Any,
    config: PerceptionProviderConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert caller-supplied natural-language evidence to media_analysis.v2.

    This is normalization, not perception: descriptions remain explicitly
    caller-supplied and are never promoted to independently verified facts.
    """
    if not isinstance(descriptions, list) or not descriptions:
        raise ValueError("input_type=asset_descriptions requires a non-empty asset_descriptions array")

    prepared_source = copy.deepcopy(dict(source))
    source_assets = prepared_source.get("assets")
    if source_assets is not None and not isinstance(source_assets, list):
        raise ValueError("source.assets must be an array when provided")

    description_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(descriptions):
        if not isinstance(item, Mapping):
            raise ValueError(f"asset_descriptions[{index}] must be an object")
        entry = copy.deepcopy(dict(item))
        asset_id = str(entry.get("asset_id", "")).strip()
        description = str(entry.get("description", entry.get("summary", ""))).strip()
        if not asset_id:
            raise ValueError(f"asset_descriptions[{index}].asset_id is required")
        if asset_id in description_by_id:
            raise ValueError(f"duplicate asset_description asset_id: {asset_id}")
        if not description:
            raise ValueError(f"asset_descriptions[{index}].description is required")
        entry["asset_id"] = asset_id
        entry["description"] = description
        description_by_id[asset_id] = entry

    if source_assets is None:
        source_assets = []
        for index, entry in enumerate(description_by_id.values()):
            media_type = str(entry.get("media_type", entry.get("type", ""))).strip()
            uri = str(entry.get("uri", "")).strip()
            if media_type not in {"image", "video", "audio"}:
                raise ValueError(
                    f"asset_descriptions[{index}].media_type must be image, video, or audio"
                )
            if not uri:
                raise ValueError(
                    f"asset_descriptions[{index}].uri is required when source.assets is omitted"
                )
            asset = {
                key: copy.deepcopy(value)
                for key, value in entry.items()
                if key not in {"description", "summary", "evidence", "regions", "entities", "relations", "events", "technical", "transcript", "uncertainties", "evidence_coverage"}
            }
            asset["asset_id"] = entry["asset_id"]
            asset["media_type"] = media_type
            asset["uri"] = uri
            source_assets.append(asset)
        prepared_source["assets"] = source_assets

    source_ids = {
        str(item.get("asset_id", ""))
        for item in source_assets
        if isinstance(item, Mapping)
    }
    description_ids = set(description_by_id)
    if source_ids != description_ids:
        raise ValueError(
            "asset_descriptions asset IDs do not match source.assets: "
            f"expected={sorted(source_ids)}, actual={sorted(description_ids)}"
        )

    raw_assets = []
    passthrough_fields = (
        "evidence", "regions", "entities", "relations", "events", "technical",
        "transcript", "uncertainties", "evidence_coverage", "supplemental_attempts",
    )
    for asset_id, entry in description_by_id.items():
        normalized_entry = {
            "asset_id": asset_id,
            "summary": entry["description"],
        }
        for field in passthrough_fields:
            if field in entry:
                normalized_entry[field] = copy.deepcopy(entry[field])
        if "evidence" not in normalized_entry:
            normalized_entry["evidence"] = [{
                "source": "caller_supplied_description",
                "text": entry["description"],
            }]
        if "uncertainties" not in normalized_entry:
            normalized_entry["uncertainties"] = [
                "Caller-supplied description; not independently verified by a perception model."
            ]
        raw_assets.append(normalized_entry)

    analysis = media_evidence_normalize({"assets": raw_assets}, source_assets, config)
    analysis["source"] = "caller_supplied_asset_descriptions"
    prepared_source["perception"] = copy.deepcopy(analysis)
    return prepared_source, analysis


def _read_result(directory: Path, name: str) -> Any:
    path = directory / name
    if name.endswith(".json"):
        return json.loads(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")


def _artifact_meta(value: Any, source: str) -> dict[str, str]:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"source": source, "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def h3_prompt_generate(
    payload: Mapping[str, Any],
    *,
    output_dir: Path | None = None,
    style_skill: str | None = None,
) -> dict[str, Any]:
    """Compile from exactly one declared starting point.

    input_type=assets: full intent planning, perception, and compilation.
    input_type=asset_descriptions: normalize caller descriptions, then compile.
    input_type=media_analysis: reuse validated upstream perception.
    input_type=context_ir: deterministic render, audit, and request only.
    """
    input_type = str(payload.get("input_type", "")).strip()
    if input_type not in {"assets", "asset_descriptions", "media_analysis", "context_ir"}:
        raise ValueError(
            "input_type must be assets, asset_descriptions, media_analysis, or context_ir"
        )
    if input_type == "context_ir":
        ir = payload.get("context_ir")
        if not isinstance(ir, Mapping):
            raise ValueError("input_type=context_ir requires context_ir object")
        report = validate_context_ir(ir)
        if not report.passed:
            raise ValueError(json.dumps(report.to_dict(), ensure_ascii=False))
        prompt = render_h3_prompt(ir)
        audit = audit_h3_prompt(ir, prompt)
        if not audit.passed:
            raise ValueError(json.dumps(audit.to_dict(), ensure_ascii=False))
        prompt_file = str(payload.get("prompt_file", "h3_prompt.txt"))
        output_path = str(payload.get("output_path", "h3_outputs"))
        result = {
            "schema_version": H3_PROMPT_OUTPUT_VERSION,
            "input_type": input_type,
            "sources": {"context_ir": "caller_supplied"},
            "media_analysis": ir.get("perception"),
            "context_ir": copy.deepcopy(dict(ir)),
            "h3_prompt": prompt,
            "h3_prompt_audit": audit.to_dict(),
            "h3_request": build_h3_request(ir, prompt_file, output_path),
        }
        result["artifacts"] = {
            "context_ir": _artifact_meta(result["context_ir"], "caller_supplied"),
            "h3_prompt": _artifact_meta(result["h3_prompt"], "generated"),
            "h3_request": _artifact_meta(result["h3_request"], "generated"),
        }
        return result

    source = payload.get("source")
    if not isinstance(source, Mapping):
        raise ValueError(f"input_type={input_type} requires source object")
    source = copy.deepcopy(dict(source))
    normalized_descriptions = None
    if input_type == "assets":
        if not isinstance(source.get("assets"), list) or "media_analysis" in payload:
            raise ValueError("input_type=assets requires source.assets and forbids media_analysis")
        perception_path = None
    elif input_type == "asset_descriptions":
        if "media_analysis" in payload:
            raise ValueError("input_type=asset_descriptions forbids media_analysis")
        from backend.agent import perception_config

        source, normalized_descriptions = _prepare_asset_descriptions(
            source,
            payload.get("asset_descriptions"),
            perception_config(source),
        )
        perception_path = None
    else:
        analysis = payload.get("media_analysis")
        if not isinstance(analysis, Mapping):
            raise ValueError("input_type=media_analysis requires media_analysis object")
        if str(analysis.get("schema_version", "")) != "media_analysis.v2":
            raise ValueError("media_analysis must use schema_version media_analysis.v2")
        expected_ids = {
            str(item.get("asset_id", ""))
            for item in source.get("assets", [])
            if isinstance(item, Mapping)
        }
        actual_ids = {
            str(item.get("asset_id", ""))
            for item in analysis.get("assets", [])
            if isinstance(item, Mapping)
        }
        if actual_ids != expected_ids:
            raise ValueError(
                f"media_analysis asset IDs do not match source.assets: "
                f"expected={sorted(expected_ids)}, actual={sorted(actual_ids)}"
            )
        source["perception"] = copy.deepcopy(dict(analysis))
        perception_path = None

    from backend.agent import run_agent

    managed_temp = output_dir is None
    target = output_dir or (Path(tempfile.mkdtemp(prefix="context-ir-compile-")) / "result")
    run_agent(
        source,
        target,
        style_skill,
        perception_from=perception_path,
        intent_resolved=(
            input_type in {"asset_descriptions", "media_analysis"}
            and bool(payload.get("intent_resolved", False))
        ),
    )
    result = {
        "schema_version": H3_PROMPT_OUTPUT_VERSION,
        "input_type": input_type,
        "sources": {
            "media_analysis": (
                "generated" if input_type == "assets"
                else "normalized_from_caller_descriptions" if input_type == "asset_descriptions"
                else "caller_supplied"
            ),
            "context_ir": "generated",
        },
        "media_analysis": _read_result(target, "media_analysis.json"),
        "context_ir": _read_result(target, "context_ir.json"),
        "h3_prompt": _read_result(target, "h3_prompt.txt"),
        "h3_prompt_audit": _read_result(target, "h3_prompt_audit.json"),
        "h3_request": _read_result(target, "h3_request.json"),
        "stage_timings": _read_result(target, "stage_timings.json"),
    }
    result["artifacts"] = {
        "media_analysis": _artifact_meta(result["media_analysis"], result["sources"]["media_analysis"]),
        "context_ir": _artifact_meta(result["context_ir"], "generated"),
        "h3_prompt": _artifact_meta(result["h3_prompt"], "generated"),
        "h3_request": _artifact_meta(result["h3_request"], "generated"),
    }
    if not managed_temp:
        result["output_dir"] = str(target)
    return result


def video_generate(
    compiled: Mapping[str, Any],
    *,
    client: H3VideoClient | None = None,
    wait: bool = False,
) -> dict[str, Any]:
    request = compiled.get("h3_request", compiled)
    if not isinstance(request, Mapping) or "task" not in request:
        raise ValueError("video_generate requires an H3 request or h3_prompt_generate output")
    service = client or default_h3_client()
    submitted = service.submit(request)
    if not wait:
        return {"schema_version": "video_generate.v1", "submission": submitted}
    task_id = str(submitted.get("task_id", submitted.get("id", "")))
    if not task_id:
        raise RuntimeError("H3 submission did not return a task ID")
    return {
        "schema_version": "video_generate.v1",
        "submission": submitted,
        "result": service.wait(task_id),
    }


def context_ir_generate(
    payload: Mapping[str, Any],
    *,
    output_dir: Path | None = None,
    generate_video: bool = False,
    wait_for_video: bool = False,
    client: H3VideoClient | None = None,
) -> dict[str, Any]:
    compiled = h3_prompt_generate(payload, output_dir=output_dir, style_skill=payload.get("style_skill"))
    result = {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "workflow": "context_ir_generate",
        "compile": compiled,
        "video_generation": None,
    }
    if generate_video:
        result["video_generation"] = video_generate(compiled, client=client, wait=wait_for_video)
    return result
