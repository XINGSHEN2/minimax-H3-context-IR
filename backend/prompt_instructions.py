"""Single-call orchestration and response contract for four H3 skills."""
from __future__ import annotations
import json
from typing import Any, Mapping

ORCHESTRATION = """一次请求完成下面四步，按顺序思考，只输出最终 JSON，不输出思考过程。
1. 大纲：先列出用户明确要求和素材可见事实。在目标时长内确定事件怎样开始、发生、结束；再决定每份素材用来保留什么。此时不写分镜或声音。
2. 分镜：按大纲决定每镜看到什么、镜头从哪里开始和结束、摄影机怎样移动、为什么切镜，以及前后镜如何接上。每镜的完整正文直接写进最终 h3_prompt 的 detailed_description，不在 content_plan 重写一遍。
3. 声音：根据用户要求和已经确定的画面，写需要同步的动作声、贯穿的环境声和画外配乐。声音不能凭空增加画面事件。
4. H3 写作：按 H3 Prompt Writing Skill 的六板块格式交付，保留用户指定的内容和素材锚点。

信息放在该发挥作用的位置：subject_definitions 简述跨镜需要保持的主体；summary 概括目标视频和事件结果；retention_analysis 说明素材哪些部分保留、哪些可变化；detailed_description 具体写每镜画面、动作、材质与光线、摄影机、转场和必要的同步声音；最后两栏写全片声景和配乐。前三栏不要重复逐镜细节，镜头正文也不要反复抄主体定义。

交稿前检查：用户要求是否落实，素材编号是否正确，时间是否覆盖全片，前后镜动作与物体状态是否接得上，以及大纲、分镜和最终 H3 文本是否一致。"""

RESPONSE_CONTRACT = """最终只输出一个 JSON 对象，顶层严格为 content_plan、h3_prompt、uncertainties，不输出分析、草稿或其他顶层字段。
h3_prompt 必须是包含完整六节最终 H3 的字符串，不能是对象、数组或分节字段。它采用最短充分表达且不设机械字符上限：subject_definitions、summary 和 retention_analysis 保持紧凑，detailed_description 保留执行每个镜头所需的具体信息。删除重复句，不删除会改变动作阶段、空间关系、材质与光线响应、摄影机执行、连续状态、切点或精确音画同步的信息。静态内容若只存在于一个已定义 Picture/Video 锚点中，不再拆成 Subject；逐镜不重述 Subject 外观、Picture 完整画面、全局风格或固定层。
content_plan 包含：creative_brief（user_locked、reference_anchors、open_design）；requirement_map（content_events、editing_treatments、global_style、audio_requirements，每项含稳定 id 与要求文本）；task_mode；must_keep；bindings（asset_id、role、retained_attributes、optional_inherited_attributes、excluded_attributes、exclusion_reasons）；developments（id、source_content_event_ids、visible_change、outcome）；shots（id、development_ids、content_purpose、treatment_ids、start_seconds、end_seconds；只有拆分同一连续动作时才增加 cut_reason 和 continuity_bridge）。逐镜正文只存在于 h3_prompt.detailed_description，各镜用独占行首的 [Shot N] 标签，编号从 1 连续递增，数量与 shots 一致；不要在 content_plan 另写 description、start_state、action、end_state、sound_cues 或 audio_plan。代码会从最终原文提取逐镜 description 供记录。不输出 action_units 或 shot_merge_audit。
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
