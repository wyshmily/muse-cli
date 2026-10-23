"""Resumable state in an explicitly selected store, without account/OTP storage."""
import http.cookiejar
import time
from .native_auth import LoginError, NativeLogin, MemorySession

STATES = {'new', 'sending', 'otp_sent', 'confirming', 'authenticated', 'blocked'}
COOKIE_FIELDS = ('version', 'name', 'value', 'port', 'port_specified', 'domain',
                 'domain_specified', 'domain_initial_dot', 'path', 'path_specified',
                 'secure', 'expires', 'discard', 'comment', 'comment_url', 'rfc2109')


def snapshot(login, created):
    cookies = []
    for cookie in login.http.cookies.jar:
        if cookie.domain.lstrip('.') != 'muse.ai':
            continue
        row = {k: getattr(cookie, k) for k in COOKIE_FIELDS}
        row['rest'] = dict(cookie._rest)
        cookies.append(row)
    return {'version': 1, 'state': login.state, 'created': created,
            'csrf': login.csrf, 'cookies': cookies,
            'diagnostics': login.diagnostics}


def restore(value, *, _http=None):
    login = None
    try:
        if not isinstance(value, dict) or value.get('version') != 1 or value.get('state') not in STATES:
            raise ValueError()
        if not isinstance(value.get('created'), (int, float)) or not 0 < value['created'] <= time.time()+60:
            raise ValueError()
        if not isinstance(value.get('cookies'), list) or len(value['cookies']) > 100:
            raise ValueError()
        csrf = value.get('csrf')
        if csrf is not None and (not isinstance(csrf, str) or not csrf or len(csrf) > 8192 or any(ord(c) < 32 for c in csrf)):
            raise ValueError()
        if value['state'] == 'otp_sent' and csrf is None:
            raise ValueError()
        parsed = []
        for row in value['cookies']:
            c = http.cookiejar.Cookie(**row)
            if c.domain.lstrip('.') != 'muse.ai' or not c.path.startswith('/'):
                raise ValueError()
            if not c.name or any(x in c.name for x in '\r\n;=') or any(x in c.value for x in '\r\n;'):
                raise ValueError()
            parsed.append(c)
        login = NativeLogin(_http=_http)
        login.state, login.csrf = value['state'], csrf
        for c in parsed:
            login.http.cookies.jar.set_cookie(c)
        from .safe_diagnostics import stored_diagnostics
        login.diagnostics = stored_diagnostics(value.get('diagnostics'))
        return login
    except Exception:
        if login:
            login.close()
        raise LoginError('STORE_CORRUPT') from None


def check_session(login):
    """Read auth state only; never sends another code or finalizes an account."""
    if login.closed or login.state == 'blocked':
        raise LoginError('INVALID_SEQUENCE')
    data = login._request('POST', '/api/auth/check')
    if not isinstance(data.get('access_token'), str) or not data['access_token']:
        raise LoginError('WAITING_SESSION')
    cookies = [c for c in login.http.cookies.jar if c.domain.lstrip('.') == 'muse.ai'
               and c.path in ('/', '/api', '/api/') and not c.is_expired()]
    if not any(c.name == 'hatch_sess' and c.value for c in cookies):
        raise LoginError('WAITING_SESSION')
    return MemorySession('; '.join(c.name + '=' + c.value for c in cookies))


class SavedLogin:
    def __init__(self, store, *, _factory=NativeLogin):
        self.store, self.factory = store, _factory
        self.diagnostics = []

    def start(self, read):
        if self.store.load() is not None:
            raise LoginError('ATTEMPT_EXISTS')
        created = time.time()
        login = self.factory()
        login.checkpoint = lambda current: self.store.save(snapshot(current, created))
        try:
            login.send(read('Existing Muse account (hidden): '))
        finally:
            self.diagnostics = login.diagnostics
            login.close()

    def resume(self, *, confirm=None, _http=None):
        value = self.store.load()
        if value is None:
            raise LoginError('NO_SESSION')
        login = restore(value, _http=_http)
        login.checkpoint = lambda current: self.store.save(snapshot(current, value['created']))
        try:
            if confirm is not None:
                if login.state != 'otp_sent':
                    raise LoginError('INVALID_SEQUENCE')
                if time.time() - value['created'] > 600:
                    raise LoginError('ATTEMPT_EXPIRED')
                return login.confirm(confirm('Verification code (hidden): '))
            session = check_session(login)
            login.state = 'authenticated'
            login._save()
            return session
        finally:
            self.diagnostics = login.diagnostics
            login.close()
