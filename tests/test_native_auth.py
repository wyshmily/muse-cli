"""Synthetic fixtures only; socket/DNS and production transport are forbidden."""
import contextlib
import io
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from muse_cli.native_auth import LoginError, MemorySession, NativeLogin, _Contract
from muse_cli.native_login import hidden_input, main, run_interactive

# NOT platform enum claims. These labels exist only in offline fixtures.
C = _Contract('__test_existing__', '__test_sent__', '__test_authenticated__',
              'required-existing-login', 'synthetic fixture only')
SENT = {'flow': C.send_flow, 'registration_state': C.send_state}
DONE = {'registration_state': C.confirm_state}
SECRET = 'SYNTHETIC_SECRET_NEVER_LOG'


class Response:
    def __init__(self, data=None, status=200):
        self.data, self.status_code = {} if data is None else data, status
    def json(self):
        if isinstance(self.data, BaseException): raise self.data
        return self.data


class Cookies:
    def __init__(self):
        self.jar = [SimpleNamespace(name='hatch_sess', value=SECRET, domain='.muse.ai', path='/'),
                    SimpleNamespace(name='other', value='UNRELATED', domain='other.invalid')]
    def clear(self): self.jar.clear()


class Http:
    def __init__(self):
        self.responses = [Response(), Response({'csrf_token': SECRET}), Response(SENT),
                          Response(DONE), Response(), Response({'access_token': SECRET})]
        self.calls, self.cookies, self.closed, self.hook = [], Cookies(), False, None
    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.hook: self.hook()
        value = self.responses.pop(0)
        if isinstance(value, BaseException): raise value
        return value
    def close(self): self.closed = True


