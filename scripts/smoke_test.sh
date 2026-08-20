#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

python3 -m py_compile agent.py context_ir.py perception.py backend/agent.py backend/context_ir.py backend/perception.py
python3 -m json.tool examples/request.example.json >/dev/null

python3 - <<'PY'
import os

from backend.agent import reasoning_provider_config

os.environ['CONTEXT_IR_LLM_PROVIDER'] = 'glm'
glm = reasoning_provider_config()
assert glm['selection'] == 'glm'
assert glm['model'] == os.environ.get('GLM_MODEL', 'GLM-5.2')
assert glm['api_key_env'] == 'OPENAI_API_KEY'

os.environ['CONTEXT_IR_LLM_PROVIDER'] = 'deepseek'
deepseek = reasoning_provider_config()
assert deepseek['selection'] == 'deepseek'
assert deepseek['model'] == os.environ.get('DEEPSEEK_MODEL', 'deepseek-v4-flash')
assert deepseek['base_url'] == os.environ.get('DEEPSEEK_RESPONSES_BASE_URL', 'https://api.deepseek.com')
assert deepseek['api_key_env'] == 'DEEPSEEK_API_KEY'

os.environ['CONTEXT_IR_LLM_PROVIDER'] = 'invalid'
try:
    reasoning_provider_config()
except ValueError:
    pass
else:
    raise AssertionError('invalid reasoning provider must be rejected')
PY

skill_count="$(find skills -maxdepth 2 -name SKILL.md | wc -l)"
if [[ "$skill_count" -ne 9 ]]; then
  echo "Expected 9 official Skills, found $skill_count" >&2
  exit 3
fi

python3 - <<'PY'
import json
from context_ir import audit_h3_prompt, compile_context_ir, render_h3_prompt, validate_context_ir

with open('examples/request.example.json', encoding='utf-8') as stream:
    source = json.load(stream)
