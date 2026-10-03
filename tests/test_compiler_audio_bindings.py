import copy
import pytest
from backend.compiler import transport_issues
from backend.evidence import build_writer_evidence
from backend.contracts import build_h3_request


def fixture():
    video = {'asset_id': 'video_1', 'media_type': 'video', 'uri': '/tmp/source.mp4'}
    audio = {'asset_id': 'audio_1', 'media_type': 'audio', 'uri': '/tmp/voice.wav'}
    source = {'user_request': '保留背景音乐，替换对白',
              'task': {'type': 'ref2va', 'duration_seconds': 15, 'aspect_ratio': '16:9'},
              'assets': [video, audio], 'perception': {'schema_version': 'media_analysis.v3',
              'assets': [{**video, 'technical': {'has_audio': True}, 'audio': {
                  'status': 'analyzed', 'audio_id': 'video_1:audio',
                  'source_asset_id': 'video_1', 'source_type': 'embedded_audio'}},
                  {**audio, 'audio': {'status': 'analyzed'}}]}}
    result = {'content_plan': {'bindings': [{'asset_id': k} for k in ['video_1', 'audio_1', 'video_1:audio']],
                              'shots': [{'start_seconds': 0, 'end_seconds': 15}]},
              'h3_prompt': 'subject_definitions: <Video 1> source; <Audio 1> voice; <Audio 2> original track.\n'
              'summary: Edit dialogue.\nretention_analysis: Keep music.\ndetailed_description:\n'
              '[Shot 1] Keep the original action.\noverall_soundscape: Replace dialogue.\nnon_diegetic_music: Keep original.'}
    return source, build_writer_evidence(source), result


def test_standalone_and_embedded_audio_both_valid_without_duplicate_upload():
    source, evidence, result = fixture()
    assert transport_issues(result, evidence)[0] == []
    labels = {r['asset_id']: r['official_label'] for r in evidence['reference_registry']}
    assert labels['audio_1'] == '<Audio 1>'
    assert labels['video_1:audio'] == '<Audio 2>'
    request = build_h3_request(source, '/tmp/prompt.txt', '/tmp/out')
    assert len(request['conditions']) == 2
    assert [c['uri'] for c in request['conditions']] == ['/tmp/source.mp4', '/tmp/voice.wav']


@pytest.mark.parametrize('change', ['missing_video', 'silent_video', 'no_analysis', 'wrong_parent', 'wrong_id', 'collision', 'duplicate_label'])
def test_invalid_embedded_audio_is_rejected(change):
    _, evidence, result = fixture()
    row = evidence['reference_registry'][-1]
    track = evidence['assets'][0]['audio']
    if change == 'missing_video': evidence['assets'] = evidence['assets'][1:]
    if change == 'silent_video': evidence['assets'][0]['technical']['has_audio'] = False
    if change == 'no_analysis': track['status'] = 'no_track'
    if change == 'wrong_parent': row['source_asset_id'] = 'audio_1'
    if change == 'wrong_id': row['asset_id'] = 'video_2:audio'
    if change == 'collision': row['asset_id'] = 'audio_1'
    if change == 'duplicate_label': row['official_label'] = '<Audio 1>'
    assert transport_issues(result, evidence)[0]


def test_unregistered_track_and_unknown_audio_label_are_rejected():
    _, evidence, result = fixture()
    evidence['reference_registry'].pop()
    errors, _ = transport_issues(result, evidence)
    assert any('unknown asset_id: video_1:audio' in e for e in errors)
    assert any('nonexistent Audio 2' in e for e in errors)


def test_video_only_uses_audio_one():
    source, _, result = fixture()
    source['assets'] = source['assets'][:1]
    source['perception']['assets'] = source['perception']['assets'][:1]
    evidence = build_writer_evidence(source)
    result['content_plan']['bindings'] = [{'asset_id': 'video_1'}, {'asset_id': 'video_1:audio'}]
    result['h3_prompt'] = result['h3_prompt'].replace('<Audio 2>', '<Audio 1>')
    assert transport_issues(result, evidence)[0] == []


@pytest.mark.parametrize('section', ['subject_definitions', 'summary', 'retention_analysis', 'overall_soundscape', 'non_diegetic_music'])
def test_dialogue_tags_in_edit_explanations_are_rejected(section):
    _, evidence, result = fixture()
    result['h3_prompt'] = result['h3_prompt'].replace(section + ':', section + ': <d>[Chinese] 然后今天买了一些小零食。</d>')
    assert any('Dialogue tags' in error for error in transport_issues(result, evidence)[0])


def test_final_dialogue_and_quoted_sign_replacement_are_allowed():
    _, evidence, result = fixture()
    result['h3_prompt'] = result['h3_prompt'].replace(
        'summary: Edit dialogue.',
        'summary: Replace "然后今天买了一些小零食。" with "然后今天买了一堆可乐。"; replace sign "全家" with "互惠".')
    result['h3_prompt'] = result['h3_prompt'].replace(
        '[Shot 1] Keep the original action.',
        '[Shot 1] Keep the original action. The sign reads "互惠" instead of "全家". The woman (S1) says <d>[Chinese] 然后今天买了一堆可乐。</d>.')
    assert transport_issues(result, evidence)[0] == []