class Gateway:
    def __init__(self, cookies): self.cookies, self.calls, self.closed = cookies, [], False
    def call_json(self, method):
        self.calls.append(method)
        return {'private_fixture': SECRET}
    def close(self): self.closed = True


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guards = [patch.object(socket, n, side_effect=AssertionError('NETWORK_FORBIDDEN'))
                      for n in ('socket', 'create_connection', 'getaddrinfo')]
        cls.guards.append(patch('muse_cli.native_auth._http_session', side_effect=AssertionError('REAL_HTTP_FORBIDDEN')))
        for p in cls.guards: p.start()
    @classmethod
    def tearDownClass(cls):
        for p in cls.guards: p.stop()
    def make(self):
        http = Http()
        return NativeLogin(_http=http, _contract=C), http
    def fails(self, code, fn):
        with self.assertRaises(LoginError) as caught: fn()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(SECRET, str(caught.exception))

    def test_production_contract_uses_observed_send_and_auth_check(self):
        from muse_cli.native_auth import verified_contract
        c = verified_contract()
        self.assertEqual((c.send_flow, c.send_state, c.confirm_state, c.save_account),
                         ('login', 'otp_sent', 'auth-check', 'omit'))

    def test_fixture_requires_injected_transport(self):
        self.fails('CONTRACT_UNVERIFIED', lambda: NativeLogin(_contract=C))

    def test_normal_memory_handoff(self):
        login, http = self.make()
        login.send('fixture@example.invalid')
        session = login.confirm('000000')
        self.assertTrue(http.closed)
        self.assertFalse(http.cookies.jar)
        self.assertIsNone(login.csrf)
        self.assertEqual([x[1].split('muse.ai')[1] for x in http.calls],
            ['/', '/api/auth/native/restart', '/api/auth/native/send-otp',
             '/api/auth/native/confirm-otp', '/api/auth/save-account', '/api/auth/check'])
        gateways = []
        def factory(cookies):
            gateways.append(Gateway(cookies))
            return gateways[-1]
        self.assertEqual(session.verify_readonly(_gateway_factory=factory),
                         {'authenticated': True, 'gateway_verified': True})
        self.assertEqual(gateways[0].cookies, 'hatch_sess=' + SECRET)
        self.assertEqual(gateways[0].calls, ['identity'])
        self.assertTrue(gateways[0].closed)
        self.assertIsNone(session._cookies)

    def test_verified_omit_contract(self):
        http = Http()
        http.responses.pop(4)
        contract = _Contract(C.send_flow, C.send_state, C.confirm_state, 'omit', 'synthetic')
        login = NativeLogin(_http=http, _contract=contract)
        login.send('fixture@example.invalid')
        login.confirm('000000').close()
        self.assertFalse(any('/save-account' in x[1] for x in http.calls))

    def test_unknown_missing_and_malformed_states(self):
        for stage, index in [('send', 2), ('confirm', 3)]:
            for data in ({}, {'registration_state': None}, {'registration_state': SECRET},
                         {'registration_state': []}):
                with self.subTest(stage=stage, shape=list(data)):
                    login, http = self.make()
                    http.responses[index] = Response(data)
                    if stage == 'confirm': login.send('fixture@example.invalid')
                    self.fails('UNKNOWN_AUTH_STATE', lambda: getattr(login, stage)('000000'))
                    self.assertEqual(len(http.calls), index + 1)
                    self.assertTrue(http.closed)

    def test_unknown_missing_and_register_flow(self):
        for flow, code in [('register','REGISTRATION_NOT_ALLOWED'), ({'type':'register'},'REGISTRATION_NOT_ALLOWED'),
                           (None,'UNKNOWN_AUTH_STATE'), (SECRET,'UNKNOWN_AUTH_STATE')]:
            login, http = self.make()
            http.responses[2] = Response({**SENT, 'flow': flow})
            self.fails(code, lambda: login.send('fixture@example.invalid'))
        login, http = self.make()
        http.responses[3] = Response({**DONE, 'flow': SECRET})
        login.send('fixture@example.invalid')
        self.fails('UNKNOWN_AUTH_STATE', lambda: login.confirm('000000'))
        self.assertEqual(len(http.calls), 4)

    def test_known_branches_both_stages(self):
        branches = {'register':'REGISTRATION_NOT_ALLOWED', 'completion_required':'COMPLETION_REQUIRED',
                    'password_required':'PASSWORD_REQUIRED', 'two_factor_required':'TWO_FACTOR_REQUIRED',
                    'account_selection_required':'ACCOUNT_SELECTION_REQUIRED', 'ntp_upsell':'ACCOUNT_CONFIRMATION_REQUIRED'}
        for state, code in branches.items():
            for stage, index in [('send',2), ('confirm',3)]:
                with self.subTest(state=state, stage=stage):
                    login, http = self.make()
                    http.responses[index] = Response({'registration_state':state})
                    if stage == 'confirm': login.send('fixture@example.invalid')
                    self.fails(code, lambda: getattr(login, stage)('000000'))
                    self.assertTrue(http.closed)
                    self.assertFalse(any('/save-account' in x[1] for x in http.calls))

    def test_otp_error_no_retry(self):
        for kind, code in [('invalidOtp','INVALID_OTP'), ('expiredOtp','EXPIRED_OTP'),
                           ('tooManyAttempts','RATE_LIMITED'), ('regionNotSupported','REGION_UNSUPPORTED')]:
            login, http = self.make()
            http.responses[3] = Response({'type':kind, 'private':SECRET}, 400)
            login.send('fixture@example.invalid')
            self.fails(code, lambda: login.confirm('000000'))
            self.fails('INVALID_SEQUENCE', lambda: login.confirm('000000'))
            self.assertEqual(len(http.calls), 4)

    def test_timeout_and_transport_errors_redacted(self):
        curl_timeout = RuntimeError(SECRET)
        curl_timeout.code = 28
        for error, code in [(TimeoutError(SECRET),'TIMEOUT'), (curl_timeout,'TIMEOUT'),
                            (RuntimeError(SECRET),'NETWORK_FAILED')]:
            login, http = self.make()
            http.responses[0] = error
            self.fails(code, lambda: login.send('fixture@example.invalid'))
            self.assertEqual(len(http.calls), 1)
            self.assertTrue(http.closed)

    def test_timeout_after_confirm_never_save(self):
        login, http = self.make()
        http.responses[3] = TimeoutError(SECRET)
        login.send('fixture@example.invalid')
        self.fails('TIMEOUT', lambda: login.confirm('000000'))
        self.assertEqual(len(http.calls), 4)

    def test_redirects_disabled_and_errors_sanitized(self):
        login, http = self.make()
        http.responses[0] = Response({'type':SECRET}, 302)
        login.send('fixture@example.invalid')
        self.assertFalse(http.calls[0][2]['allow_redirects'])
        self.assertEqual(http.calls[0][2]['timeout'], 25)

    def test_invalid_response_or_csrf(self):
        for value in (ValueError(SECRET), [], 'private', {}):
            login, http = self.make()
            http.responses[1] = Response(value)
            self.fails('INVALID_RESPONSE', lambda: login.send('fixture@example.invalid'))
            self.assertTrue(http.closed)

    def test_missing_session_and_token(self):
        for what in ('cookie','token'):
            login, http = self.make()
            if what == 'cookie': http.cookies.clear()
            else: http.responses[5] = Response({})
            login.send('fixture@example.invalid')
            self.fails('SESSION_INVALID', lambda: login.confirm('000000'))
            self.assertTrue(http.closed)

    def test_cancel_before_during_and_after_send(self):
        for when, expected_calls in [('before',0), ('during',1), ('after',3)]:
            login, http = self.make()
            if when == 'before': login.cancel()
            elif when == 'during': http.hook = login.cancel
            else:
                login.send('fixture@example.invalid')
                login.cancel()
            fn = (lambda: login.confirm('000000')) if when == 'after' else (lambda: login.send('fixture@example.invalid'))
            self.fails('CANCELLED', fn)
            self.assertEqual(len(http.calls), expected_calls)
            self.assertTrue(http.closed)

    def test_request_interruption(self):
        login, http = self.make()
        http.responses[0] = KeyboardInterrupt()
        self.fails('CANCELLED', lambda: login.send('fixture@example.invalid'))
        self.assertTrue(http.closed)

    def test_interactive_interrupt_eof_cleanup(self):
        for error in (KeyboardInterrupt(), EOFError()):
            for stage in (0,1):
                login, http = self.make()
                values = iter(['fixture@example.invalid'] if stage else [])
                def read(_):
                    try: return next(values)
                    except StopIteration: raise error
                self.assertEqual(run_interactive(_factory=lambda:login, _read=read, output=io.StringIO()), 130)
                self.assertTrue(http.closed)
                self.assertEqual(len(http.calls), stage*3)

    def test_interactive_success_no_file_access_or_logs(self):
        login, http = self.make()
        values = iter(['fixture@example.invalid','000000'])
        output = io.StringIO()
        with patch('builtins.open', side_effect=AssertionError('FILE_ACCESS')):
            result = run_interactive(_factory=lambda:login, _read=lambda _:next(values),
                _verify=lambda s:s.verify_readonly(_gateway_factory=Gateway), output=output)
        self.assertEqual(result, 0)
        for secret in (SECRET,'fixture@example.invalid','000000'):
            self.assertNotIn(secret, output.getvalue())

    def test_interactive_exception_redacted(self):
        login, http = self.make()
        def read(_): raise RuntimeError(SECRET)
        output = io.StringIO()
        self.assertEqual(run_interactive(_factory=lambda:login, _read=read, output=output), 2)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertTrue(http.closed)

    def test_gateway_failure_interrupt_and_cleanup(self):
        for error, code in [(RuntimeError(SECRET),'GATEWAY_VERIFY_FAILED'), (KeyboardInterrupt(),'CANCELLED')]:
            session = MemorySession(SECRET)
            gateway = Gateway(SECRET)
            def call(_): raise error
            gateway.call_json = call
            self.fails(code, lambda:session.verify_readonly(_gateway_factory=lambda _:gateway))
            self.assertTrue(gateway.closed)
            self.assertIsNone(session._cookies)
            self.assertNotIn(SECRET, repr(session))

    def test_arguments_never_echo_secrets(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(main(['--account',SECRET,'--otp','000000']), 2)
            self.assertEqual(main(['--help='+SECRET]), 2)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn('000000', output.getvalue())

    def test_cancel_at_memory_handoff(self):
        login, http = self.make()
        login.send('fixture@example.invalid')
        session = login.confirm('000000')
        login.cancel()
        self.fails('CANCELLED', lambda:session.verify_readonly(_gateway_factory=lambda _:self.fail('GATEWAY_CREATED')))
        self.assertIsNone(session._cookies)

    def test_cancel_during_gateway_setup(self):
        login, http = self.make()
        login.send('fixture@example.invalid')
        session = login.confirm('000000')
        gateway = Gateway(SECRET)
        def factory(_):
            login.cancel()
            return gateway
        self.fails('CANCELLED', lambda:session.verify_readonly(_gateway_factory=factory))
        self.assertEqual(gateway.calls, [])
        self.assertTrue(gateway.closed)

    def test_tty_and_getpass_fallback(self):
        with patch('sys.stdin.isatty', return_value=False):
            self.fails('INTERACTIVE_TTY_REQUIRED', lambda:hidden_input('hidden: '))
        import getpass
        with patch('sys.stdin.isatty', return_value=True), patch('sys.stderr.isatty', return_value=True), patch('getpass.getpass', side_effect=getpass.GetPassWarning('no terminal')):
            self.fails('INTERACTIVE_TTY_REQUIRED', lambda:hidden_input('hidden: '))

    def test_invalid_input_and_sequence(self):
        for contact in ('','\n',None):
            login, http = self.make()
            self.fails('INVALID_INPUT', lambda:login.send(contact))
            self.assertEqual(http.calls, [])
        login, http = self.make()
        self.fails('INVALID_SEQUENCE', lambda:login.confirm('000000'))
        self.assertTrue(http.closed)


if __name__ == '__main__': unittest.main()
