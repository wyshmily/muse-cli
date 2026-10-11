"""Installed command-module smoke tests; isolated environment, no accounts."""
import os
import subprocess
import sys
import unittest


class Entrypoints(unittest.TestCase):
    def run_cli(self, module, *args):
        env = dict(os.environ)
        for key in ('DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'WAYLAND_DISPLAY',
                    'MUSE_COOKIES_FILE', 'MUSE_VM_ID', 'MUSE_NODE_ID'):
            env.pop(key, None)
        # A nonexistent bus ensures no auto-discovery of an existing keyring.
        env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/nonexistent-dotlink-test-bus'
        return subprocess.run([sys.executable, '-m', module, *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, env=env, timeout=20)

    def test_login_help_has_real_stages(self):
        p = self.run_cli('muse_cli.native_login','--help')
        self.assertEqual(p.returncode,0)
        for word in ('session','start','confirm','check','preflight','secretservice'):
            self.assertIn(word,p.stdout)

    def test_read_help(self):
        p=self.run_cli('muse_cli.readonly','--help')
        self.assertEqual(p.returncode,0)
        for word in ('sessions','session','history','spaces','media'):
            self.assertIn(word,p.stdout)

    def test_no_tty_fails_before_account_or_network(self):
        p=self.run_cli('muse_cli.native_login')
        self.assertEqual(p.returncode,2)
        self.assertIn('INTERACTIVE_TTY_REQUIRED',p.stderr)

    def test_no_secure_store_fails_preflight(self):
        p=self.run_cli('muse_cli.native_login','preflight','--store','secretservice')
        self.assertEqual(p.returncode,2)
        self.assertIn('STORE_UNAVAILABLE',p.stderr)

    def test_arguments_do_not_echo(self):
        for module in ('muse_cli.native_login','muse_cli.readonly'):
            p=self.run_cli(module,'--password','SYNTHETIC_SECRET')
            self.assertEqual(p.returncode,2)
            self.assertNotIn('SYNTHETIC_SECRET',p.stdout+p.stderr)

    def test_media_schema_failure_before_credential_read(self):
        p=self.run_cli('muse_cli.readonly','media')
        self.assertEqual(p.returncode,2)
        self.assertIn('MEDIA_SCHEMA_UNVERIFIED',p.stderr)

    def test_read_without_store_never_uses_legacy_cookie_files(self):
        p=self.run_cli('muse_cli.readonly','sessions')
        self.assertEqual(p.returncode,2)
        self.assertIn('STORE_UNAVAILABLE',p.stderr)

    def test_wait_never_applies_to_otp_mutations(self):
        for action in ('start','confirm'):
            p=self.run_cli('muse_cli.native_login',action,'--store','secretservice','--wait','120')
            self.assertEqual(p.returncode,2)
            self.assertIn('INVALID_ARGUMENTS',p.stderr)


if __name__ == '__main__': unittest.main()
