"""Offline schema fixtures only: synthetic IDs/bodies, no credentials/network."""
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('probe',Path(__file__).resolve().parents[1] / 'tools' / 'probe_local.py')
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class SchemaTests(unittest.TestCase):
    def test_session_contract_uses_session_id(self):
        self.assertEqual(probe.sessions_shape({'sessions':[{'session_id':'synthetic-session-1'}]}),(1,'synthetic-session-1',None))
    def test_old_harness_id_is_not_silently_accepted(self):
        self.assertEqual(probe.sessions_shape({'sessions':[{'id':'synthetic-old-field'}]}),(1,None,'SESSION_ID_SHAPE_UNRECOGNIZED'))
    def test_missing_or_wrong_list_reports_exact_shape_error(self):
        for obj in (None,[],{}, {'sessions':{}}, {'items':[]}):
            self.assertEqual(probe.sessions_shape(obj),(None,None,'SESSION_LIST_SHAPE_UNRECOGNIZED'))
    def test_empty_list_is_not_schema_failure(self):
        self.assertEqual(probe.sessions_shape({'sessions':[]}),(0,None,'NO_SESSIONS'))
    def test_invalid_id_never_sent(self):
        for v in ('', '../x', 'bad\nvalue', None, 42):
            self.assertEqual(probe.sessions_shape({'sessions':[{'session_id':v}]})[2],'SESSION_ID_SHAPE_UNRECOGNIZED')
    def test_valid_session_after_malformed_row(self):
        self.assertEqual(probe.sessions_shape({'sessions':[None,{}, {'session_id':'synthetic-2'}]}),(3,'synthetic-2',None))
    def test_history_uses_chat_events_without_body_output(self):
        self.assertEqual(probe.history_shape({'chat_events':[{'payload':{'content':'synthetic fixture'}}]}),(1,None))
    def test_history_empty_valid(self):
        self.assertEqual(probe.history_shape({'chat_events':[]}),(0,None))
    def test_history_unknown_shape(self):
        for obj in ({'messages':[]},{'chat_events':None},None):
            self.assertEqual(probe.history_shape(obj),(None,'HISTORY_RESPONSE_SHAPE_UNRECOGNIZED'))
    def test_untrusted_exception_code_never_leaks(self):
        from types import SimpleNamespace
        exc=SimpleNamespace(code='SYNTHETIC_SECRET_DO_NOT_PRINT')
        for stage in ('decrypt','identity','history'):
            result=probe.safe_error_code(exc,stage,lambda e:e.code)
            self.assertNotIn('SYNTHETIC_SECRET',result)
            self.assertIn(result,('LOCAL_ENVELOPE_FAILED','LOCAL_PROBE_FAILED'))
    def test_untrusted_classifier_result_never_leaks(self):
        result=probe.safe_error_code(Exception(),'identity',lambda e:'SYNTHETIC_SECRET')
        self.assertEqual(result,'LOCAL_PROBE_FAILED')
    def test_approved_error_code_survives(self):
        from types import SimpleNamespace
        self.assertEqual(probe.safe_error_code(SimpleNamespace(code='FORBIDDEN'),'identity',lambda e:'TRANSPORT_FAILED'),'FORBIDDEN')
    def test_cleanup_refuses_arbitrary_root_in_preflight(self):
        for p in (Path('/tmp'),Path('/workspace/shared'),Path('muse-live-relative')):
            with self.assertRaises(ValueError): probe.validate_envelope_dir(p)

class CleanupTests(unittest.TestCase):
    def make_envelope(self):
        import tempfile, json, base64, os
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        root=Path(tempfile.mkdtemp(prefix='muse-live-fixture-',dir='/tmp'))
        receiver=X25519PrivateKey.generate(); sender=X25519PrivateKey.generate()
        aad=b'synthetic-fixture'; nonce=os.urandom(12)
        key=HKDF(algorithm=hashes.SHA256(),length=32,salt=None,info=aad).derive(sender.exchange(receiver.public_key()))
        sealed={'ephemeral_public':sender.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(),'nonce':nonce.hex(),
                'ciphertext':base64.b64encode(AESGCM(key).encrypt(nonce,b'{"synthetic": true}',aad)).decode()}
        (root/'ephemeral.key').write_bytes(receiver.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
        (root/'sealed.json').write_text(json.dumps(sealed))
        for p in root.iterdir(): p.chmod(0o600)
        return root,aad
    def execute_mocked(self, rejected=False):
        from unittest.mock import patch, MagicMock
        from muse_cli.readonly import ReadError
        root,aad=self.make_envelope()
        login=MagicMock(); session=MagicMock(); session._cookies='SYNTHETIC-NOT-A-CREDENTIAL'
        gateway=MagicMock()
        results=[{'ok':True},{'sessions':[{'session_id':'synthetic-session'}]}, {'chat_events':[{'synthetic':True}]}]
        try:
            with patch('muse_cli.login_state.restore',return_value=login), patch('muse_cli.login_state.check_session',return_value=session), patch('muse_cli.gateway.Gateway',return_value=gateway), patch('muse_cli.readonly.read',side_effect=ReadError('FORBIDDEN') if rejected else results) as mocked:
                report=probe.probe(root,aad)
                self.assertEqual(mocked.call_count,1 if rejected else 3)
                if not rejected:
                    self.assertEqual(mocked.call_args.kwargs,{'identifier':'synthetic-session','limit':2})
            self.assertFalse(root.exists())
            self.assertTrue(report['temporary_directory_removed'])
            for obj in (login,session,gateway): obj.close.assert_called_once()
            self.assertNotIn('synthetic-session',str(report))
            return report
        finally:
            if root.exists():
                import shutil
                shutil.rmtree(root)
    def test_success_closes_and_removes_envelope(self):
        report=self.execute_mocked()
        self.assertEqual(report['result'],'completed')
        self.assertTrue(report['identity_read'])
        self.assertTrue(report['identity_response_valid'])
        self.assertNotIn('identity_verified',report)
        self.assertEqual(report['history_entry_count'],1)
    def test_rejection_closes_and_removes_without_retry(self):
        report=self.execute_mocked(True)
        self.assertEqual(report['result'],'stopped')
        self.assertEqual(report['error_code'],'FORBIDDEN')

if __name__ == '__main__': unittest.main()
