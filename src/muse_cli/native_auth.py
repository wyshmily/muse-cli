"""OTP state machine with independent auth verification and optional checkpoints."""
from dataclasses import dataclass
from threading import Event
import uuid

BASE = 'https://muse.ai'
_MESSAGES = {
    'CONTRACT_UNVERIFIED': 'Existing-account OTP success states and save-account semantics are unverified; no login request was sent.',
    'REGISTRATION_NOT_ALLOWED': 'Registration is not supported; stopped.',
    'COMPLETION_REQUIRED': 'Account completion is required; stopped.',
    'PASSWORD_REQUIRED': 'Password authentication is required; stopped.',
    'TWO_FACTOR_REQUIRED': 'Additional authentication is required; stopped.',
    'ACCOUNT_SELECTION_REQUIRED': 'Account selection is required; stopped.',
    'ACCOUNT_CONFIRMATION_REQUIRED': 'Account confirmation is required; stopped.',
    'UNKNOWN_AUTH_STATE': 'Missing, unknown, or contradictory authentication state; stopped.',
    'INVALID_OTP': 'The verification code was rejected; no retry was made.',
    'EXPIRED_OTP': 'The verification code expired; no retry was made.',
    'RATE_LIMITED': 'The service rejected further attempts; no retry was made.',
    'REGION_UNSUPPORTED': 'The service does not support this region; stopped.',
    'HTTP_REJECTED': 'Authentication request was rejected; no retry was made.',
    'NETWORK_FAILED': 'Authentication transport failed; no retry was made.',
    'TIMEOUT': 'Authentication timed out; the remote outcome may be unknown. No retry was made.',
    'INVALID_RESPONSE': 'Authentication returned an invalid response; stopped.',
    'INVALID_INPUT': 'Empty or invalid interactive input; stopped.',
    'INVALID_SEQUENCE': 'This login attempt cannot continue; start a separately authorized attempt.',
    'CANCELLED': 'Login cancelled; in-memory session released.',
    'SESSION_INVALID': 'Authentication did not establish a valid in-memory session.',
    'GATEWAY_VERIFY_FAILED': 'Read-only gateway verification failed; no details or credentials are displayed.',
    'INTERACTIVE_TTY_REQUIRED': 'An interactive terminal with hidden input is required.',
    'STORE_UNAVAILABLE': 'An unlocked Linux Secret Service is required; no plaintext fallback is used.',
    'STORE_USER_ACTION_REQUIRED': 'Secure storage is missing or locked, or requires a prompt. Configure/unlock it yourself; no automatic action was taken.',
    'STORE_ACCESS_NOT_ENABLED': 'This storage object is a read-only preflight; secret access was not enabled.',
    'VAULT_UNLOCK_FAILED': 'Vault authentication failed or its contents are damaged; no plaintext details are displayed.',
    'STORE_FAILED': 'Secure storage failed; no credential details are displayed.',
    'STORE_CORRUPT': 'Stored login data is invalid; no network request was sent.',
    'ATTEMPT_EXISTS': 'A saved attempt exists. Resume/check it or explicitly forget it before starting again.',
    'NO_SESSION': 'No saved login exists in the selected secure store.',
    'BUSY': 'Another process owns this login profile.',
    'WAITING_SESSION': 'Session is not ready. Use check again; do not resend OTP.',
    'CHECKPOINT_REQUIRED': 'An official account checkpoint is required; terminal continuation is blocked.',
    'ATTEMPT_EXPIRED': 'The local login continuation window expired. Check authentication before starting another attempt.',
}


class LoginError(Exception):
    def __init__(self, code):
        self.code = code if code in _MESSAGES else 'INVALID_RESPONSE'
        super().__init__(_MESSAGES[self.code])


