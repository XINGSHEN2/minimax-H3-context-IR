"""Single-call orchestration and response contract for four H3 skills."""
from __future__ import annotations
import json
from typing import Any, Mapping

ORCHESTRATION = """在一次 API 请求的一次响应中，严格依次完成四个阶段。这是内部工作顺序，不是四次请求；不要输出推理过程，也不要调用工具。

1. 使用 H3 Outline Planning Skill 确定“发生什么”：先整理用户要求和素材可见事实，按目标时长建立并锁定最小充分 developments，再据此确定素材用途与 bindings。不要设计镜头和声音。
2. 使用 H3 Shot Planning Skill 确定“怎样看见”：把每条 development 映射到 shots，决定观看任务、镜头边界、摄影机路径、连续性、转场和时间，并在最终 h3_prompt 的 detailed_description 中写出完整逐镜正文。不要改写大纲。
3. 使用 H3 Sound Planning Skill 确定“需要听见什么”：结合逐镜同步声音和用户要求，写出整体声景与画外配乐。不要为了声音增加动作、切点或视觉结果。
4. 使用 H3 Prompt Writing Skill 确定“怎样交付给 H3”：根据任务 profile 阅读对应官方 reference，完成六板块信息分配和可执行表达；镜头正文只写一次，不另输出副本。

Ref2VA 写作时，把信息按用途分配，而不是平均分配篇幅：
- subject_definitions 只保留跨镜识别或独立控制所需的身份锚点；一个主体通常用一句完整定义，不罗列本镜才需要的动作、光线和环境细节。
- summary 只说明任务类型、素材分工、事件主线和结局。
- retention_analysis 只说明出现范围、保留级别、必须保持的核心身份，以及允许发生的目标变化；不重复主体定义，也不预写镜头内容。
- 修改任务中，subject_definitions 写明原素材中的哪个内容被替换成什么；summary 简短覆盖各项修改；retention_analysis 写清原内容、目标内容、适用范围和保留项。相关 Shot 的画面修改仍要写清从什么改成什么，不能只引用目标标签。对白、旁白和歌词替换只在前面的修改说明中保留原句与新句；Shot 只写最终要发声的内容，不出现被替换的旧台词。招牌等可见文字仍保留原文与新文；精简和去重不能删掉这些对应关系。替换描述不要求播放变形过程，局部修改不因此新增动作、切镜或音效。
- detailed_description 承担主要执行信息。每个 Shot 应具体写清起始画面、主体动作的可见阶段、主体与环境的关系、必要的材质或光线响应、摄影机如何观察、切点如何到达下一状态，以及需要精确同步的声音。具体不等于重复：只写本镜独有、能够改变 H3 执行结果的信息。
- overall_soundscape 和 non_diegetic_music 按声音计划简洁交付，不用缩短 detailed_description 来给前述板块腾篇幅。


对白标签边界：<d> 只表示目标视频中实际发出的对白或歌词，仅写在 detailed_description 对应的发声位置。待替换、删除或仅用于解释的原句使用普通引号，不能放入 <d>。subject_definitions、summary、retention_analysis 中的新旧对白均用普通引号说明；对白、旁白或歌词被替换时，相关 Shot 只写最终实际发声内容并使用 <d>；不得在镜头正文中引用、复述或用否定句提及被替换的旧台词，即使用普通引号也不允许。新旧台词对应关系只留在前面的修改说明中。保留不变且实际发出的原对白仍可使用 <d>。招牌、字幕等可见文字继续用普通双引号写清原文和目标文字，不使用 <d>，也不因此省略替换关系。

最后核对用户要求覆盖、真实素材编号、时间连续性，以及 developments、shots 与 h3_prompt 的一致性。问题必须回到所属阶段修正；content_plan 只保存最终锁定版本。

h3_prompt 采用最短充分表达且不设机械字符上限：前三节保持紧凑，detailed_description 保留执行每个镜头所需的具体信息。删除重复句，不删除会改变动作阶段、空间关系、材质与光线响应、摄影机执行、连续状态、切点或精确音画同步的信息。静态内容若只存在于一个已定义 Picture/Video 锚点中，不再拆成 Subject；逐镜不重述 Subject 外观、Picture 完整画面、全局风格或固定层。
"""

RESPONSE_CONTRACT = """本次模型调用只返回一个 JSON 对象，顶层严格为 content_plan、h3_prompt、uncertainties，不输出分析、草稿或其他顶层字段。
h3_prompt 必须是包含完整六节最终 H3 的字符串，不能是对象、数组或分节字段。
content_plan 包含：creative_brief（user_locked、reference_anchors、open_design）；requirement_map（content_events、editing_treatments、global_style、audio_requirements，每项含稳定 id 与要求文本）；task_mode；bindings（asset_id、role、retained_attributes、optional_inherited_attributes、excluded_attributes、exclusion_reasons）；developments（id、source_content_event_ids、visible_change、outcome、estimated_duration_seconds）；shots（id、development_ids、content_purpose、treatment_ids、start_seconds、end_seconds）。逐镜正文只存在于 h3_prompt.detailed_description，各镜用独占行首的 [Shot N] 标签，编号从 1 连续递增，数量与 shots 一致；不要在 content_plan 另写 description、start_state、action、end_state、sound_cues 或 audio_plan。代码会从最终原文提取逐镜 description 供记录。不输出 action_units、shot_merge_audit 或 must_keep。
使用真实 asset_id 和 reference_registry 编号；时间连续覆盖 0 到目标时长。uncertainties 只记录影响使用的具体问题。"""

COMPACT_WRITING_INSTRUCTIONS = "\n\n".join((
    "你是视频内容规划与 MiniMax H3 提示词编写器。按 system prompt 中四个 H3 Skill 的职责依次完成任务。",
    ORCHESTRATION,
    "直接按 user_request 理解用户要求，保留明确给出的 directives。素材分析只说明原素材有什么。"
    "\nvisual 是画面观察，audio 是实际声音，cross_asset_relations 是跨图片关系。"
    "用户要求修改的内容不等于素材原本的内容。不要把 inferred 或 uncertain 写成确定事实。"
    "\n音轨的 source_asset_id 指向原视频；按 reference_registry 引用 <Audio N>。"
    "bindings 可引用实际输入的 asset_id，或 reference_registry 已登记的内嵌音轨 ID（如 video_1:audio）。内嵌音轨来自原视频，不是另一个上传文件。"
    "\n素材时间是源视频时间，shots 时间是目标视频时间。time_range=null 表示无法定位；"
    "model_estimate 只是模型估计，不能声称已精确对齐。保留或替换对白时使用原始转写，不补写听不清的部分。",
    "以下是本次任务和素材证据：\n",
))

def build_compact_writing_prompt(evidence: Mapping[str, Any]) -> str:
    return (COMPACT_WRITING_INSTRUCTIONS
            + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
            + "\n\n" + RESPONSE_CONTRACT)
