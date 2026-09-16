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
    assert '请一次性分析输入图片' in RELATIONAL_IMAGE_PROMPT
    assert '生成语义归并' in RELATIONAL_IMAGE_PROMPT
    assert '服装、鞋、佩戴饰品和固定随身造型默认合并' in RELATIONAL_IMAGE_PROMPT
    assert '优先更少但完整的生成单元' in RELATIONAL_IMAGE_PROMPT
