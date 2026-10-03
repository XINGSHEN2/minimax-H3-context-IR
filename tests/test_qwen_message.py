import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.perception import split_qwen_message, QwenTransport, PerceptionProviderConfig

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