@dataclass(frozen=True)
class _Contract:
    """Developer-reviewed contract, not an end-user or environment override.

    Tests use unmistakably synthetic enums. No real success enum is guessed.
    save_account must be 'required-existing-login' or 'omit' per verified evidence.
    """
    send_flow: str
    send_state: str
    confirm_state: str
    save_account: str
    evidence: str


def verified_contract():
    # send response observed by the authorized cloud operator, 2026-10-09.
    # confirm HTTP 200 has no state enum: authenticate independently, never infer
    # success from an invented enum or call the unverified save-account endpoint.
    return _Contract('login', 'otp_sent', 'auth-check', 'omit',
                     'Cloud operator nonsecret observation 2026-10-09')


def _checked_state(data, expected_state, expected_flow=None):
    if not isinstance(data, dict):
        raise LoginError('INVALID_RESPONSE')
    flow = data.get('flow')
    flow = flow.get('type') if isinstance(flow, dict) else flow
    state = data.get('registration_state')
    if flow == 'register' or state == 'register':
        raise LoginError('REGISTRATION_NOT_ALLOWED')
    blocked = {
        'completion_required': 'COMPLETION_REQUIRED',
        'password_required': 'PASSWORD_REQUIRED',
        'two_factor_required': 'TWO_FACTOR_REQUIRED',
        'account_selection_required': 'ACCOUNT_SELECTION_REQUIRED',
        'ntp_upsell': 'ACCOUNT_CONFIRMATION_REQUIRED',
    }
    if isinstance(state, str) and state in blocked:
        raise LoginError(blocked[state])
    if not isinstance(state, str) or state != expected_state:
        raise LoginError('UNKNOWN_AUTH_STATE')
    if expected_flow is not None and flow != expected_flow:
        raise LoginError('UNKNOWN_AUTH_STATE')


def _http_session():
    from curl_cffi import requests
    return requests.Session(impersonate='chrome', timeout=25)


class MemorySession:
    """Owns only in-memory credentials; no serialization or persistent export API."""
    def __init__(self, cookies, cancel_event=None):
        self._cookies = cookies
        self._cancel_event = cancel_event or Event()

    def __repr__(self):
        return '<MemorySession redacted>'

    def close(self):
        # Python/HTTP libraries can retain copies; this is not guaranteed zeroization.
        self._cookies = None

    def verify_readonly(self, *, _gateway_factory=None, retain=False):
        if not self._cookies:
            raise LoginError('SESSION_INVALID')
        gateway = None
        try:
            if self._cancel_event.is_set():
                raise LoginError('CANCELLED')
            if _gateway_factory is None:
                from .gateway import Gateway
                _gateway_factory = Gateway
            gateway = _gateway_factory(self._cookies)
            if self._cancel_event.is_set():
                raise LoginError('CANCELLED')
            # Same Gateway as the CLI, without load_config or any on-disk login.
            result = gateway.call_json('identity')
            if self._cancel_event.is_set():
                raise LoginError('CANCELLED')
            if not isinstance(result, dict) or not result or result.get('ok') is False:
                raise LoginError('SESSION_INVALID')
            return {'authenticated': True, 'gateway_verified': True}
        except (KeyboardInterrupt, EOFError):
            raise LoginError('CANCELLED') from None
        except LoginError:
            raise
        except Exception as exc:
            from .gateway import AuthError, GatewayError
            if isinstance(exc, AuthError) or (isinstance(exc, GatewayError) and exc.status == 401):
                raise LoginError('SESSION_INVALID') from None
            if isinstance(exc, GatewayError) and exc.status in (403, 429):
                raise LoginError('RATE_LIMITED' if exc.status == 429 else 'HTTP_REJECTED') from None
            if isinstance(exc, TimeoutError) or getattr(exc, 'code', None) == 28:
                raise LoginError('TIMEOUT') from None
            raise LoginError('GATEWAY_VERIFY_FAILED') from None
        finally:
            if gateway is not None:
                try:
                    gateway.close()
                except Exception:
                    pass
            if not retain:
                self.close()


