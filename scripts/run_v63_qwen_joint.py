#!/usr/bin/env python3
"""One Qwen request: resolve user intent, then inspect all reference images."""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
from pathlib import Path

from backend.agent import run_agent
from backend.intent_resolver import build_intent_prompt, validate_intent_resolution
from backend.perception import PerceptionProviderConfig, RELATIONAL_IMAGE_PROMPT, _json_object
from scripts.convert_grouped_perception import convert_grouped_result
from scripts.run_qwen_thinking_perception import RecordingThinkingProvider


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def joint_prompt(source: dict) -> str:
    asset_ids = [item['asset_id'] for item in source['assets']]
    first = build_intent_prompt(source).replace(
        '你负责在看素材之前理解用户需求，并给视觉模型写逐素材检查计划。你只能读取用户文字和素材清单；不能声称已经看见、听见或识别素材内容。',
        '同一次请求分两步完成。第一步只根据用户文字和素材清单整理需求、确定素材用途与检查计划；此时不要利用图片推断用户意图。第二步再查看附在本请求中的图片，按第一步的检查计划记录实际可见的事实。',
        1,
    )
    visual_rules = RELATIONAL_IMAGE_PROMPT.split('\n', 2)[2]
    return (first + '\n\n第二步：按图片顺序检查以下素材编号：'
            + json.dumps(asset_ids, ensure_ascii=False)
            + '。先逐图记录画面结构、人物与物品、可见文字、位置关系和不确定处，再判断跨图是否是同一主体。'
            + '用户描述只决定观察重点，不能作为已看见的事实。图片顺序不等于时间顺序。\n'
            + visual_rules
            + '\n\n仍然只返回一个 JSON 对象。先输出第一步要求的 resolved_request、asset_mentions、directives、completion_policy、perception_plan、open_questions；'
            + '另加 grouped_image_analysis 字段保存第二步结果。该字段使用图片分析模板的 summary、global_analysis、entities、relations、uncertainties；'
            + '另加 image_observations 数组，每张图片一项：'
            + '{"source_asset_id":"image_1","summary":"这张图实际可见的内容","entity_ids":[],"uncertainties":[]}。'
            + '每个实体必须包含 category、summary 和 features；每条 feature 严格为 [group,name,value,0到1的数字,visible|inferred|unresolved]。'
            + 'relations 严格使用图片模板示例中的七项数组，最后可加 source_asset_ids。'
            + 'visible_text 放入 global_analysis.visible_text。每个实体、关系、framing_layer 和 visible_text 都加 source_asset_ids 数组。'
            + '相同主体跨图可共用 entity_id，但只在有足够可见证据时合并；无法确认时保持分离。'
            + '第一步写的是检查计划，第二步写的是图片事实；两者不可互相冒充。')


