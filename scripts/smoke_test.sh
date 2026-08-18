#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

python3 -m py_compile agent.py context_ir.py perception.py backend/agent.py backend/context_ir.py backend/perception.py
python3 -m json.tool examples/request.example.json >/dev/null

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
    'task':task,
    'assets':assets,
    'perception':source['perception'],
    'asset_bindings':bindings,
    'isolation_rules':rules,
    'constraints':{'preserve':['face identity','product geometry'],'allow_change':['lighting'],'prohibit':['identity drift']},
    'timeline':[
        {'shot_id':'01','start_seconds':0,'end_seconds':3,'event':'Establish subject','asset_refs':['image_1','image_2'],'binding_refs':['b_identity','b_outfit']},
        {'shot_id':'02','start_seconds':3,'end_seconds':8,'event':'Perform dance phrase','asset_refs':['video_1','audio_1'],'binding_refs':['b_motion','b_voice']},
        {'shot_id':'03','start_seconds':8,'end_seconds':12,'event':'Present product','asset_refs':['image_3'],'binding_refs':['b_product']},
        {'shot_id':'04','start_seconds':12,'end_seconds':15,'event':'Product hero close-up','asset_refs':['image_3'],'binding_refs':['b_product']},
    ],
    'audio_plan':{'voice':'follow audio reference','music':'beat-led music','sound_effects':'subtle','ambient_sound':'studio room tone','sync_rules':['dance accents align to beats']},
    'generation_description':{'cinematography':'clean commercial','lighting':'soft key light','materials':'accurate surfaces','performance':'controlled','continuity':'stable identity and product'},
})
report = validate_context_ir(ir)
assert report.passed, report.to_dict()
prompt = render_h3_prompt(ir)
assert 'subject_definitions:' in prompt
assert 'non_diegetic_music:' in prompt
assert audit_h3_prompt(ir, prompt).passed, audit_h3_prompt(ir, prompt).to_dict()

for mode, frame_roles, expected_section in [
    ('t2va', [], 'integrated_multimodal_description:'),
    ('i2va', [('image_1', 'first_frame')], 'For the target video'),
    ('fl2va', [('image_1', 'first_frame'), ('image_3', 'last_frame')], 'How the reference pictures align'),
    ('l2va', [('image_3', 'last_frame')], 'How the reference pictures align'),
]:
    candidate = json.loads(json.dumps(ir))
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
    base_prompt = render_h3_prompt(candidate)
    assert expected_section in base_prompt
    assert 'subject_definitions:' not in base_prompt
    assert audit_h3_prompt(candidate, base_prompt).passed, (mode, audit_h3_prompt(candidate, base_prompt).to_dict(), base_prompt)
print(json.dumps({'passed':True,'official_skills':9,'context_ir_schema':'0.1.0'}, ensure_ascii=False))
PY

python3 - <<'PY'
import json
from perception import GiteeQwen3VLProvider, PERCEPTION_PROVIDERS, PerceptionProviderConfig

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
assert result['schema_version'] == 'media_analysis.v1'
assert result['provider']['model'] == 'Qwen3-VL-30B-A3B-Instruct'
assert result['assets'][0]['asset_id'] == 'image_1'
assert result['assets'][1]['technical']['analysis_status'] == 'unsupported_by_visual_provider'
assert captured[0][1]['content'][0]['image_url']['url'] == 'https://example.com/product.png'
assert 'reasoning' not in json.dumps(result)
assert 'local-qwen3-vl-32b' in PERCEPTION_PROVIDERS.names()
print(json.dumps({'passed': True, 'vlm_provider': result['provider']['name'], 'vlm_model': result['provider']['model']}))
PY
