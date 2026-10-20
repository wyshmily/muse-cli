import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('verify_source',Path(__file__).resolve().parents[1]/'tools/verify_source.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class SourceManifestTests(unittest.TestCase):
    def test_valid_and_modified(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'code.py').write_bytes(b'valid')
            (root/'SOURCE-MANIFEST.json').write_text(json.dumps({'schema_version':1,'sha256':{'code.py':hashlib.sha256(b'valid').hexdigest()}}))
            self.assertEqual(m.verify(root),1)
            (root/'code.py').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'SOURCE_MISMATCH'): m.verify(root)
    def test_escape(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'SOURCE-MANIFEST.json').write_text(json.dumps({'schema_version':1,'sha256':{'../secret':'a'*64}}))
            with self.assertRaisesRegex(ValueError,'INVALID_MANIFEST'): m.verify(root)
    def test_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'target').write_bytes(b'x'); (root/'link').symlink_to('target')
            (root/'SOURCE-MANIFEST.json').write_text(json.dumps({'schema_version':1,'sha256':{'link':hashlib.sha256(b'x').hexdigest()}}))
            with self.assertRaisesRegex(ValueError,'INVALID_SOURCE_PATH'): m.verify(root)
    def test_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for value in [None, [], {'schema_version':1,'sha256':{}}, {'schema_version':1,'sha256':{'x':'z'*64}}]:
                (root/'SOURCE-MANIFEST.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError): m.verify(root)