def normalize_grouped(grouped: dict) -> tuple[dict, list[str]]:
    """Preserve Qwen facts when their JSON shape drifts from the image schema."""
    fixed = copy.deepcopy(grouped)
    repairs: list[str] = []
    global_analysis = fixed.setdefault('global_analysis', {})
    if not isinstance(global_analysis, dict):
        raise ValueError('global_analysis must be an object')
    if 'visible_text' not in global_analysis and isinstance(fixed.get('visible_text'), list):
        global_analysis['visible_text'] = fixed['visible_text']
        repairs.append('moved top-level visible_text into global_analysis')
    global_analysis.setdefault('scene', str(fixed.get('summary', '')))
    layers = global_analysis.get('framing_layers') or []
    global_analysis.setdefault('composition', str(layers[0].get('description', ''))
                               if layers and isinstance(layers[0], dict) else '')
    confidence_words = {'high': 0.9, 'medium': 0.7, 'low': 0.5}
    for entity in fixed.get('entities', []):
        if not isinstance(entity, dict):
            continue
        if not entity.get('category') and entity.get('label'):
            entity['category'] = entity['label']
            entity['summary'] = f"{entity['label']}：{entity.get('summary', '')}"
            repairs.append(f"preserved label as category for {entity.get('entity_id')}")
        for feature in entity.get('features', []):
            if not isinstance(feature, list) or len(feature) < 5:
                raise ValueError(f"Malformed feature in {entity.get('entity_id')}")
            value = feature[3]
            if isinstance(value, str) and value.lower() in confidence_words:
                feature[3] = confidence_words[value.lower()]
                repairs.append(f"normalized feature confidence in {entity.get('entity_id')}")
            if not isinstance(feature[3], (int, float)):
                raise ValueError(f"Non-numeric feature confidence in {entity.get('entity_id')}")
    relations = []
    for index, relation in enumerate(fixed.get('relations', []), 1):
        if isinstance(relation, list):
            relations.append(relation)
            continue
        if not isinstance(relation, dict):
            raise ValueError('Unsupported relation shape')
        subject = str(relation.get('from', ''))
        obj = str(relation.get('to', ''))
        kind = str(relation.get('relation', ''))
        if not subject or not obj or not kind:
            raise ValueError('Relation omitted subject, object, or type')
        relations.append([
            f'relation_{index}', kind, subject, obj,
            str(relation.get('anchor') or f'{subject} {kind} {obj}'),
            0.7, 'visible', relation.get('source_asset_ids', []),
        ])
        repairs.append(f'normalized relation_{index}')
    fixed['relations'] = relations
    return fixed, repairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('case_dir', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--duration', type=float, required=True)
    parser.add_argument('--ratio', required=True)
    parser.add_argument('--perception-only', action='store_true')
    parser.add_argument('--from-result', type=Path,
                        help='Reprocess a saved Qwen response without another model request')
    args = parser.parse_args()
    case = args.case_dir.resolve()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    user_request = (case / 'prompt.txt').read_text(encoding='utf-8').strip()
    paths = sorted(path for path in (case / 'assets').iterdir() if path.is_file())
    if not paths or any(path.suffix.lower() not in IMAGE_SUFFIXES for path in paths):
        raise ValueError('This one-request prototype currently requires image-only assets')
    assets = [
        {'asset_id': f'image_{i}', 'media_type': 'image', 'uri': str(path),
         'label': path.stem, 'user_role': 'reference'}
        for i, path in enumerate(paths, 1)
    ]
    source = {
        'schema_version': 'context_request.v1', 'user_request': user_request,
        'resolved_request': '', 'task': {
            'type': 'ref2va', 'duration_seconds': args.duration,
            'aspect_ratio': args.ratio, 'generate_audio': True, 'style': ''},
        'assets': assets, 'directives': [], 'asset_mentions': [], 'open_questions': [],
        'completion_policy': {'technical': True, 'conservative_semantic': True, 'creative': False},
    }
    save(out / 'source_input.json', source)
    prompt = joint_prompt(source)
    (out / 'qwen_prompt.txt').write_text(prompt, encoding='utf-8')
    config = PerceptionProviderConfig(
        provider='local-qwen3-vl-32b', model=os.environ.get('YIWU_VLM_MODEL', 'Qwen3.8-27B'),
        options={
            'image_base_url': os.environ['QWEN_IMAGE_UNDERSTAND_BASE_URL'],
            'video_base_url': os.environ['QWEN_VIDEO_UNDERSTAND_BASE_URL'],
            'asset_upload_base_url': os.environ['QWEN_ASSET_UPLOAD_BASE_URL'],
            'output_dir': str(out / 'qwen_work'), 'cache_enabled': False,
            'enable_thinking': True, 'temperature': 0.0, 'timeout_seconds': 7200,
        },
    )
    provider = RecordingThinkingProvider(config, out / 'raw_responses')
    content = [{'type': 'text', 'text': prompt}]
    content.extend({'type': 'image_url', 'image_url': {'url': provider._media_url(path)}}
                   for path in paths)
    payload = {
        'model': config.model, 'messages': [{'role': 'user', 'content': content}],
        'max_tokens': 12000, 'stream': False, 'temperature': 0.0, 'top_p': 0.9,
    }
    started = time.perf_counter()
    if args.from_result:
        result = json.loads(args.from_result.resolve().read_text(encoding='utf-8'))
    else:
        response = provider._request_json('POST', '/v1/chat/completions', payload, 7200,
                                          config.options['image_base_url'])
        message = response['choices'][0]['message']
        raw = str(message.get('content') or '')
        final = raw.split('</think>', 1)[1].strip() if '</think>' in raw else raw
        result = _json_object(final)
    save(out / 'joint_result.json', result)
    resolution = validate_intent_resolution(result, source)
    save(out / 'intent_resolution.json', {
        key: result.get(key) for key in (
            'resolved_request', 'asset_mentions', 'directives',
            'completion_policy', 'perception_plan', 'open_questions')
    })
    grouped = result.get('grouped_image_analysis')
    if not isinstance(grouped, dict):
        raise ValueError('Qwen response omitted grouped_image_analysis')
    grouped, repairs = normalize_grouped(grouped)
    save(out / 'structural_repairs.json', repairs)
    envelope = {
        'user_request': user_request,
        'image_source_map': {asset['asset_id']: asset['uri'] for asset in assets},
        'grouped_image_analysis': grouped,
    }
    perception = convert_grouped_result(envelope)
    save(out / 'media_analysis.json', perception)
    save(out / 'manifest.json', {
        'qwen_requests': 0 if args.from_result else 1, 'images': len(paths),
        'elapsed_seconds': round(time.perf_counter() - started, 3),
        'internal_steps': ['intent_resolution', 'visual_analysis'],
    })
    print(f'Qwen one-call complete: {len(paths)} images', flush=True)
    if args.perception_only:
        return 0
    return run_agent(resolution['source'], out / 'ir', None,
                     perception_from=out / 'media_analysis.json', intent_resolved=True)


if __name__ == '__main__':
    raise SystemExit(main())
