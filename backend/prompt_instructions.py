"""Single source for content-outline planning and H3 writing instructions."""
from __future__ import annotations

import json
from typing import Any, Mapping

SHOT_SCOPE_RULES = """镜头范围：用户指定的镜头只约束对应片段，未描述后续不等于禁止后续。仅一个镜头、一镜到底、不加镜头、完整锁定分镜或严格迁移按明确范围执行。未标为片尾的 Hard cut 是转场，须有切入内容；片尾硬切按结尾处理。任何新增限制必须有原始请求依据，不能以派生指令自身作证。冲突记入 uncertainties。"""

COMPLETION_RULES = """补全原则：完成用户意图所需的最小充分补全。优先补齐已有动作的衔接、表演、摄影和节奏，不默认增加人物、道具互动、触发机制、剧情转折或特效高潮。允许补充不等于必须扩写；删除仍不影响目标且没有明确表现价值的新增内容。不用长时间静止代替必要发展，也不限定镜头数。明确要求大胆创作时按其要求发挥。此原则不是用户的硬性禁止项。"""

INPUT_RULES = """输入与证据
以原始 user_request 为依据，上游 resolved_request、directives、completion_policy 只是解释。派生的 creative:false 不自动禁止未指定的创作；保留真正的用户限制、局部编辑和参考迁移范围，不授权删除编辑底片中的旁人或背景。不能以相似动作替代用户指定动作。
即使标为 visible，带有“可能”等限定也不是确定事实；同一分析中的重复不是独立佐证。保留有证据支持的共同外观；其拼写与 OCR 冲突时，区分明确目标文字与仅描述素材时的说法：前者遵从用户，后者引用原图字形并记录冲突，不猜字或声称已重新核验。
先看整体结构、各区域、可见状态及关系。依据充分才整合同一对象的互补视图，不合并不同人物或产品；人物关注服装领口/版型/长度、头发和鞋履，产品关注形状、材质、部件及标记。静态姿态不证明动作、时序或隐藏机制，布局不自动等于分镜。
素材用途按用户范围决定；未指定用途可选择有据且适合目标的内容，区分必须保留、可选继承和有理由排除，不把主要用途变成排他白名单。仅风格/身份等明确限制按其范围处理。关键参考证据缺失时记录具体不确定项。"""

WORKFLOW = """按顺序完成以下四步，在一次调用中返回最终结果，不输出推理过程，不读取文件或调用工具。

第一步：确定用户已锁定的范围
识别 generate、reference_transfer、edit 或 continuation。没有分镜时规划内容；指定部分镜头时锁定这些片段、补齐开放部分；完整分镜或严格复刻时忠实执行。把用户要求、素材绑定和开放选择分别记入 creative_brief 与 bindings。

第二步：先写内容大纲 developments
每条只写“发生什么变化，以及产生什么结果”，不要提前写镜头号、景别或切点。大纲可以是动作、情绪、产品展示或图形动画的发展，不强加故事。先完成大纲，再决定覆盖方式；不把现成镜头改名为 developments。一条事件可以由多个必要镜头呈现，一个镜头也能完成多个连续动作。
两行标题若共同构成一套包装，默认作为一个整体事件，保持主副标题关系，连续完成一次动画。文字语义不同本身不是拆成两轮入场的理由；只有用户要求或确有独立揭示必要时才拆开，不能以“没有重复全部效果”掩盖重复启动。

第三步：根据大纲安排 shots
每镜用 development_ids 指向大纲，只记录时间、起始状态、动作、结束状态和同步声音。不按主体或事件数量机械分镜。切镜要有新的信息、动作结果、关系或必要细节；仅换景别、增强震动不构成新事件，重复功能应合并。保留用户指定快切、重复节奏和分镜；不套用固定走路动作、镜头数或时长比例。
跨切镜续接动作阶段、方向和空间关系；保留快切，不强制叠化。黑帧、闪白和模糊放在边界并计入镜头时间，不独立凑镜头。只检查必要前提，如持物手、握持、位置和物品归属；换手或交接须有过渡。不重复到达、不恢复已离开的物体、不为收尾新增姿势或动作。检查即时因果反应，不插入无关节拍。

第四步：写 H3 并核对
将计划中的要求实际落实到 h3_prompt。核对用户指定内容与时间、大纲到分镜的对应、重复功能、状态衔接、文字和声音。没有用户依据的新限制要移除；不必要的新增事件要删除。必要转场须有后续内容，不能移到片尾代替。一次响应内修正，不额外调用编辑/审计模型。
"""

OUTPUT_RULES = """H3 信息分配
遵守随附 H3 skill 的格式、编号和摄影规范。以下信息分配覆盖其外观重述写法。使用英文改写，画面文字、对白、歌词保留指定原文。完整保留内容，不以固定字符目标牺牲要求覆盖，不截断，不设通用篇幅上限。
- subject_definitions：固定身份、外观和必要场景锚点只定义一次。Subject 按独立控制/引用需要划分，不照抄素材实体清单；可合并无需独立控制的场景组合，不合并不同人物。Picture/Video 表示素材，明确有依据的首尾帧、关键帧、构图或外观用途，不默认将参考图锁为首帧。姿态、站位、持物手放入镜头状态，不锁定全片。标题原文只在此写一次，镜头用主体标签及主/副标题指代。
- summary：只概括主线，不逐镜重述。
- retention_analysis：只说明保留范围和改变项，不复制属性清单。
- detailed_description：全局风格和持续效果写一次，镜头只写动作、关系、构图、摄影和动态变化；首次出场和特写也不重述固定外观。必要接触部位可以指明。通用转场只定义一次，再写应用时机和例外。文字需完整处于画面内并留边距；用户明确要求裁切字形、局部显露等例外按其时段执行。
- overall_soundscape：环境底噪与物理声音质感，不重复动作清单。同步声音的物理触发写在镜头中，停止走动即停止脚步；画外动作持续才可延续。自然余响可以跨切点，新撞击需要新动作。
- non_diegetic_music：配乐及其变化与结束。各声音层按时结束；遵守静音和锁定音轨，不编造无据的精确接触时刻。音色/节奏参考不授权复制音轨或歌词，不得擅加复制区间；已授权复用不因缺少音频分析而取消，也不能声称听到了未分析的内容。

最终 JSON 契约
仅输出一个对象，顶层严格为 content_plan、h3_prompt（字符串）、uncertainties（数组）。
content_plan 包含：
creative_brief：user_locked、reference_anchors、open_design；
task_mode：generate/reference_transfer/edit/continuation；
must_keep：要求及必要细节；
bindings：asset_id、role、retained_attributes、optional_inherited_attributes、excluded_attributes、exclusion_reasons；
developments：每条含 id、visible_change、outcome，作为内容大纲；
shots：每条含 development_ids、start_seconds、end_seconds、start_state、action、end_state、sound_cues。
使用真实 asset_id 和 reference_registry 编号，数值时间连续覆盖 0 到目标时长。不要将这些 content_plan 子字段放到顶层。uncertainties 只记录影响使用的具体问题。
"""

COMPACT_WRITING_INSTRUCTIONS = "\n\n".join((
    "你是视频内容规划与 MiniMax H3 提示词编写器。先构筑内容大纲，再安排镜头，最后写提示词。",
    SHOT_SCOPE_RULES, COMPLETION_RULES, INPUT_RULES, WORKFLOW, OUTPUT_RULES,
    "以下是本次任务和素材证据：\n",
))


def build_compact_writing_prompt(evidence: Mapping[str, Any]) -> str:
    return COMPACT_WRITING_INSTRUCTIONS + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
