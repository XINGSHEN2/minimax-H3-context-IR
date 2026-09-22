import copy, json
from pathlib import Path

from backend.agent import CORE_SKILLS
from backend.prompt_instructions import COMPACT_WRITING_INSTRUCTIONS, RESPONSE_CONTRACT, build_compact_writing_prompt

ROOT=Path(__file__).resolve().parents[1]
OUTLINE=(ROOT/'skills/h3-outline-planning/SKILL.md').read_text('utf-8')
SHOT=(ROOT/'skills/h3-shot-planning/SKILL.md').read_text('utf-8')
SOUND=(ROOT/'skills/h3-sound-planning/SKILL.md').read_text('utf-8')
WRITING=(ROOT/'skills/h3-prompt-writing/SKILL.md').read_text('utf-8')

def test_four_skills_loaded_in_dependency_order():
    assert CORE_SKILLS == ('h3-outline-planning','h3-shot-planning','h3-sound-planning','h3-prompt-writing')

def test_evidence_and_response_contract_round_trip():
    evidence={'user_request':'保持结尾','assets':[{'asset_id':'image_1'}]};before=copy.deepcopy(evidence)
    sent=build_compact_writing_prompt(evidence);suffix='\n\n'+RESPONSE_CONTRACT
    assert sent.startswith(COMPACT_WRITING_INSTRUCTIONS) and sent.endswith(suffix)
    assert json.loads(sent[len(COMPACT_WRITING_INSTRUCTIONS):-len(suffix)]) == evidence
    assert evidence == before

def test_user_prompt_is_orchestration_not_domain_policy():
    for phrase in ('H3 Outline Planning Skill','H3 Shot Planning Skill','H3 Sound Planning Skill','H3 Prompt Writing Skill'):
        assert phrase in COMPACT_WRITING_INSTRUCTIONS
    for phrase in ('视点剥离','强度剥离','摄影机运动本身通常没有声音','望远镜'):
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS

def test_outline_owns_v33_semantic_compression():
    for phrase in ('Development 不表示观察角度','连续目标合并','表现层剥离','视点剥离','强度剥离',
                   '不同空间中的观察与反应','默认采用“完成用户意图所需的最小充分补全”'):
        assert phrase in OUTLINE
        assert phrase not in COMPACT_WRITING_INSTRUCTIONS

def test_shot_skill_preserves_v33_camera_and_fast_cut_core():
    for phrase in ('一个镜头可以包含多个有序动作阶段','不能自行决定镜头数量或创建切点',
                   '应在实质性里程碑之间跳切','不得先虚构更多 beat',
                   '同一 development 跨越多个镜头时','完成初步分镜后执行去表现层检查'):
        assert phrase in SHOT

def test_sound_and_writing_remain_separate():
    assert 'auditory_focus' in SOUND and 'music_decision' in SOUND
    assert '不得为了配合音乐增加切点' in SOUND
    assert '编译成 H3' in WRITING
    assert '声音不得改变事件、镜头、动作、时间、运镜或结尾画面' in COMPACT_WRITING_INSTRUCTIONS

def test_response_contract_only_defines_payload():
    assert '顶层严格为 content_plan、h3_prompt、uncertainties' in RESPONSE_CONTRACT
    assert 'h3_prompt 必须是包含完整六节最终 H3 的字符串' in RESPONSE_CONTRACT
    assert '视点剥离' not in RESPONSE_CONTRACT
