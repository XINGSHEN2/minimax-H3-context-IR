#!/usr/bin/env python3
"""Run one Ref2VA case with independent Qwen perception and the v63 writer.

The raw user request is sent to Qwen as analysis guidance. No previous
DeepSeek intent resolution, directives, or evidence file is reused.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from backend.agent import run_agent
from backend.perception import PerceptionProviderConfig
from scripts.run_qwen_thinking_perception import RecordingThinkingProvider


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}


def media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return 'image'
    if suffix in VIDEO_EXTENSIONS:
        return 'video'
    raise ValueError(f'Unsupported reference asset: {path}')


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('case_dir', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--duration', required=True, type=float)
    parser.add_argument('--ratio', required=True)
    args = parser.parse_args()

    case_dir = args.case_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    user_request = (case_dir / 'prompt.txt').read_text(encoding='utf-8').strip()
    if not user_request:
        raise ValueError('Case prompt.txt is empty')

    counts = {'image': 0, 'video': 0}
    assets = []
    for path in sorted((case_dir / 'assets').iterdir()):
        if not path.is_file():
            continue
        kind = media_type(path)
        counts[kind] += 1
        assets.append({
            'asset_id': f'{kind}_{counts[kind]}',
            'media_type': kind,
            'uri': str(path),
            'label': path.stem,
            'user_role': 'reference',
        })
    if not assets:
        raise ValueError('No reference assets found')

    source = {
        'schema_version': 'context_request.v1',
        'user_request': user_request,
        'resolved_request': user_request,
        'task': {
            'type': 'ref2va',
            'duration_seconds': args.duration,
            'aspect_ratio': args.ratio,
            'generate_audio': True,
            'style': '',
        },
        'assets': assets,
        'directives': [],
        'asset_mentions': [],
        'open_questions': [],
        'completion_policy': {
            'technical': True,
            'conservative_semantic': True,
            'creative': False,
        },
    }
    save(output / 'source_input.json', source)

    plan = {
        'mode': 'qwen_independent_user_prompt',
        'user_request': user_request,
        'assets': [{
            'asset_id': asset['asset_id'],
            'role': 'reference',
            'user_claimed_category': '',
            'analyze': [
                '先看整张图：说明画面是单幅还是多格，并写清各格的位置、主体和构图。',
                '找出用户希望在视频中保留或使用的人物、物品、场景和文字；写清它们在图中实际可见的外形、颜色、材质、位置及相互关系。',
                '人物与固定服装通常放在同一实体；只有需要单独拿取、运动、变化或跨镜保持身份的物品才单列。不要把背景小物逐件列成实体。',
                '看不清的文字和细节请标为不确定；单张图不能证明动作顺序、镜头运动或声音。',
                '下面是用户原始需求，只用它选择观察重点，不能把其中的描述当成图片中已经可见的事实。',
                f'用户原始需求：{user_request}',
            ],
            'evidence_requirements': [],
            'do_not_infer': [
                '不要把用户需求当成素材中已发生的事实。',
                '不要推断音频、真实身份、品牌、所有权或未展示的动作。',
            ],
        } for asset in assets],
    }
    save(output / 'perception_plan.json', plan)

    qwen_base = os.environ['QWEN_IMAGE_UNDERSTAND_BASE_URL']
    config = PerceptionProviderConfig(
        provider='local-qwen3-vl-32b',
        model=os.environ.get('YIWU_VLM_MODEL', 'Qwen3.8-27B'),
        options={
            'image_base_url': qwen_base,
            'video_base_url': os.environ['QWEN_VIDEO_UNDERSTAND_BASE_URL'],
            'asset_upload_base_url': os.environ['QWEN_ASSET_UPLOAD_BASE_URL'],
            'output_dir': str(output / 'qwen_work'),
            'cache_enabled': False,
            'max_parallel_assets': 0,
            'single_pass_image_analysis': True,
            'single_pass_video_analysis': True,
            'max_tokens': 6000,
            'relational_image_max_tokens': 6000,
            'video_single_pass_max_tokens': 6000,
            'enable_thinking': True,
            'temperature': 0.0,
            'timeout_seconds': 7200,
            'video_fps': 2.0,
            'video_max_frames': 256,
        },
    )
    provider = RecordingThinkingProvider(config, output / 'raw_responses')
    started = time.perf_counter()
    perception = provider.analyze(assets, plan)
    elapsed = round(time.perf_counter() - started, 3)
    perception['experiment'] = {
        'mode': 'v63_qwen_independent_user_prompt',
        'elapsed_seconds': elapsed,
        'user_request': user_request,
    }
    perception_path = output / 'media_analysis.json'
    save(perception_path, perception)
    save(output / 'pipeline_manifest.json', {
        'base_version': 'v63',
        'intent_resolution': 'skipped; resolved_request is verbatim user_request',
        'perception': 'Qwen3.8-27B thinking with original user_request per asset',
        'qwen_requests': perception.get('perception_metrics', {}).get('request_count'),
        'perception_seconds': elapsed,
        'writer': 'v63 DeepSeek single-call compiler',
        'prior_intent_or_media_analysis_reused': False,
    })

    print(f'Qwen complete: {len(assets)} assets, {elapsed}s', flush=True)
    return run_agent(source, output / 'ir', None, perception_from=perception_path,
                     intent_resolved=True)


if __name__ == '__main__':
    raise SystemExit(main())
