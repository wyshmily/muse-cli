"""Credential-free bootstrap argument/overwrite regression checks."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'bootstrap_local.py'

@unittest.skipUnless(sys.version_info >= (3, 12) and sys.platform.startswith('linux'), 'Linux Python 3.12+ bootstrap')
class BootstrapArguments(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)

    def test_help_is_offline(self):
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('doctor', result.stdout)

    def test_rejects_nonimmutable_ref(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke('bootstrap', '--source', directory, '--commit', 'main', '--runtime', str(Path(directory) / 'new'))
            self.assertEqual(result.returncode, 2)
            self.assertFalse((Path(directory) / 'new').exists())

    def test_does_not_replace_existing_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'keep.txt'
            marker.write_text('preserve')
            result = self.invoke('bootstrap', '--source', directory, '--commit', 'a' * 40, '--runtime', directory)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(marker.read_text(), 'preserve')