task = source['task']
assets = source['assets']
bindings = [
    {'binding_id':'b_identity','asset_id':'image_1','target':'Subject 1','role':'identity','priority':'hard','inherit':['face identity'],'exclude':['outfit','background']},
    {'binding_id':'b_outfit','asset_id':'image_2','target':'Subject 1 outfit','role':'outfit','priority':'hard','inherit':['garment design'],'exclude':['identity','background']},
    {'binding_id':'b_product','asset_id':'image_3','target':'Product 1','role':'product','priority':'hard','inherit':['product geometry'],'exclude':['person','background']},
    {'binding_id':'b_motion','asset_id':'video_1','target':'Subject 1 motion','role':'motion','priority':'soft','inherit':['body motion'],'exclude':['identity','outfit','scene']},
    {'binding_id':'b_voice','asset_id':'audio_1','target':'Voice 1','role':'voice','priority':'soft','inherit':['vocal character'],'exclude':['source noise']},
]
rules = [
    {'binding_id':item['binding_id'],'allow':item['inherit'],'block':item['exclude']}
    for item in bindings
]
ir = compile_context_ir({
    'schema_version':'0.1.0',
    'intent':{'user_request':source['user_request'],'resolved_request':'Dance-led product advertisement','assumptions':[],'uncertainties':[]},
    'protocol':{'rewrite_language':'English','preserve_source_language_for':['dialogue','lyrics','visible scene text'],'summary_task_types':['reference generation','audio reference']},
    'task':task,
    'assets':assets,
    'perception':source['perception'],
    'asset_bindings':bindings,
    'subjects':[
        {'subject_id':'subject_1','name':'the advertised product','kind':'product','primary':True,'description':'a stable product with accurate geometry','source_asset_ids':['image_3'],'binding_ids':['b_product'],'appearance_shot_ids':['01','02','03','04'],'retention_mode':'fully_preserved','retention_description':'the product geometry remains accurate'},
        {'subject_id':'subject_2','name':'the performer','kind':'person','primary':False,'description':'a stable performer identity wearing the referenced outfit','source_asset_ids':['image_1','image_2'],'binding_ids':['b_identity','b_outfit','b_motion'],'appearance_shot_ids':['01','02','03','04'],'retention_mode':'fully_preserved','retention_description':'face identity and outfit remain stable'},
    ],
    'reference_relationships':[
        {'asset_id':'image_1','relationship':'reference_generation','subject_refs':['subject_2'],'definition':'is the identity reference for <Subject 2>','retention_mode':'fully_preserved','retention_description':'face identity is retained'},
        {'asset_id':'image_2','relationship':'reference_generation','subject_refs':['subject_2'],'definition':'is the outfit reference for <Subject 2>','retention_mode':'attribute_transfer','retention_description':'the garment design transfers to <Subject 2>'},
        {'asset_id':'image_3','relationship':'reference_generation','subject_refs':['subject_1'],'definition':'is the authoritative product reference for <Subject 1>','retention_mode':'fully_preserved','retention_description':'product geometry is retained'},
        {'asset_id':'video_1','relationship':'reference_generation','subject_refs':['subject_2'],'definition':'is the motion reference for <Subject 2>','retention_mode':'weak_reference','retention_description':'body motion guides the performance'},
        {'asset_id':'audio_1','relationship':'audio_reference','subject_refs':['subject_2'],'definition':'is the voice reference for <Subject 2>','retention_mode':'reference','retention_description':'vocal character guides delivery'},
    ],
    'decision_plan':{
        'intent_hierarchy':{
            'explicit_goal':'Create a dance-led product advertisement from the supplied references',
            'intended_outcome':'Make the advertised product the memorable commercial result while references support execution',
            'execution_means':['retain performer identity and outfit','transfer body motion','reference vocal character'],
            'non_authorized_inferences':['source video performer identity','source video scene','unsupported brand claims'],
        },
        'asset_authority':[
            {'asset_id':'image_1','authority':'authoritative_content','controlled_dimensions':['face identity'],'secondary_dimensions':[]},
            {'asset_id':'image_2','authority':'authoritative_content','controlled_dimensions':['garment design'],'secondary_dimensions':[]},
            {'asset_id':'image_3','authority':'authoritative_content','controlled_dimensions':['product geometry'],'secondary_dimensions':['surface presentation']},
            {'asset_id':'video_1','authority':'scoped_reference','controlled_dimensions':['body motion'],'secondary_dimensions':['performance pacing']},
            {'asset_id':'audio_1','authority':'scoped_reference','controlled_dimensions':['vocal character'],'secondary_dimensions':[]},
        ],
        'attribute_decisions':[
            {'asset_id':'image_1','attribute':'face identity','decision':'cite','target_subject_id':'subject_2','priority':'hard','evidence_basis':'asset_role','rationale':'The image is the authoritative identity source'},
            {'asset_id':'image_2','attribute':'garment design','decision':'transfer','target_subject_id':'subject_2','priority':'hard','evidence_basis':'asset_role','rationale':'The garment is assigned to the performer'},
            {'asset_id':'image_3','attribute':'product geometry','decision':'cite','target_subject_id':'subject_1','priority':'hard','evidence_basis':'visible','rationale':'The product image controls advertised geometry'},
            {'asset_id':'video_1','attribute':'body motion','decision':'transfer','target_subject_id':'subject_2','priority':'soft','evidence_basis':'visible','rationale':'Only motion supports the performance'},
            {'asset_id':'video_1','attribute':'performer identity','decision':'discard','target_subject_id':'','priority':'soft','evidence_basis':'asset_role','rationale':'Motion reference identity is outside its assigned scope'},
            {'asset_id':'audio_1','attribute':'vocal character','decision':'transfer','target_subject_id':'subject_2','priority':'soft','evidence_basis':'asset_role','rationale':'The audio is assigned as a voice reference'},
        ],
        'attention_budget':[
            {'subject_id':'subject_1','weight':0.7,'role':'primary','requirements':['Hold clear product visibility','End on a hero close-up']},
            {'subject_id':'subject_2','weight':0.3,'role':'supporting','requirements':['Support the product reveal without displacing it']},
        ],
    },
    'state_relations':[
        {
            'relation_id':'state_1','subject_id':'subject_2','predicate':'holds','object_subject_id':'subject_1',
            'start_seconds':0,'end_seconds':15,'persistence':'across_cuts','required_shot_ids':['01','02','03','04'],
            'description':'The performer continuously keeps the advertised product physically present through every cut',
            'forbidden_breaks':['a missing product','a substituted product'],
        },
    ],
    'creative_focus':{
        'primary_target':'Product 1', 'primary_subject_id':'subject_1', 'primary_asset_id':'image_3', 'primary_binding_ids':['b_product'],
        'objective':'Showcase Product 1 as the main commercial subject',
        'supporting_asset_ids':['image_1','image_2','video_1','audio_1'],
        'required_shot_ids':['03','04'],
        'presentation_requirements':['Keep the product clearly visible','End on a product hero close-up'],
    },
    'isolation_rules':rules,
    'constraints':{'preserve':['face identity','product geometry'],'allow_change':['lighting'],'prohibit':['identity drift']},
    'timeline':[
        {'shot_id':'01','start_seconds':0,'end_seconds':3,'purpose':'Establish the supporting performer','focus_level':'supporting','event':'Establish subject','subject_refs':['subject_1','subject_2'],'asset_refs':['image_1','image_2'],'binding_refs':['b_identity','b_outfit'],'reference_transfer':['face identity','garment design'],'required_state_refs':['state_1']},
        {'shot_id':'02','start_seconds':3,'end_seconds':8,'purpose':'Use performance energy to lead into the offer','focus_level':'supporting','event':'Perform dance phrase','subject_refs':['subject_1','subject_2'],'asset_refs':['video_1','audio_1'],'binding_refs':['b_motion','b_voice'],'reference_transfer':['body motion','vocal character'],'required_state_refs':['state_1']},
        {'shot_id':'03','start_seconds':8,'end_seconds':12,'purpose':'Reveal the advertised product clearly','focus_level':'primary','event':'Present product','subject_refs':['subject_1','subject_2'],'asset_refs':['image_3'],'binding_refs':['b_product'],'reference_transfer':['product geometry'],'required_state_refs':['state_1']},
        {'shot_id':'04','start_seconds':12,'end_seconds':15,'purpose':'Create the final product memory point','focus_level':'hero','event':'Product hero close-up','subject_refs':['subject_1','subject_2'],'asset_refs':['image_3'],'binding_refs':['b_product'],'reference_transfer':['product geometry'],'required_state_refs':['state_1']},
    ],
    'audio_plan':{'voice':'follow audio reference','music':'beat-led music','sound_effects':'subtle','ambient_sound':'studio room tone','sync_rules':['dance accents align to beats']},
    'generation_description':{'cinematography':'clean commercial','lighting':'soft key light','materials':'accurate surfaces','performance':'controlled','continuity':'stable identity and product'},
})
report = validate_context_ir(ir)
assert report.passed, report.to_dict()
prompt = render_h3_prompt(ir)
assert 'subject_definitions:' in prompt
assert 'non_diegetic_music:' in prompt
assert '<Subject 1>' in prompt and '<Subject 2>' in prompt
assert '[reference generation + audio reference]' in prompt
assert '[ref2va]' not in prompt
assert audit_h3_prompt(ir, prompt).passed, audit_h3_prompt(ir, prompt).to_dict()
bad_subject_prompt = prompt.replace('<Subject 1>', '<Product hero>')
bad_subject_audit = audit_h3_prompt(ir, bad_subject_prompt)
assert not bad_subject_audit.passed
assert any(item.code == 'PROMPT_NONOFFICIAL_ANGLE_TAG' for item in bad_subject_audit.issues)

