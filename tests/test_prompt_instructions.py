import copy
import json
from pathlib import Path

from backend.prompt_instructions import (
    COMPACT_WRITING_INSTRUCTIONS,
    RESPONSE_CONTRACT,
    build_compact_writing_prompt,
)

ROOT = Path(__file__).resolve().parents[1]
SHARED_GUIDE = (ROOT / "skills/h3-prompt-writing/references/shared-zh-en.txt").read_text(encoding="utf-8")
REF2VA_GUIDE = (ROOT / "skills/h3-prompt-writing/references/ref2va-zh-en.txt").read_text(encoding="utf-8")
OUTLINE_SKILL = (ROOT / "skills/h3-outline-planning/SKILL.md").read_text(encoding="utf-8")
SHOT_SKILL = (ROOT / "skills/h3-shot-planning/SKILL.md").read_text(encoding="utf-8")
SOUND_SKILL = (ROOT / "skills/h3-sound-planning/SKILL.md").read_text(encoding="utf-8")


def test_instructions_prioritize_content_and_evidence():
    assert "即使标为 visible" in COMPACT_WRITING_INSTRUCTIONS
    assert "有证据支持的共同外观" in COMPACT_WRITING_INSTRUCTIONS
    assert "同一对象的互补视图" in COMPACT_WRITING_INSTRUCTIONS
    assert "不同人物或产品" in COMPACT_WRITING_INSTRUCTIONS
    assert "不要把素材分析逐项搬入" in COMPACT_WRITING_INSTRUCTIONS


def test_evidence_precedes_response_contract_without_mutation():
    evidence = {
        "user_request": "只替换台词：别走了，好吗？",
        "completion_policy": {"creative": False},
        "directives": [{"operation": "exclude", "scope": ["music"]}],
        "assets": [{"asset_id": "video_1", "events": [{"time_range": [0, 9]}]}],
    }
    original = copy.deepcopy(evidence)
    sent = build_compact_writing_prompt(evidence)
    suffix = "\n\n" + RESPONSE_CONTRACT
    assert sent.startswith(COMPACT_WRITING_INSTRUCTIONS)
    assert sent.endswith(suffix)
    encoded = sent[len(COMPACT_WRITING_INSTRUCTIONS):-len(suffix)]
    assert json.loads(encoded) == original
    assert sent.index('"user_request"') < sent.index("最终响应契约")
    assert evidence == original


def test_response_contract_only_defines_outer_payload():
    assert "顶层严格为 content_plan、h3_prompt、uncertainties" in RESPONSE_CONTRACT
    assert "h3_prompt 必须是一个字符串" in RESPONSE_CONTRACT
    assert "不能是对象、数组或分节字段" in RESPONSE_CONTRACT
    assert "subject_definitions：" not in RESPONSE_CONTRACT
    assert "non_diegetic_music：" not in RESPONSE_CONTRACT


def test_third_stage_locks_plan_and_delegates_writing():
    assert "第三阶段：锁定计划并交接 H3" in COMPACT_WRITING_INSTRUCTIONS
    assert "按照 system prompt 中的 H3 Prompt Writing Skill" in COMPACT_WRITING_INSTRUCTIONS
    assert "不得借写作过程新增、删除、合并或重新拆分" in COMPACT_WRITING_INSTRUCTIONS
    assert "每个事件、动作阶段、结果和切点都必须映射" in COMPACT_WRITING_INSTRUCTIONS
    assert "按照 system prompt 中的 H3 Sound Planning Skill" in COMPACT_WRITING_INSTRUCTIONS
    assert "audio_plan" in RESPONSE_CONTRACT
    assert "key_sound_events 为对象数组" in RESPONSE_CONTRACT
    assert "decision（use 或 N/A）" in RESPONSE_CONTRACT
    assert "tempo_energy_basis" in RESPONSE_CONTRACT


