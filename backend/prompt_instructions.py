"""Single-call orchestration and response contract for four H3 skills."""
from __future__ import annotations
import json
from typing import Any, Mapping

ORCHESTRATION = """在一次 API 请求的一次响应中，严格依次完成四个阶段。这是内部工作顺序，不是四次请求；不要输出推理过程，也不要调用工具。

1. 使用 H3 Outline Planning Skill 确定“发生什么”：整理要求与素材用途，明确创作范围，建立并锁定最小充分 developments。不要设计镜头和声音。
2. 使用 H3 Shot Planning Skill 确定“怎样看见”：把每条 development 映射到 shots，决定观看任务、镜头边界、摄影机路径、连续性、转场和时间。不要改写大纲。
3. 使用 H3 Sound Planning Skill 确定“需要听见什么”：在锁定画面上规划 audio_plan 和必要的 shots.sound_cues。不要为了声音增加动作、切点或视觉结果。
4. 使用 H3 Prompt Writing Skill 确定“怎样交付给 H3”：根据任务 profile 阅读对应官方 reference，把锁定计划编译为完整 h3_prompt。只做信息分配、压缩和可执行表达，不重新规划。

Ref2VA 写作时，把信息按用途分配，而不是平均分配篇幅：
- subject_definitions 只保留跨镜识别或独立控制所需的身份锚点；一个主体通常用一句完整定义，不罗列本镜才需要的动作、光线和环境细节。
- summary 只说明任务类型、素材分工、事件主线和结局。
- retention_analysis 只说明出现范围、保留级别、必须保持的核心身份，以及允许发生的目标变化；不重复主体定义，也不预写镜头内容。
- detailed_description 承担主要执行信息。每个 Shot 应具体写清起始画面、主体动作的可见阶段、主体与环境的关系、必要的材质或光线响应、摄影机如何观察、切点如何到达下一状态，以及需要精确同步的声音。具体不等于重复：只写本镜独有、能够改变 H3 执行结果的信息。
- overall_soundscape 和 non_diegetic_music 按声音计划简洁交付，不用缩短 detailed_description 来给前述板块腾篇幅。

最后核对用户要求覆盖、真实素材编号、时间连续性，以及 developments、shots、audio_plan 与 h3_prompt 的一致性。问题必须回到所属阶段修正；content_plan 只保存最终锁定版本。
"""

RESPONSE_CONTRACT = """最终只输出一个 JSON 对象，顶层严格为 content_plan、h3_prompt、uncertainties，不输出分析、草稿或其他顶层字段。
h3_prompt 必须是包含完整六节最终 H3 的字符串，不能是对象、数组或分节字段。它采用最短充分表达且不设机械字符上限：subject_definitions、summary 和 retention_analysis 保持紧凑，detailed_description 保留执行每个镜头所需的具体信息。删除重复句，不删除会改变动作阶段、空间关系、材质与光线响应、摄影机执行、连续状态、切点或精确音画同步的信息。静态内容若只存在于一个已定义 Picture/Video 锚点中，不再拆成 Subject；逐镜不重述 Subject 外观、Picture 完整画面、全局风格、固定层或已定义的重复转场语法。
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
