"""Synthetic offline recovery-plan security regressions; never use a real login."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/recovery_plan.py'
spec = importlib.util.spec_from_file_location('recovery_plan', TOOL)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
FIXTURE = json.loads((ROOT / 'tests/fixtures/muse-recovery-plan-v1.json').read_text())


class RecoveryPlans(unittest.TestCase):
    def setUp(self):
        self.plan = copy.deepcopy(FIXTURE['plan'])
        self.binding = {k: copy.deepcopy(self.plan[k]) for k in m.BINDING_FIELDS}
        self.now = self.plan['created_at'] + 1

    def check(self, plan=None, binding=None, now=None):
        return m.validate(self.plan if plan is None else plan,
                          expected_binding=self.binding if binding is None else binding,
                          now=self.now if now is None else now)

    def test_cross_language_known_fixture(self):
        self.assertEqual(m.canonical_bytes(self.plan).decode('ascii'), FIXTURE['canonical'])
        self.assertEqual(m.digest(self.plan), '7914362042ffc603932d5496860800389cb42a3f68fc25d7ca9babc51ef7ac9b')
        self.assertEqual(self.check(), self.plan)

    def test_new_request_not_authorization(self):
        plan = m.create(self.binding, now=self.now)
        self.assertNotEqual(plan['request_id'], self.plan['request_id'])
        self.assertNotIn('approved', plan)
        self.check(plan)

    def test_unknown_and_secret_fields_rejected(self):
        for key in ('approved', 'authorization', 'callback_url', 'credentials', 'token', 'challenge'):
            with self.subTest(key=key):
                plan = copy.deepcopy(self.plan); plan[key] = True
                with self.assertRaisesRegex(ValueError, 'INVALID_PLAN_FIELDS'): self.check(plan)
        plan = copy.deepcopy(self.plan); plan['scope']['callback_url'] = 'https://muse.ai/'
        with self.assertRaises(ValueError): self.check(plan)

    def test_every_binding_change_rejected_even_redigested(self):
        for key in m.BINDING_FIELDS:
            with self.subTest(key=key):
                plan = copy.deepcopy(self.plan)
                if key == 'scope': plan[key]['actions'] = ['auth_check']
                elif key == 'recipient_public_key_sha256': plan[key] = 'b' * 64
                elif key == 'cli_commit': plan[key] = 'b' * 40
                else: plan[key] += '-changed'
                plan['request_digest'] = m.digest(plan)
                with self.assertRaisesRegex(ValueError, 'BINDING_MISMATCH'): self.check(plan)

    def test_expiry_and_future_and_ttl(self):
        with self.assertRaisesRegex(ValueError, 'EXPIRED'): self.check(now=self.plan['expires_at'])
        with self.assertRaisesRegex(ValueError, 'NOT_YET_VALID'): self.check(now=self.plan['created_at'] - 1)
        for ttl in (0, -1, 601, True, 1.5):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError): m.create(self.binding, ttl=ttl, now=self.now)

    def test_scope_rejects_noncanonical_or_expanded_values(self):
        for field, value in [('actions', []), ('actions', ['auth_check', 'auth_check']),
                             ('actions', ['read_sessions', 'auth_check']), ('actions', ['resume_task']),
                             ('hosts', ['muse.ai.evil']), ('hosts', ['https://muse.ai']),
                             ('hosts', ['muse.ai', 'hatch.metaaivm.com']),
                             ('account_ref', 'owner@example.com'), ('vault_ref', 'a/secret'),
                             ('account_ref', '中文'), ('vault_ref', 'a\n')]:
            with self.subTest(field=field, value=value):
                binding = copy.deepcopy(self.binding); binding['scope'][field] = value
                with self.assertRaises(ValueError): m.create(binding, now=self.now)

    def test_invalid_uuid_numbers_digest(self):
        for field, value in [('schema_version', True), ('created_at', True), ('expires_at', 2 ** 53),
                             ('created_at', 1.0), ('request_id', '123e4567-e89b-12d3-a456-426614174000'),
                             ('request_id', self.plan['request_id'].upper()), ('request_digest', 'b' * 64)]:
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan); plan[field] = value
                with self.assertRaises(ValueError): self.check(plan)

    def test_duplicate_json_and_oversize_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'plan.json'
            for data in ('{"scope":{},"scope":{}}', '{"n":NaN}', ' ' * 16385):
                path.write_text(data)
                with self.assertRaises(ValueError): m.load_plan(path)

    def test_metadata_only_missing_present_unsafe(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'synthetic-session'
            self.assertEqual(m.credential_status(path), 'needs_recovery')
            path.write_text('synthetic-never-read'); path.chmod(0o600)
            with mock.patch('builtins.open', side_effect=AssertionError('Must not read credentials')), \
                 mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('Must not read credentials')):
                self.assertEqual(m.credential_status(path), 'present_unverified')
            path.chmod(0o644)
            self.assertEqual(m.credential_status(path), 'blocked_unsafe_metadata')
            path.chmod(0o600)
            link = Path(root) / 'link'; link.symlink_to(path)
            self.assertEqual(m.credential_status(link), 'blocked_unsafe_metadata')
            parentlink = Path(root) / 'parentlink'; parentlink.symlink_to(root)
            self.assertEqual(m.credential_status(parentlink / path.name), 'blocked_unsafe_metadata')
            self.assertEqual(m.credential_status(parentlink / '..' / path.name), 'blocked_unsafe_metadata')
            self.assertEqual(m.credential_status(Path(root) / '..' / 'missing'), 'blocked_unsafe_metadata')
            hardlink = Path(root) / 'hardlink'; os.link(path, hardlink)
            self.assertEqual(m.credential_status(path), 'blocked_unsafe_metadata')

    def args(self):
        args = []
        for key in sorted(m.BINDING_FIELDS - {'scope'}):
            args += ['--' + key.replace('_', '-'), self.binding[key]]
        for key, value in self.binding['scope'].items():
            args += ['--' + key.replace('_', '-')]
            args += value if isinstance(value, list) else [value]
        return args

    def test_cli_create_validate_and_no_credential_echo(self):
        with tempfile.TemporaryDirectory() as root:
            session = Path(root) / 'missing-session'
            run = subprocess.run([sys.executable, str(TOOL), 'create', '--credential-file', str(session), *self.args()], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('needs_recovery', run.stderr)
            session.write_text('synthetic-unverified'); session.chmod(0o600)
            present = subprocess.run([sys.executable, str(TOOL), 'create', '--credential-file', str(session), *self.args()], capture_output=True, text=True)
            self.assertEqual(present.returncode, 0, present.stderr)
            self.assertIn('draft_pending_session_verification', present.stderr)
            self.assertNotIn('needs_recovery', present.stderr)
            self.assertNotIn('synthetic-unverified', present.stderr + present.stdout)
            session.chmod(0o644)
            blocked = subprocess.run([sys.executable, str(TOOL), 'create', '--credential-file', str(session), *self.args()], capture_output=True, text=True)
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(blocked.stdout, '')
            plan = Path(root) / 'plan.json'; plan.write_text(run.stdout)
            result = subprocess.run([sys.executable, str(TOOL), 'validate', '--plan', str(plan), *self.args()], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)['authorization_granted'])
            result = subprocess.run([sys.executable, str(TOOL), 'create', '--credentials', 'never-echo-me'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('never-echo-me', result.stderr + result.stdout)


if __name__ == '__main__':
    unittest.main()
