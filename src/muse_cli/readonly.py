"""Small read-only command surface, separate from the legacy writing CLI."""
import argparse
import json
import re
import sys
from .native_auth import LoginError


class ReadError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def classify(exc):
    from .gateway import AuthError, GatewayError
    if isinstance(exc, AuthError):
        return 'AUTH_INVALID'
    if isinstance(exc, TimeoutError) or getattr(exc, 'code', None) == 28:
        return 'TIMEOUT'
    if isinstance(exc, GatewayError):
        return {401: 'AUTH_INVALID', 403: 'FORBIDDEN', 404: 'NOT_FOUND',
                429: 'RATE_LIMITED', -1: 'GATEWAY_UNAVAILABLE'}.get(exc.status, 'API_FAILED')
    return 'TRANSPORT_FAILED'


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', value):
        raise ReadError('INVALID_ID')
    return value


def read(gateway, command, *, identifier=None, limit=20, cursor=None):
    if not 1 <= limit <= 100:
        raise ReadError('INVALID_LIMIT')
    if command == 'media':
        raise ReadError('MEDIA_SCHEMA_UNVERIFIED')
    requests = {'identity': ('identity', {}), 'sessions': ('sessions.list', {}),
                'spaces': ('spaces.list', {})}
    if command == 'session':
        requests[command] = ('sessions.get', {'path_params': {'id': safe_id(identifier)}})
    elif command == 'history':
        requests[command] = ('chat.history', {'query': {'session_id': safe_id(identifier), 'limit': limit}})
    if command not in requests:
        raise ReadError('UNSUPPORTED_READ')
    method, kwargs = requests[command]
    from .gateway import ROUTES
    if ROUTES[method]['http'] != 'GET':
        raise ReadError('READ_CONTRACT_CHANGED')
    try:
        result = gateway.call_json(method, **kwargs)
        if not isinstance(result, (dict, list)):
            raise ReadError('INVALID_RESPONSE')
        from .safe_diagnostics import redact
        return redact(result)
    except ReadError:
        raise
    except Exception as exc:
        raise ReadError(classify(exc)) from None


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid positional strings (possibly secrets).
        raise ReadError('INVALID_ARGUMENTS')


def main(argv=None):
    session = gateway = None
    try:
        parser = Parser(description='Read-only Muse access using explicit Secret Service storage.')
        parser.add_argument('--profile', default='default')
        parser.add_argument('--store', choices=['secretservice', 'encrypted-file', 'plaintext-file'], default='secretservice')
        parser.add_argument('--vault')
        parser.add_argument('command', choices=['identity', 'sessions', 'session', 'history', 'spaces', 'media'])
        parser.add_argument('--id')
        parser.add_argument('--limit', type=int, default=20)
        args = parser.parse_args(argv)
        if args.command == 'media':
            raise ReadError('MEDIA_SCHEMA_UNVERIFIED')
        if not 1 <= args.limit <= 100:
            raise ReadError('INVALID_LIMIT')
        if args.command in ('session', 'history'):
            safe_id(args.id)
        elif args.id is not None:
            raise ReadError('INVALID_ARGUMENTS')
        from .secure_store import configured_store
        from .login_state import SavedLogin
        from .gateway import Gateway
        store = configured_store(args.store, args.profile, vault=args.vault, allow_secret_access=True)
        with store.lock():
            session = SavedLogin(store).resume()
        gateway = Gateway(session._cookies)
        result = read(gateway, args.command, identifier=args.id, limit=args.limit)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (KeyboardInterrupt, EOFError):
        print('CANCELLED', file=sys.stderr)
        return 130
    except (ReadError, LoginError) as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except Exception as exc:
        print(classify(exc), file=sys.stderr)
        return 2
    finally:
        if gateway is not None:
            try:
                gateway.close()
            except Exception:
                pass
        if session is not None:
            session.close()


if __name__ == '__main__':
    raise SystemExit(main())
