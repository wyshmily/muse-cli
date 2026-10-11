"""Synthetic state and API fixtures only. Never contacts Muse or an OS keyring."""
import contextlib
import http.cookiejar
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from muse_cli.native_auth import NativeLogin, LoginError
from muse_cli.login_state import SavedLogin, snapshot, restore, check_session
from muse_cli.secure_store import SecretStore
from muse_cli.safe_diagnostics import response_shape
from muse_cli.readonly import read, ReadError, classify
from muse_cli.gateway import GatewayError, AuthError

SECRET = 'SYNTHETIC_ONLY_NEVER_A_REAL_CREDENTIAL'


class Backend:
    def __init__(self): self.value = None
    def get_password(self, *args): return self.value
    def set_password(self, service, profile, value): self.value = value
    def delete_password(self, *args): self.value = None


class Cookies:
    def __init__(self): self.jar = http.cookiejar.CookieJar()
    def clear(self): self.jar.clear()
    def add(self, domain='.muse.ai', expires=None):
        self.jar.set_cookie(http.cookiejar.Cookie(0, 'hatch_sess', SECRET, None, False,
            domain, True, True, '/', True, True, expires, expires is None, None, None, {}, False))


class Response:
    def __init__(self, data, status=200): self.data, self.status_code = data, status
    def json(self): return self.data


class Http:
    def __init__(self, responses):
        self.responses, self.calls, self.cookies = list(responses), [], Cookies()
    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        value = self.responses.pop(0)
        if isinstance(value, BaseException): raise value
        if '/confirm-otp' in url: self.cookies.add()
        return value
    def close(self): pass


def flow(confirm=None, check=None):
    return Http([Response({}, 307), Response({'csrf_token': SECRET}, 201),
        Response({'flow': 'login', 'registration_state': 'otp_sent'}, 201),
        Response({} if confirm is None else confirm),
        Response({'access_token': SECRET} if check is None else check)])