for mode, frame_roles, expected_section in [
    ('t2va', [], 'integrated_multimodal_description:'),
    ('i2va', [('image_1', 'first_frame')], 'For the target video'),
    ('fl2va', [('image_1', 'first_frame'), ('image_3', 'last_frame')], 'How the reference pictures align'),
    ('l2va', [('image_3', 'last_frame')], 'How the reference pictures align'),
]:
    candidate = json.loads(json.dumps(ir))
    # Legacy callers may omit decision_plan; keep all pre-existing modes readable.
    candidate.pop('decision_plan', None)
    candidate.pop('state_relations', None)
    for shot in candidate['timeline']:
        shot.pop('required_state_refs', None)
    candidate['task']['type'] = mode
    candidate['asset_bindings'] = []
    candidate['isolation_rules'] = []
    for shot in candidate['timeline']:
        shot['binding_refs'] = []
    for index, (asset_id, role) in enumerate(frame_roles, start=1):
        candidate['asset_bindings'].append({
            'binding_id': f'b_frame_{index}', 'asset_id': asset_id,
            'target': role, 'role': role, 'priority': 'hard',
            'inherit': ['complete frame'], 'exclude': [],
        })
        candidate['isolation_rules'].append({
            'binding_id': f'b_frame_{index}', 'allow': ['complete frame'], 'block': [],
        })
    if mode == 't2va':
        candidate['assets'] = []
        candidate['perception'] = None
        candidate['reference_relationships'] = []
        candidate['subjects'] = [{
            'subject_id':'subject_1','name':'the generated commercial subject','kind':'product','primary':True,
            'description':'a stable generated product','source_asset_ids':[],'binding_ids':[],
            'appearance_shot_ids':['01','02','03','04'],'retention_mode':'fully_preserved',
            'retention_description':'the generated product remains stable',
        }]
        for shot in candidate['timeline']:
            shot['asset_refs'] = []
            shot['subject_refs'] = ['subject_1']
        candidate['creative_focus'] = {
            'primary_target':'Generated commercial subject', 'primary_subject_id':'subject_1', 'primary_asset_id':'', 'primary_binding_ids':[],
            'objective':'Keep the generated commercial subject visually dominant', 'supporting_asset_ids':[],
            'required_shot_ids':['01'], 'presentation_requirements':['Establish the subject clearly'],
        }
    else:
        focus_index = len(frame_roles)
        focus_shot = '01' if frame_roles[-1][1] == 'first_frame' else candidate['timeline'][-1]['shot_id']
        focus_binding = f'b_frame_{focus_index}'
        focus_subject = 'subject_2' if frame_roles[-1][0] == 'image_1' else 'subject_1'
        valid_frame_bindings = {item['binding_id'] for item in candidate['asset_bindings']}
        for subject in candidate['subjects']:
            subject['binding_ids'] = [item for item in subject['binding_ids'] if item in valid_frame_bindings]
        candidate['creative_focus'] = {
            'primary_target':'Keyframe-controlled subject', 'primary_subject_id':focus_subject, 'primary_asset_id':frame_roles[-1][0],
            'primary_binding_ids':[focus_binding], 'objective':'Preserve the keyframe-controlled subject as the visual focus',
            'supporting_asset_ids':[asset_id for asset_id, _ in frame_roles[:-1]],
            'required_shot_ids':[focus_shot], 'presentation_requirements':['Preserve the aligned keyframe composition'],
        }
        focus_timeline_index = 0 if focus_shot == '01' else -1
        candidate['timeline'][focus_timeline_index]['binding_refs'] = [focus_binding]
        if focus_subject not in candidate['timeline'][focus_timeline_index]['subject_refs']:
            candidate['timeline'][focus_timeline_index]['subject_refs'].append(focus_subject)
        for subject in candidate['subjects']:
            subject['primary'] = subject['subject_id'] == focus_subject
            if subject['subject_id'] == focus_subject and focus_binding not in subject['binding_ids']:
                subject['binding_ids'].append(focus_binding)
            subject['appearance_shot_ids'] = [shot['shot_id'] for shot in candidate['timeline'] if subject['subject_id'] in shot['subject_refs']]
    base_prompt = render_h3_prompt(candidate)
    assert expected_section in base_prompt
    assert 'subject_definitions:' not in base_prompt
    assert audit_h3_prompt(candidate, base_prompt).passed, (mode, audit_h3_prompt(candidate, base_prompt).to_dict(), base_prompt)
