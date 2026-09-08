"""Prompt contract tests, not evidence of VLM accuracy."""
import json

from backend.perception import RELATIONAL_IMAGE_PROMPT


def test_image_example_is_concrete_and_relations_resolve():
    example = json.loads(RELATIONAL_IMAGE_PROMPT.splitlines()[1])
    ids = {item['entity_id'] for item in example['entities']}
    assert all(r[2] in ids and r[3] in ids for r in example['relations'])
    assert all(f[1] != 'name' and f[2] != 'value'
               for e in example['entities'] for f in e['features'])


def test_image_instruction_protects_content_without_more_calls():
    assert 'Analyze this image once' in RELATIONAL_IMAGE_PROMPT
    assert "main entity's features" in RELATIONAL_IMAGE_PROMPT
    assert 'independent requested role' in RELATIONAL_IMAGE_PROMPT
    assert 'Replace every example value' in RELATIONAL_IMAGE_PROMPT
