import unittest

from scripts.run_v63_qwen_joint import normalize_grouped


class QwenJointNormalizationTests(unittest.TestCase):
    def test_preserves_schema_drift_without_dropping_visual_facts(self):
        grouped, repairs = normalize_grouped({
            'summary': 'A figure stands before a fleet.',
            'global_analysis': {'framing_layers': [{'description': 'window frame'}]},
            'visible_text': [{'text': 'TITLE', 'source_asset_ids': ['image_1']}],
            'entities': [{
                'entity_id': 'entity_1', 'label': 'figure',
                'summary': 'back view',
                'features': [['geometry', 'pose', 'standing', 'high', 'visible']],
                'source_asset_ids': ['image_1'],
            }],
            'relations': [{
                'from': 'entity_1', 'to': 'entity_2',
                'relation': 'facing', 'source_asset_ids': ['image_1'],
            }],
        })
        self.assertEqual(grouped['entities'][0]['features'][0][3], 0.9)
        self.assertIn('figure', grouped['entities'][0]['summary'])
        self.assertEqual(grouped['global_analysis']['visible_text'][0]['text'], 'TITLE')
        self.assertEqual(grouped['relations'][0][1:4], ['facing', 'entity_1', 'entity_2'])
        self.assertTrue(repairs)


if __name__ == '__main__':
    unittest.main()