print(json.dumps({'passed':True,'official_skills':9,'context_ir_schema':'0.1.0'}, ensure_ascii=False))
PY

python3 - <<'PY'
import json
from perception import GiteeQwen3VLProvider, PERCEPTION_PROVIDERS, PerceptionProviderConfig
from backend.perception import _json_object

malformed_localization = '{"boxes":[["nail art",70,100,270,390,0.95],"nail art",290,100,440,390,0.95]}'
repaired = _json_object(malformed_localization)
assert repaired == {'boxes': [
    ['nail art', 70.0, 100.0, 270.0, 390.0, 0.95],
    ['nail art', 290.0, 100.0, 440.0, 390.0, 0.95],
]}

captured = []
def mock_transport(messages, config):
    captured.append(messages)
    return json.dumps({
        'asset_id': 'ignored',
        'observations': [{'text': 'A product is visible'}],
        'entities': [{'type': 'product', 'description': 'rectangular package'}],
        'events': [], 'audio': {},
        'technical': {'media_type': 'image', 'visible_text': []},
        'transcript': '', 'confidence': 0.9, 'uncertainties': [],
    })

provider = GiteeQwen3VLProvider(
    PerceptionProviderConfig(
        provider='gitee-qwen3-vl',
        model='Qwen3-VL-30B-A3B-Instruct',
        options={'base_url': 'https://ai.gitee.com/v1'},
    ),
    completion_transport=mock_transport,
)
result = provider.analyze([
    {'asset_id': 'image_1', 'media_type': 'image', 'uri': 'https://example.com/product.png'},
    {'asset_id': 'audio_1', 'media_type': 'audio', 'uri': '/data/audio.wav'},
])
assert result['schema_version'] == 'media_analysis.v2'
assert result['provider']['model'] == 'Qwen3-VL-30B-A3B-Instruct'
assert result['assets'][0]['asset_id'] == 'image_1'
assert result['assets'][1]['technical']['analysis_status'] == 'unsupported_by_visual_provider'
assert captured[0][1]['content'][0]['image_url']['url'] == 'https://example.com/product.png'
assert 'reasoning' not in json.dumps(result)
assert 'local-qwen3-vl-32b' in PERCEPTION_PROVIDERS.names()
print(json.dumps({'passed': True, 'vlm_provider': result['provider']['name'], 'vlm_model': result['provider']['model']}))
PY
