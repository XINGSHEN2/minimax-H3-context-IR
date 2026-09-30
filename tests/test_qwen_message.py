import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.perception import split_qwen_message, LocalQwen3VL32BProvider, PerceptionProviderConfig

class QwenMessageTests(unittest.TestCase):
    def test_separate_fields_preserve_final_literal(self):
        final = '{"summary":"literal </think> text"}'
        self.assertEqual(split_qwen_message({'reasoning_content':'analysis', 'content':final}), ('analysis',final))
    def test_legacy(self):
        self.assertEqual(split_qwen_message({'content':'<think>{"wrong":1}</think>{"summary":"ok"}'}), ('{"wrong":1}','{"summary":"ok"}'))
    def test_plain_final(self):
        self.assertEqual(split_qwen_message({'content':' {} '}), ('','{}'))
    def test_unfinished_legacy_has_no_final(self):
        self.assertEqual(split_qwen_message({'content':'<think>{"wrong":1}'}), ('{"wrong":1}',''))
    def test_run_task_separates_and_saves(self):
        p=LocalQwen3VL32BProvider(PerceptionProviderConfig(options={'json_parse_retries':0}))
        response={'choices':[{'message':{'reasoning_content':'{"wrong":1}', 'content':'{"summary":"ok"}'}}]}
        with tempfile.TemporaryDirectory() as d, patch.object(p,'_media_url',return_value='http://asset/input'), patch.object(p,'_request_json',return_value=response):
            out=Path(d)/'out';result=p._run_task(Path(d)/'input.png','Describe',out,1024)
            self.assertEqual(result['summary'],'ok');self.assertNotIn('wrong',result)
            self.assertEqual((out/'thinking.txt').read_text(),'{"wrong":1}')
            self.assertEqual(json.loads((out/'final.txt').read_text()),{'summary':'ok'})
    def test_reasoning_only_is_rejected_and_saved(self):
        p=LocalQwen3VL32BProvider(PerceptionProviderConfig(options={'json_parse_retries':0}))
        response={'choices':[{'message':{'reasoning_content':'{"summary":"not evidence"}','content':None}}]}
        with tempfile.TemporaryDirectory() as d, patch.object(p,'_media_url',return_value='http://asset/input'), patch.object(p,'_request_json',return_value=response):
            out=Path(d)/'out'
            with self.assertRaises(RuntimeError):p._run_task(Path(d)/'input.png','Describe',out,1024)
            self.assertTrue((out/'response.json').exists())