class WorkflowTests(unittest.TestCase):
    def test_staged_login_and_check_never_verify_gateway(self):
        from muse_cli.native_login import main
        from muse_cli.native_auth import MemorySession
        http = flow()
        http.responses.append(Response({'access_token': SECRET}))
        class Store:
            value = None
            def lock(self): return contextlib.nullcontext()
            def load(self): return self.value
            def save(self, value): self.value = value
        store = Store()
        factory = lambda: NativeLogin(_http=http)
        output = io.StringIO()
        args = ['--store', 'plaintext-file', '--vault', '/synthetic/session.json']
        with patch('muse_cli.secure_store.configured_store', return_value=store), \
             patch('muse_cli.login_state.SavedLogin', side_effect=lambda s: SavedLogin(s, _factory=factory)), \
             patch('muse_cli.login_state.restore', side_effect=lambda value, **kw: restore(value, _http=http)), \
             patch('muse_cli.native_login.hidden_input', side_effect=['fixture@example.invalid', '000000']), \
             patch.object(MemorySession, 'verify_readonly', side_effect=AssertionError('GATEWAY_FORBIDDEN')), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(main(['start', *args]), 0)
            self.assertEqual(main(['confirm', *args]), 0, output.getvalue())
            self.assertEqual(main(['check', *args]), 0, output.getvalue())
        self.assertEqual(store.value['state'], 'authenticated')
        self.assertIn('Gateway not verified', output.getvalue())
        self.assertNotIn(SECRET, output.getvalue())
        self.assertFalse(any('/hatch/' in call[1] or 'metaaivm' in call[1] for call in http.calls))

    def fails(self, code, fn):
        with self.assertRaises((LoginError, ReadError)) as cm: fn()
        self.assertEqual(cm.exception.code, code)
        self.assertNotIn(SECRET, str(cm.exception))

    def test_observed_stateless_confirm_proves_auth_without_save(self):
        http = flow({'auth_meta_session': {'frl_access_token': SECRET}, 'redirect_to': '/'})
        login = NativeLogin(_http=http)
        login.send('synthetic@example.invalid')
        session = login.confirm('000000')
        self.assertIn('hatch_sess=', session._cookies)
        self.assertFalse(any('/save-account' in x[1] for x in http.calls))
        self.assertNotIn(SECRET, json.dumps(login.diagnostics))
        session.close()

    def test_stateless_200_not_success_without_auth(self):
        http = flow(check={})
        login = NativeLogin(_http=http)
        login.send('synthetic@example.invalid')
        self.fails('SESSION_INVALID', lambda: login.confirm('000000'))

    def test_unknown_state_and_checkpoint_block_followup(self):
        for data, code in [({'registration_state': SECRET}, 'UNKNOWN_AUTH_STATE'),
                           ({'checkpoint_url': 'https://example.invalid'}, 'CHECKPOINT_REQUIRED')]:
            login = NativeLogin(_http=flow(data), retain_pending=True)
            login.send('synthetic@example.invalid')
            self.fails(code, lambda: login.confirm('000000'))
            self.assertEqual(login.state, 'blocked')
            self.fails('INVALID_SEQUENCE', lambda: check_session(login))
            login.close()

    def test_rate_limit_status_without_enum(self):
        http = flow()
        http.responses[3] = Response({'private': SECRET}, 429)
        login = NativeLogin(_http=http)
        login.send('synthetic@example.invalid')
        self.fails('RATE_LIMITED', lambda: login.confirm('000000'))
        self.assertEqual(len(http.calls), 4)

    def test_structural_diagnostic_never_echoes_dynamic_keys_values(self):
        value = {SECRET: SECRET, 'access_token': SECRET, 'data': [{SECRET: SECRET}]}
        self.assertNotIn(SECRET, json.dumps(response_shape(value)))
        from muse_cli.safe_diagnostics import stored_diagnostics
        data = [{'http_status': 200, 'body': response_shape(value)}]
        self.assertEqual(stored_diagnostics(data), data)
        self.assertNotIn(SECRET, json.dumps(stored_diagnostics([{'body': {'type': SECRET, SECRET: SECRET}}])))

    def test_secure_store_rejects_corrupt_and_does_not_fallback(self):
        backend = Backend()
        store = SecretStore(_backend=backend)
        for raw in ['not-json'+SECRET, '[]', '{"version":2}', 'x'*262145]:
            backend.value = raw
            self.fails('STORE_CORRUPT', store.load)
        with patch('sys.platform', 'not-linux'):
            self.fails('STORE_UNAVAILABLE', SecretStore)

    def test_backend_failure_redacted(self):
        backend = Backend()
        backend.get_password = lambda *a: (_ for _ in ()).throw(RuntimeError(SECRET))
        self.fails('STORE_FAILED', SecretStore(_backend=backend).load)

    def test_restart_between_send_and_confirm(self):
        store = SecretStore(_backend=Backend())
        first = flow()
        SavedLogin(store, _factory=lambda: NativeLogin(_http=first)).start(lambda _: 'synthetic@example.invalid')
        self.assertEqual(store.load()['state'], 'otp_sent')
        self.assertNotIn('synthetic@example.invalid', store.backend.value)
        second = Http([Response({}), Response({'access_token': SECRET})])
        session = SavedLogin(store).resume(confirm=lambda _: '000000', _http=second)
        self.assertEqual(store.load()['state'], 'authenticated')
        self.assertEqual(len(second.calls), 2)
        session.close()
        third = Http([Response({'access_token': SECRET})])
        session = SavedLogin(store).resume(_http=third)
        self.assertEqual(len(third.calls), 1)
        session.close()

    def test_process_restart_state_is_loadable(self):
        login = NativeLogin(_http=flow())
        login.state = 'otp_sent'
        login.csrf = SECRET
        value = snapshot(login, time.time())
        # Only this synthetic fixture goes through a pipe; production CLI never
        # accepts credentials via argv or redirected stdin.
        code = 'import json,sys; from muse_cli.login_state import restore; x=restore(json.load(sys.stdin)); print(x.state); x.close()'
        result = subprocess.run([sys.executable, '-c', code], input=json.dumps(value),
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'otp_sent')
        self.assertNotIn(SECRET, result.stdout+result.stderr)

    def test_timeout_confirm_preserves_uncertain_state_no_resubmit(self):
        store = SecretStore(_backend=Backend())
        SavedLogin(store, _factory=lambda: NativeLogin(_http=flow())).start(lambda _: 'synthetic@example.invalid')
        http = Http([TimeoutError(SECRET)])
        self.fails('TIMEOUT', lambda: SavedLogin(store).resume(confirm=lambda _: '000000', _http=http))
        self.assertEqual(store.load()['state'], 'confirming')
        self.fails('INVALID_SEQUENCE', lambda: SavedLogin(store).resume(confirm=lambda _: '000000', _http=Http([])))
        self.assertEqual(len(http.calls), 1)

    def test_timeout_send_records_uncertainty_before_network(self):
        store = SecretStore(_backend=Backend())
        http = Http([TimeoutError(SECRET)])
        flow_obj = SavedLogin(store, _factory=lambda: NativeLogin(_http=http))
        self.fails('TIMEOUT', lambda: flow_obj.start(lambda _: 'synthetic@example.invalid'))
        self.assertEqual(store.load()['state'], 'sending')
        self.fails('ATTEMPT_EXISTS', lambda: flow_obj.start(lambda _: self.fail('must not prompt')))

    def test_store_failure_prevents_send(self):
        store = SecretStore(_backend=Backend())
        store.backend.set_password = lambda *a: (_ for _ in ()).throw(RuntimeError(SECRET))
        http = flow()
        self.fails('STORE_FAILED', lambda: SavedLogin(store, _factory=lambda:NativeLogin(_http=http)).start(lambda _: 'synthetic@example.invalid'))
        self.assertEqual(http.calls, [])

    def test_expired_attempt_never_reads_otp_or_sends(self):
        store = SecretStore(_backend=Backend())
        login = NativeLogin(_http=flow())
        login.state = 'otp_sent'
        login.csrf = SECRET
        store.save(snapshot(login, time.time()-601))
        http = Http([])
        self.fails('ATTEMPT_EXPIRED', lambda:SavedLogin(store).resume(confirm=lambda _:self.fail('prompt'), _http=http))
        self.assertEqual(http.calls, [])

    def test_waiting_session_does_not_lose_checkpoint(self):
        store = SecretStore(_backend=Backend())
        login = NativeLogin(_http=flow())
        login.state = 'confirming'
        store.save(snapshot(login, time.time()))
        for _ in range(3):
            http = Http([Response({})])
            self.fails('WAITING_SESSION', lambda:SavedLogin(store).resume(_http=http))
            self.assertEqual(len(http.calls), 1)
            self.assertEqual(store.load()['state'], 'confirming')

    def test_cancel_after_send_survives(self):
        store = SecretStore(_backend=Backend())
        SavedLogin(store, _factory=lambda:NativeLogin(_http=flow())).start(lambda _: 'synthetic@example.invalid')
        def cancel(_): raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            SavedLogin(store).resume(confirm=cancel, _http=Http([]))
        self.assertEqual(store.load()['state'], 'otp_sent')

    def test_corrupt_cookie_domain_and_header_rejected_before_http(self):
        login = NativeLogin(_http=flow())
        login.http.cookies.add()
        value = snapshot(login, time.time())
        for field, bad in [('domain','attacker.invalid'), ('value','x\r\nInjected: y')]:
            other = json.loads(json.dumps(value))
            other['cookies'][0][field] = bad
            http = Http([])
            self.fails('STORE_CORRUPT', lambda:restore(other, _http=http))
            self.assertEqual(http.calls, [])

    def test_expired_credentials_not_returned(self):
        http = Http([Response({'access_token': SECRET})])
        http.cookies.add(expires=int(time.time())-10)
        self.fails('WAITING_SESSION', lambda:check_session(NativeLogin(_http=http)))

    def test_read_route_mapping_and_secret_redaction(self):
        class Gateway:
            def __init__(self): self.calls=[]
            def call_json(self, method, **kw):
                self.calls.append((method,kw))
                return {'access_token':SECRET, 'url':'https://example.invalid/file?token='+SECRET}
        gw=Gateway()
        for command in ('identity','sessions','session','history','spaces'):
            result=read(gw,command,identifier='fixture-id')
            self.assertNotIn(SECRET,json.dumps(result))
        self.assertEqual(gw.calls[2],('sessions.get',{'path_params':{'id':'fixture-id'}}))
        self.assertEqual(gw.calls[3],('chat.history',{'query':{'session_id':'fixture-id','limit':20}}))
        self.fails('MEDIA_SCHEMA_UNVERIFIED',lambda:read(gw,'media'))
        self.fails('UNSUPPORTED_READ',lambda:read(gw,'send'))

    def test_read_error_classification_sanitized(self):
        for error,code in [(AuthError(SECRET),'AUTH_INVALID'),(TimeoutError(SECRET),'TIMEOUT'),
                (GatewayError(401,SECRET),'AUTH_INVALID'),(GatewayError(403,SECRET),'FORBIDDEN'),
                (GatewayError(404,SECRET),'NOT_FOUND'),(GatewayError(429,SECRET),'RATE_LIMITED'),
                (GatewayError(500,SECRET),'API_FAILED'),(GatewayError(-1,SECRET),'GATEWAY_UNAVAILABLE')]:
            self.assertEqual(classify(error),code)
            if isinstance(error,GatewayError): self.assertNotIn(SECRET,str(error))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux flock semantics')
    def test_runtime_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'XDG_RUNTIME_DIR':root}):
            os.chmod(root,0o700)
            store=SecretStore(_backend=Backend())
            with store.lock():
                self.fails('BUSY',lambda:store.lock().__enter__())
            with store.lock(): pass

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux permissions')
    def test_runtime_lock_rejects_unprotected_directory(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'XDG_RUNTIME_DIR':root}):
            os.chmod(root,0o755)
            self.fails('STORE_UNAVAILABLE',lambda:SecretStore(_backend=Backend()).lock().__enter__())


if __name__ == '__main__': unittest.main()