class NativeLogin:
    def __init__(self, *, _http=None, _contract=None, cancel_event=None, checkpoint=None, retain_pending=False):
        # A test contract is accepted only with an explicitly injected transport.
        self.contract = verified_contract() if _contract is None else _contract
        if _contract is not None and _http is None:
            raise LoginError('CONTRACT_UNVERIFIED')
        if (not isinstance(self.contract, _Contract) or
                not all(isinstance(v, str) and v for v in (
                    self.contract.send_flow, self.contract.send_state,
                    self.contract.confirm_state, self.contract.evidence)) or
                self.contract.save_account not in ('required-existing-login', 'omit')):
            raise LoginError('CONTRACT_UNVERIFIED')
        self.http = _http if _http is not None else _http_session()
        self.cancel_event = cancel_event or Event()
        self.headers = {'Origin': BASE, 'Referer': BASE + '/',
                        'Accept': 'application/json', 'Sec-Fetch-Site': 'same-origin',
                        'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty',
                        'x-hatch-waterfall-id': str(uuid.uuid4())}
        self.csrf = None
        self.state = 'new'
        self.closed = False
        self.diagnostics = []
        self.checkpoint = checkpoint
        self.retain_pending = retain_pending

    def _save(self):
        if self.checkpoint:
            self.checkpoint(self)

    def __repr__(self):
        return '<NativeLogin redacted>'

    def cancel(self):
        self.cancel_event.set()
        # An active request is bounded by its timeout; do not race session.close.

    def _check_cancel(self):
        if self.cancel_event.is_set():
            raise LoginError('CANCELLED')

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.csrf = None
        self.headers.clear()
        try:
            self.http.cookies.clear()
        except Exception:
            pass
        try:
            self.http.close()
        except Exception:
            pass

    def _request(self, method, path, body=None, csrf=False):
        self._check_cancel()
        headers = dict(self.headers)
        if csrf:
            headers.update({'x-hatch-csrf-token': self.csrf,
                            'x-hatch-caa-reg-entry-point': 'login_home'})
        try:
            response = self.http.request(method, BASE + path, headers=headers,
                json=body, timeout=25, allow_redirects=False)
        except (KeyboardInterrupt, EOFError):
            raise LoginError('CANCELLED') from None
        except Exception as exc:
            code = 'TIMEOUT' if isinstance(exc, TimeoutError) or getattr(exc, 'code', None) == 28 else 'NETWORK_FAILED'
            raise LoginError(code) from None
        self._check_cancel()
        if path == '/api/auth/native/confirm-otp':
            from .safe_diagnostics import response_shape
            try:
                shape = response_shape(response.json())
            except Exception:
                shape = {'type': 'non-json'}
            self.diagnostics.append({'http_status': int(response.status_code), 'body': shape})
        self._save()
        # The homepage is only a prewarm. AYMH redirects are normal; do not
        # follow cross-origin redirects with our authentication headers.
        if path == '/' and response.status_code in (301, 302, 303, 307, 308):
            return {}
        if not 200 <= response.status_code < 300:
            try:
                data = response.json()
                kind = data.get('type') if isinstance(data, dict) else None
            except Exception:
                kind = None
            known = {'invalidOtp': 'INVALID_OTP', 'expiredOtp': 'EXPIRED_OTP',
                     'tooManyAttempts': 'RATE_LIMITED', 'regionNotSupported': 'REGION_UNSUPPORTED'}
            if response.status_code == 429:
                raise LoginError('RATE_LIMITED')
            if path == '/api/auth/check' and response.status_code == 401:
                raise LoginError('SESSION_INVALID')
            raise LoginError(known.get(kind, 'HTTP_REJECTED') if isinstance(kind, str) else 'HTTP_REJECTED')
        if path == '/':
            return {}
        try:
            data = response.json()
        except Exception:
            raise LoginError('INVALID_RESPONSE') from None
        if not isinstance(data, dict):
            raise LoginError('INVALID_RESPONSE')
        return data

    def send(self, contact):
        try:
            if self.closed or self.state != 'new':
                raise LoginError('INVALID_SEQUENCE')
            if not isinstance(contact, str) or not contact.strip() or len(contact) > 320 or any(ord(c) < 32 for c in contact):
                raise LoginError('INVALID_INPUT')
            self.state = 'sending'
            self._save()
            self._request('GET', '/')
            data = self._request('POST', '/api/auth/native/restart', {})
            self.csrf = data.get('csrf_token')
            if not isinstance(self.csrf, str) or not self.csrf:
                raise LoginError('INVALID_RESPONSE')
            data = self._request('POST', '/api/auth/native/send-otp', {'contact_point': contact.strip()}, True)
            _checked_state(data, self.contract.send_state, self.contract.send_flow)
            self.state = 'otp_sent'
            self._save()
        except (KeyboardInterrupt, EOFError):
            self.close()
            raise LoginError('CANCELLED') from None
        except LoginError:
            self.close()
            raise
        except Exception:
            self.close()
            raise LoginError('INVALID_RESPONSE') from None

    def confirm(self, code):
        try:
            if self.closed or self.state != 'otp_sent':
                raise LoginError('INVALID_SEQUENCE')
            if not isinstance(code, str) or not code.strip() or len(code) > 64 or any(ord(c) < 32 for c in code):
                raise LoginError('INVALID_INPUT')
            self.state = 'confirming'
            self._save()
            data = self._request('POST', '/api/auth/native/confirm-otp', {'otp_code': code.strip()}, True)
            if self.contract.confirm_state == 'auth-check':
                if data.get('checkpoint_url'):
                    raise LoginError('CHECKPOINT_REQUIRED')
                # Known state-bearing responses must not bypass branch guards.
                # Empty state-less 200 is not success: check_session proves it.
                if any(k in data for k in ('flow', 'registration_state', 'error_type', 'error_code', 'error', 'type')):
                    _checked_state(data, '__no_state_expected__')
            else:
                _checked_state(data, self.contract.confirm_state)
            # Any unexpected flow contradicts an existing-account contract.
            if 'flow' in data and self.contract.confirm_state != 'auth-check':
                _checked_state(data, self.contract.confirm_state, self.contract.send_flow)
            if self.contract.save_account == 'required-existing-login':
                self._request('POST', '/api/auth/save-account')
            check = self._request('POST', '/api/auth/check')
            if not isinstance(check.get('access_token'), str) or not check['access_token']:
                raise LoginError('SESSION_INVALID')
            cookies = [c for c in self.http.cookies.jar
                       if c.domain.lstrip('.') == 'muse.ai'
                       and c.path in ('/', '/api', '/api/')
                       and not (getattr(c, 'expires', None) and c.is_expired())]
            if not any(c.name == 'hatch_sess' and c.value for c in cookies):
                raise LoginError('SESSION_INVALID')
            self._check_cancel()
            session = MemorySession('; '.join(c.name + '=' + c.value for c in cookies), self.cancel_event)
            self.state = 'authenticated'
            self._save()
            return session
        except (KeyboardInterrupt, EOFError):
            raise LoginError('CANCELLED') from None
        except LoginError as exc:
            if exc.code in ('CHECKPOINT_REQUIRED', 'REGISTRATION_NOT_ALLOWED',
                            'COMPLETION_REQUIRED', 'PASSWORD_REQUIRED',
                            'TWO_FACTOR_REQUIRED', 'ACCOUNT_SELECTION_REQUIRED',
                            'ACCOUNT_CONFIRMATION_REQUIRED', 'UNKNOWN_AUTH_STATE'):
                self.state = 'blocked'
                self._save()
            raise
        except Exception:
            raise LoginError('INVALID_RESPONSE') from None
        finally:
            if not self.retain_pending or self.state == 'authenticated':
                self.close()
