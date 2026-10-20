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
                'spaces': ('spaces.list', {}),
                'vm-health': ('vm.health', {}),
                'vm-enrollment-health': ('vm.enrollment_health', {})}
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
        if command in ('vm-health', 'vm-enrollment-health'):
            if not isinstance(result, dict):
                raise ReadError('INVALID_RESPONSE')
            allowed = {'cvm_enroll_state'}
            if command == 'vm-health':
                allowed |= {'all_healthy', 'checked_at_ms', 'health_source',
                            'daemon_metrics_reachable', 'has_active_connection',
                            'has_active_human_connection', 'has_live_device',
                            'root_agent_available', 'ws_reachable',
                            'no_in_flight_work', 'active_delivery_count',
                            'active_runtime_work_count', 'active_subagent_count',
                            'active_turn_count', 'device_count'}
            result = {k: v for k, v in result.items() if k in allowed}
            for key, value in result.items():
                if key == 'cvm_enroll_state':
                    valid = value in ('UNENROLLED', 'ENROLLING', 'ENROLLED', 'NOT_APPLICABLE')
                elif key == 'health_source':
                    valid = isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value))
                elif key.endswith(('_count', '_ms')):
                    valid = type(value) is int and value >= 0
                else:
                    valid = type(value) is bool
                if not valid:
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
    session = gateway = login = None
    try:
        parser = Parser(description='Read-only Muse queries using explicitly selected existing login storage.',
                        epilog='vm-status: website inventory/state (no wake/reset); vm-health and '
                               'vm-enrollment-health: gateway diagnostics, not quota. '
                               'quota: verified read-only website action; no recovery or retries. '
                               'capabilities: offline route inventory, --id filters method prefix; not permission to execute.')
        parser.add_argument('--profile', default='default')
        parser.add_argument('--store', choices=['secretservice', 'encrypted-file', 'plaintext-file'], default='secretservice')
        parser.add_argument('--vault')
        parser.add_argument('command', choices=['identity', 'sessions', 'session', 'history', 'spaces', 'media',
                                                'vm-health', 'vm-enrollment-health', 'vm-status', 'quota', 'capabilities', 'model', 'computer-context',
                                                'voice-catalog', 'voice-filters',
                                                'connector-marketplace', 'library', 'discover', 'describe'])
        parser.add_argument('target', nargs='?', help='Command name for describe (offline).')
        parser.add_argument('--group', help='Command group for discover (offline).')
        parser.add_argument('--id')
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--offset', type=int, default=0, help='Voice/library page offset (0..100000).')
        parser.add_argument('--preset', choices=['artifacts', 'media', 'recents'], default='artifacts', help='Library listing preset; never a filesystem path.')
        args = parser.parse_args(argv)
        if args.command in ('discover', 'describe'):
            if args.id is not None or args.offset or args.preset != 'artifacts' or args.limit != 20:
                raise ReadError('INVALID_ARGUMENTS')
            from .discovery import discover, describe
            if args.command == 'discover':
                if args.target is not None:
                    raise ReadError('INVALID_ARGUMENTS')
                result = discover(args.group)
            else:
                if args.target is None or args.group is not None:
                    raise ReadError('INVALID_ARGUMENTS')
                result = describe(args.target)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.target is not None or args.group is not None:
            raise ReadError('INVALID_ARGUMENTS')
        if args.command == 'capabilities':
            from .capabilities import capabilities
            print(json.dumps(capabilities(prefix=args.id, limit=args.limit), ensure_ascii=False))
            return 0
        if not 0 <= args.offset <= 100000:
            raise ReadError('INVALID_LIMIT')
        if args.offset and args.command not in ('voice-catalog', 'library'):
            raise ReadError('INVALID_ARGUMENTS')
        if args.preset != 'artifacts' and args.command != 'library':
            raise ReadError('INVALID_ARGUMENTS')
        if args.command == 'media':
            raise ReadError('MEDIA_SCHEMA_UNVERIFIED')
        if not 1 <= args.limit <= 100:
            raise ReadError('INVALID_LIMIT')
        if args.command in ('session', 'history'):
            safe_id(args.id)
        elif args.id is not None:
            raise ReadError('INVALID_ARGUMENTS')
        from .secure_store import configured_store
        from .login_state import SavedLogin, restore
        from .gateway import Gateway
        store = configured_store(args.store, args.profile, vault=args.vault, allow_secret_access=True)
        from .account_queries import WEB_QUERIES, read_web
        from .metadata_queries import CONTRACTS, read_metadata
        if args.command in WEB_QUERIES or args.command in CONTRACTS or args.command in ('quota', 'vm-health', 'vm-enrollment-health'):
            with store.lock():
                value = store.load()
                if value is None:
                    raise LoginError('NO_SESSION')
                login = restore(value)
            if login.state == 'blocked':
                raise LoginError('INVALID_SEQUENCE')
            if args.command == 'quota':
                from .subscription_queries import read_quota
                result = read_quota(login)
            elif args.command in WEB_QUERIES:
                result = read_web(login.http, args.command)
            else:
                # Reuse only existing Muse cookies in memory. Gateway performs
                # its standard temporary auth handshake; never save the login.
                cookies = '; '.join(c.name + '=' + c.value for c in login.http.cookies.jar
                                    if c.domain.lstrip('.') == 'muse.ai'
                                    and c.path in ('/', '/api', '/api/') and not c.is_expired())
                gateway = Gateway(cookies)
                if args.command in CONTRACTS:
                    result = read_metadata(gateway, args.command, limit=args.limit,
                                           offset=args.offset, preset=args.preset)
                else:
                    result = read(gateway, args.command)
        else:
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
        if login is not None:
            login.close()


if __name__ == '__main__':
    raise SystemExit(main())