def test_sound_plan_is_locked_before_h3_writing():
    sound = COMPACT_WRITING_INSTRUCTIONS.index("H3 Sound Planning Skill")
    writing = COMPACT_WRITING_INSTRUCTIONS.index("H3 Prompt Writing Skill")
    assert sound < writing
    assert "把锁定的视觉计划和 audio_plan 一次性编译为 h3_prompt" in COMPACT_WRITING_INSTRUCTIONS
    assert "发现声音问题时只修正 audio_plan，不能改动视觉计划" in COMPACT_WRITING_INSTRUCTIONS


def test_outline_decisions_live_in_outline_planning_skill():
    for phrase in (
        "一个 development 必须带来可见的动作",
        "删除某个新增事件后目标仍完整时",
        "把“允许补全”和“允许扩写故事”分开判断",
        "默认只建立一条主要动作弧",
        "不要把造型手势、火焰突然升级",
        "同一现象从微弱、增强到峰值",
        "不包括叠加标题、字幕、品牌字样或包装文字开始可读",
        "不得决定镜头数量、景别、机位、运镜、切点、转场、声音或视觉包装",
        "大纲必须单向推进",
        "分镜阶段只能具体化怎样拍摄",
    ):
        assert phrase in OUTLINE_SKILL
        assert phrase not in SHOT_SKILL
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS


def test_scene_and_shot_decisions_live_in_shot_planning_skill():
    for phrase in (
        "对参与揭示、取得、交接、穿戴、启用或损坏的连续性关键物体维护状态",
        "不得先虚构更多 beat",
        "每个 development 必须在移除标题文字",
        "同一时间、空间、主体和动作目标默认放在一个连续镜头内",
        "全局风格只决定已有必要切点怎样发生",
        "应在实质性里程碑之间跳切",
        "不得把“用户要求了这种效果”改写成“用户锁定了这个切点”",
        "先检查同一镜头能否通过主体靠近",
        "同一动作自然到达其直接结果",
        "同一 development 跨越多个镜头时",
        "需要更持续地观看",
        "执行去表现层检查",
        "不能在分镜阶段悄悄补写故事",
    ):
        assert phrase in SHOT_SKILL
        assert phrase not in OUTLINE_SKILL
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS


def test_user_prompt_keeps_stage_order_and_schema_handoff():
    for phrase in (
        "最小事件大纲",
        "内容镜头骨架",
        "表现层分配",
        "H3 Outline Planning Skill",
        "H3 Shot Planning Skill",
        "development_ids 和 content_purpose",
        "cut_reason 和 continuity_bridge",
        "锁定 shots",
    ):
        assert phrase in COMPACT_WRITING_INSTRUCTIONS


def test_outline_is_locked_before_shot_planning():
    outline = COMPACT_WRITING_INSTRUCTIONS.index("H3 Outline Planning Skill")
    shot = COMPACT_WRITING_INSTRUCTIONS.index("H3 Shot Planning Skill")
    sound = COMPACT_WRITING_INSTRUCTIONS.index("H3 Sound Planning Skill")
    writing = COMPACT_WRITING_INSTRUCTIONS.index("H3 Prompt Writing Skill")
    assert outline < shot < sound < writing
    assert "分镜只能决定怎样拍摄，不能修订大纲" in COMPACT_WRITING_INSTRUCTIONS
    assert "不能新增、删除、合并、拆分、替换或改写事件" in COMPACT_WRITING_INSTRUCTIONS


def test_h3_execution_rules_live_in_system_skill():
    for phrase in (
        "每个 Shot 默认只在开头写一个绝对起始时间",
        "同一次、同方向、尚未结束",
        "完整运动弧线压成单个模糊帧",
        "旧内容不得重新清晰、混合或恢复",
    ):
        assert phrase in SHARED_GUIDE
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS


def test_prop_state_lives_in_shared_writing_guide():
    for phrase in (
        "后续才被揭示、取得、交接、穿戴或启用的物体必须保持阶段状态",
        "不能让该物体提前出现在人物手中",
        "不能仅靠“不提及”表达缺席",
    ):
        assert phrase in SHARED_GUIDE
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS


