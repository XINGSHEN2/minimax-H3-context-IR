from backend.evidence import build_writer_evidence


def test_entity_order_does_not_drop_late_subject_or_break_relations():
    entities = [{'entity_id': f'e{i}', 'category': 'object', 'attributes': {}}
                for i in range(13)]
    entities[-1].update(category='person', summary='The user-selected pilot')
    relations = [{'relation_id': f'r{i}', 'type': 'near', 'subject_id': 'e12',
                  'object_id': 'e0', 'confidence': .9, 'source': 'visible'}
                 for i in range(11)]
    result = build_writer_evidence({
        'assets': [{'asset_id': 'image_1', 'media_type': 'image'}],
        'perception': {'assets': [{'asset_id': 'image_1', 'entities': entities,
                                    'relations': relations}]},
    })['assets'][0]
    assert [e['entity_id'] for e in result['entities']] == [e['entity_id'] for e in entities]
    assert result['entities'][-1]['summary'] == 'The user-selected pilot'
    assert len(result['relations']) == 11
    ids = {e['entity_id'] for e in result['entities']}
    assert all(r['subject_id'] in ids and r['object_id'] in ids for r in result['relations'])


def test_longer_event_list_retains_actual_ending():
    events = [{'event_id': f'event_{i}', 'time_range': [i, i + 1],
               'action': 'walk', 'entity_ids': ['e0'], 'confidence': .9}
              for i in range(15)]
    events[-1]['action'] = 'puts the item down before leaving'
    result = build_writer_evidence({
        'assets': [{'asset_id': 'video_1', 'media_type': 'video'}],
        'perception': {'assets': [{'asset_id': 'video_1', 'events': events}]},
    })['assets'][0]['events']
    assert len(result) == 15
    assert result[-1]['action'] == events[-1]['action']
    assert result[-1]['time_range'] == [14, 15]
