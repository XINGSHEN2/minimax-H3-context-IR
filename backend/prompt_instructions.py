"""Single-call orchestration and response contract for four H3 skills."""
from __future__ import annotations
import json
from typing import Any, Mapping

ORCHESTRATION = """在一次 API 请求的一次响应中，严格依次完成以下阶段；这是内部组织顺序，不是多次请求，不输出推理过程，也不调用工具。

1. 按 H3 Outline Planning Skill 解释原始用户要求、素材证据和创作权限，建立 requirement_map、creative_brief、bindings 与最小充分 developments。锁定后，大纲以外的阶段不得改写事件语义。
2. 按 H3 Shot Planning Skill 将锁定 developments 映射为最终 shots，决定必要视点、摄影和切点。分镜不得新增、删除、合并、拆分或替换 developments；发现问题时返回大纲阶段修正后重新锁定。
3. 按 H3 Sound Planning Skill 为锁定视觉计划形成 audio_plan 与必要的 shots.sound_cues，并落实到最终 H3 的对应声音位置；如与用户明确音频时序冲突，返回规划阶段解决后重新锁定。
4. 按 H3 Prompt Writing Skill 将锁定计划编译为完整六节 h3_prompt。写作阶段只做信息分配、语义压缩和可执行表达，不重新设计大纲、分镜或声音。素材证据不逐项转录；每项事实只写在一个板块，重复的外观、关键帧内容、全局风格、固定视觉层和转场语法通过标签或一次全局定义引用。
5. 最终核对用户要求覆盖、真实素材编号、时间连续性和计划到 H3 的一致性。语义压缩不得删除任何用户明确动作、顺序、保留项、禁止项、全局持续行为或音频要求；重复要求合并为一次全局表达。问题必须回到所属 Skill 修正；content_plan 只保存最终锁定版本。
"""

RESPONSE_CONTRACT = """最终只输出一个 JSON 对象，顶层严格为 content_plan、h3_prompt、uncertainties，不输出分析、草稿或其他顶层字段。
h3_prompt 必须是包含完整六节最终 H3 的字符串，不能是对象、数组或分节字段。它采用最短充分表达且不设机械字符上限：完整覆盖要求和锁定计划后，删除不提供新增执行信息的句子。静态内容若只存在于一个已定义 Picture/Video 锚点中，不再拆成 Subject；逐镜不重述 Subject 外观、Picture 完整画面、全局风格、固定层或已定义的重复转场语法。
content_plan 包含：creative_brief（user_locked、reference_anchors、open_design）；requirement_map（content_events、editing_treatments、global_style、audio_requirements，每项含稳定 id 与要求文本）；task_mode；must_keep；bindings（asset_id、role、retained_attributes、optional_inherited_attributes、excluded_attributes、exclusion_reasons）；developments（id、source_content_event_ids、visible_change、outcome）；shots（id、development_ids、content_purpose、treatment_ids、start_seconds、end_seconds、start_state、action、end_state、sound_cues；只有拆分同一连续动作时才增加 cut_reason 和 continuity_bridge）；audio_plan，其中 constraints 为字符串数组，auditory_focus、continuous_bed、mix_priority、ending_state 为字符串，key_sound_events 为对象数组且每项严格含已有 shot_id、trigger、sound、sync，music_decision 严格为包含 decision（use 或 N/A）、function、tempo_energy_basis、timbres（字符串数组）、dynamic_arc 的对象。不输出 action_units 或 shot_merge_audit。
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
