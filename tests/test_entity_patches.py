import unittest
from backend.entity_patches import addressable, restore_collections, apply_patches

class EntityTests(unittest.TestCase):

    def setUp(self):
        self.doc = {'shots': [{'id': 's1', 'description': 'one'}, {'id': 's2', 'description': 'two'}, {'id': 's3', 'description': 'three'}, {'id': 's4', 'description': 'four'}]}

    def test_roundtrip(self):
        (obj, keys) = addressable(self.doc)
        self.assertEqual(restore_collections(obj, keys), self.doc)

    def test_stable_id_only_changes_intended_shot(self):
        (obj, keys) = addressable(self.doc)
        obj = apply_patches(obj, [{'op': 'replace', 'path': '/shots/s3/description', 'value': 'fixed'}])
        actual = restore_collections(obj, keys)
        self.assertEqual(actual['shots'][2]['description'], 'fixed')
        self.assertEqual(actual['shots'][3], self.doc['shots'][3])
        self.assertEqual(self.doc['shots'][2]['description'], 'three')

    def test_old_off_by_one_path_rejected(self):
        (obj, keys) = addressable(self.doc)
        with self.assertRaises(KeyError):
            apply_patches(obj, [{'op': 'replace', 'path': '/shots/3/description', 'value': 'wrong'}])

    def test_id_mutation_rejected(self):
        (obj, keys) = addressable(self.doc)
        obj['shots']['s3']['id'] = 's4'
        with self.assertRaises(ValueError):
            restore_collections(obj, keys)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            addressable({'events': [{'id': 'e1'}, {'id': 'e1'}]})
if __name__ == '__main__':
    unittest.main()
