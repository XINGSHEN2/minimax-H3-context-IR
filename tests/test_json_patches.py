import unittest
from backend.entity_patches import apply_patches

class PatchTests(unittest.TestCase):

    def setUp(self):
        self.doc = {'summary': 'old', 'shots': [{'id': 's1', 'description': 'one'}, {'id': 's2', 'description': 'two'}], 'a/b': {'~key': 1}}

    def test_local_change_leaves_original_and_other_shots_untouched(self):
        result = apply_patches(self.doc, [{'op': 'replace', 'path': '/shots/1/description', 'value': 'new'}])
        self.assertEqual(self.doc['shots'][1]['description'], 'two')
        self.assertEqual(result['shots'][0], self.doc['shots'][0])
        self.assertEqual(result['shots'][1], {'id': 's2', 'description': 'new'})

    def test_pointer_escaping(self):
        result = apply_patches(self.doc, [{'op': 'replace', 'path': '/a~1b/~0key', 'value': 2}])
        self.assertEqual(result['a/b']['~key'], 2)

    def test_failure_is_atomic(self):
        with self.assertRaises((KeyError, ValueError)):
            apply_patches(self.doc, [{'op': 'replace', 'path': '/summary', 'value': 'changed'}, {'op': 'replace', 'path': '/target/summary', 'value': 'bad'}])
        self.assertEqual(self.doc['summary'], 'old')

    def test_invalid_paths_rejected(self):
        for path in ['/shots/01/description', '/shots/99/description', '/bad~2key', '/']:
            with self.subTest(path=path), self.assertRaises((ValueError, IndexError, KeyError)):
                apply_patches(self.doc, [{'op': 'replace', 'path': path, 'value': 'bad'}])

    def test_add_remove(self):
        result = apply_patches(self.doc, [{'op': 'add', 'path': '/shots/-', 'value': {'id': 's3'}}, {'op': 'remove', 'path': '/shots/0'}])
        self.assertEqual([s['id'] for s in result['shots']], ['s2', 's3'])
if __name__ == '__main__':
    unittest.main()
