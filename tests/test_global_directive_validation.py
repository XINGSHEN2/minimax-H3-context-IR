import pytest

from backend.context_ir import validate_context_ir
from backend.directive_binding import compile_directive_bindings


def payload_for(operation='preserve', asset_id=''):
    directive = {'directive_id': 'd_presentation', 'asset_id': asset_id,
                 'target': 'final presentation', 'operation': operation,
                 'scope': ['Keep clothing integrated into action'],
                 'priority': 'hard', 'provenance': 'explicit_user'}
    payload = {'intent': {'user_request': 'fashion campaign', 'directives': [directive]},
               'task': {'type': 'ref2va', 'duration_seconds': 15, 'aspect_ratio': '16:9', 'generate_audio': False},
               'assets': [{'asset_id': 'image_1', 'media_type': 'image'}],
               'asset_bindings': [{'binding_id': 'b1', 'asset_id': 'image_1',
                   'role': 'outfit', 'priority': 'hard',
                   'source_directive_ids': ['d_presentation'],
                   'inherit': ['outfit'], 'exclude': []}],
               'constraints': {}}
    return payload, directive


@pytest.mark.parametrize('operation,destination', [
    ('preserve', 'preserve'), ('exclude', 'prohibit'), ('may_change', 'allow_change')])
def test_global_directive_is_retained_once_not_copied_into_asset(operation, destination):
    payload, directive = payload_for(operation)
    compile_directive_bindings(payload, {'assets': payload['assets'], 'directives': [directive]})
    assert directive['scope'][0] in payload['constraints'][destination]
    assert directive['scope'][0] not in payload['asset_bindings'][0]['inherit']
    codes = {i.code for i in validate_context_ir(payload).issues}
    assert not codes & {'DIRECTIVE_SCOPE_NOT_INHERITED', 'EXCLUDE_DIRECTIVE_NOT_ENFORCED',
                        'GLOBAL_DIRECTIVE_NOT_RETAINED'}


def test_global_requirement_cannot_be_silently_dropped():
    payload, _ = payload_for()
    codes = {i.code for i in validate_context_ir(payload).issues}
    assert 'GLOBAL_DIRECTIVE_NOT_RETAINED' in codes


def test_asset_directive_still_requires_inherited_scope():
    payload, _ = payload_for(asset_id='image_1')
    codes = {i.code for i in validate_context_ir(payload).issues}
    assert 'DIRECTIVE_SCOPE_NOT_INHERITED' in codes