def test_audio_decisions_live_in_sound_planning_skill():
    for phrase in (
        "音频规划必须在 developments、Shot、动作、时间、运镜、视觉高潮和结尾画面锁定后进行",
        "不得为了配合音乐增加切点、动作、闪光、撞击或标题动画",
        "auditory_focus",
        "continuous_bed",
        "key_sound_events",
        "music_decision",
        "未指定配乐属于开放判断，不等于必须添加",
        "摄影机运动本身通常没有声音",
        "最多三个重要声音事件",
        "最高优先项必须与 `auditory_focus` 一致",
        "配乐在对白下方铺底",
        "删除全部音频计划后，锁定的视觉内容必须完全不变",
        "基线 → 积累 → 主要峰值 → 释放或结尾",
        "主要峰值之后不要默认让环境底层、声音设计和配乐同时保持峰值强度",
        "为主要瞬态保留动态空间",
        "配乐不得用同一频段和同一功能再次堆叠",
        "闪白、黑场、故障、遮挡和硬切不会自动获得呼啸、爆裂或静默",
        "每条配乐先选择一种主要音乐语言",
        "不得为了“更丰富”“更宏大”混入会把配乐带向第二种类型",
    ):
        assert phrase in SOUND_SKILL
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS


def test_target_keyframe_is_locked_at_first_identifiable_frame():
    for phrase in (
        "目标场景的第一帧可辨内容必须已经处于计划锁定的主体位置、景别和构图",
        "跨边界的摄影机余速只能存在于内容仍不可辨识的阶段",
        "主体不得因转场余速从画外滑入、横穿画面或被摄影机重新寻找",
    ):
        assert phrase in SHOT_SKILL
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS

    for moved_phrase in (
        "配乐的速度、能量和动态弧必须从已经锁定的视觉节奏推导",
        "不要让音乐能量与画面能量相反",
        "人物停止行走时脚步声停止",
    ):
        assert moved_phrase not in SHARED_GUIDE


def test_writing_guide_only_formats_locked_audio_plan():
    assert "按照已经锁定的 `audio_plan`" in SHARED_GUIDE
    assert "严格执行已经锁定的 `audio_plan.music_decision`" in SHARED_GUIDE
    assert "不要在写作阶段新增声音" in SHARED_GUIDE


def test_ref2va_information_assignment_lives_in_profile_guide():
    for phrase in (
        "高价值锚点写法",
        "默认使用两到三个英文句子",
        "哪些锚点必须跨镜保留",
        "前三个板块的信息边界与去重",
    ):
        assert phrase in REF2VA_GUIDE
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS


def test_shot_scope_policy_shared_by_both_stages():
    from backend.prompt_instructions import SHOT_SCOPE_RULES
    from backend.intent_resolver import build_intent_prompt
    for request in (
        "Shot 1 人物背对镜头。→ Hard cut。非完整Prompt，可自行补充",
        "全程一镜到底，不要增加镜头",
        "片尾硬切结束，不要后续画面",
    ):
        source = {"user_request": request, "assets": []}
        for prompt in (build_intent_prompt(source), build_compact_writing_prompt(source)):
            assert prompt.count(SHOT_SCOPE_RULES) == 1
            assert request in prompt
            assert "未描述后续" in prompt
            assert "片尾硬切" in prompt
            assert "不能以派生指令自身作证" in prompt


def test_minimum_completion_reaches_both_stages_without_changing_request():
    from backend.prompt_instructions import COMPLETION_RULES
    from backend.intent_resolver import build_intent_prompt
    for request in ("仅提供开场，可补充细节", "大胆发挥，设计完整故事和高潮", "严格复刻，一镜到底"):
        source = {"user_request": request, "assets": []}
        before = copy.deepcopy(source)
        for prompt in (build_intent_prompt(source), build_compact_writing_prompt(source)):
            assert prompt.count(COMPLETION_RULES) == 1
            assert request in prompt
        assert source == before
