"""Single-call orchestration and response contract for four H3 skills."""
from __future__ import annotations
import json
from typing import Any, Mapping

ORCHESTRATION = """在一次请求中完成下面四步，返回最终结果，不输出草稿或推理过程，不调用工具。

1. H3 Outline Planning：根据原始用户要求、素材分析和目标时长，确定主要内容、可见发展和结束位置，写 developments 与素材用途。解析后的要求仅供辅助，不能代替用户原文。
2. H3 Shot Planning：先安排观看过程和时间，再决定必要切点，直接在 detailed_description 中写完整镜头。动作、环境反应和文字效果能同时呈现时一起写，不逐项排成独立段落。
3. H3 Sound Planning：结合镜头中的同步声音，写整体声景和画外配乐，不另加动作或切点。
4. H3 Prompt Writing：按所选官方指南完成六板块格式，沿用已经确定的镜头与声音。

每个 Skill 只负责自己的规划内容，不另写多套镜头正文。最后对照用户要求和当前规则，修正遗漏、无依据的切镜及前后状态矛盾；content_plan 与 h3_prompt 保存同一个最终版本。

subject_definitions、summary、retention_analysis 保持简洁；detailed_description 写清能改变生成结果的动作、细节、光线、观看方式和局部声音。不设机械字数上限，删除重复表达，保留执行所需的信息。
"""

RESPONSE_CONTRACT = """本次模型调用只返回一个 JSON 对象，顶层严格为 content_plan、h3_prompt、uncertainties，不输出分析、草稿或其他顶层字段。
h3_prompt 必须是包含完整六节最终 H3 的字符串，不能是对象、数组或分节字段。
content_plan 包含：creative_brief（user_locked、reference_anchors、open_design）；requirement_map（content_events、editing_treatments、global_style、audio_requirements，每项含稳定 id 与要求文本）；task_mode；bindings（asset_id、role、retained_attributes、optional_inherited_attributes、excluded_attributes、exclusion_reasons）；developments（id、source_content_event_ids、visible_change、outcome）；shots（id、development_ids、content_purpose、treatment_ids、start_seconds、end_seconds；只有拆分同一连续动作时才增加 cut_reason 和 continuity_bridge）。逐镜正文只存在于 h3_prompt.detailed_description，各镜用独占行首的 [Shot N] 标签，编号从 1 连续递增，数量与 shots 一致；不要在 content_plan 另写 description、start_state、action、end_state、sound_cues 或 audio_plan。代码会从最终原文提取逐镜 description 供记录。不输出 action_units、shot_merge_audit 或 must_keep。
使用真实 asset_id 和 reference_registry 编号；时间连续覆盖 0 到目标时长。uncertainties 只记录影响使用的具体问题。"""

COMPACT_WRITING_INSTRUCTIONS = "\n\n".join((
    "你是视频内容规划与 MiniMax H3 提示词编写器。按 system prompt 中四个 H3 Skill 的职责依次完成任务。",
    ORCHESTRATION,
    "以下是本次任务和素材证据：\n",
))

def build_compact_writing_prompt(evidence: Mapping[str, Any]) -> str:
    return (COMPACT_WRITING_INSTRUCTIONS
            + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
            + "\n\n" + RESPONSE_CONTRACT)
