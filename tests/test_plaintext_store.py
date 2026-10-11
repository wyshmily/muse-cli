import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from muse_cli.native_auth import LoginError
from muse_cli.secure_store import configured_store


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux file permissions')
class PlaintextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'session.json'
        self.value = {'version': 1, 'state': 'confirming', 'private': 'SYNTHETIC_SECRET'}

    def make(self, access=True):
        return configured_store('plaintext-file', 'default', vault=str(self.path), allow_secret_access=access)

    def save(self):
        store = self.make()
        with store.lock(): store.save(self.value)

    def test_metadata_preflight_and_explicit_selection(self):
        store = self.make(False)
        self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(LoginError): store.load()
        with self.assertRaises(LoginError): configured_store('secretservice','default',vault=str(self.path))

    def test_restart_process_and_permissions(self):
        self.save()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        code = "from muse_cli.secure_store import configured_store; import sys; s=configured_store('plaintext-file','default',vault=sys.argv[1],allow_secret_access=True)\nwith s.lock():\n assert s.load()['private']=='SYNTHETIC_SECRET'\nprint('restored')"
        result = subprocess.run([sys.executable, '-c', code, str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'restored\n')

    def test_corruption_preserved(self):
        self.save()
        self.path.write_text('broken SYNTHETIC_SECRET')
        store = self.make()
        with store.lock(), self.assertRaises(LoginError) as error:
            store.save(self.value)
        self.assertEqual(error.exception.code, 'STORE_CORRUPT')
        self.assertNotIn('SYNTHETIC_SECRET', str(error.exception))
        self.assertEqual(self.path.read_text(), 'broken SYNTHETIC_SECRET')

    def test_replace_failure_preserves_original_and_cleans_temp(self):
        self.save()
        before = self.path.read_bytes()
        store = self.make()
        with store.lock(), patch('muse_cli.plaintext_store.os.replace', side_effect=OSError('SYNTHETIC_SECRET')):
            with self.assertRaises(LoginError) as error: store.save({'version':1})
        self.assertNotIn('SYNTHETIC_SECRET', str(error.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob('.muse-*.tmp')))

    def test_file_and_directory_modes_rejected_not_repaired(self):
        self.save()
        os.chmod(self.path, 0o644)
        with self.assertRaises(LoginError): self.make()
        self.assertEqual(self.path.stat().st_mode & 0o777,0o644)
        os.chmod(self.path,0o600)
        os.chmod(self.root,0o755)
        with self.assertRaises(LoginError): self.make()

    def test_links_rejected(self):
        self.save()
        target=self.root/'other'
        os.link(self.path,target)
        with self.assertRaises(LoginError): self.make()
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaises(LoginError): self.make()

    def test_wrong_owner_rejected(self):
        self.save()
        with patch('muse_cli.encrypted_store.os.getuid', return_value=os.getuid()+1):
            with self.assertRaises(LoginError): self.make()

    def test_no_secret_repr_or_status(self):
        self.save()
        self.assertNotIn('SYNTHETIC_SECRET',repr(self.make()))
        result=subprocess.run([sys.executable,'-m','muse_cli.native_login','status','--store','plaintext-file','--vault',str(self.path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'confirming')
        self.assertNotIn('SYNTHETIC_SECRET',result.stdout+result.stderr)
