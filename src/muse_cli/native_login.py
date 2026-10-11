"""Interactive memory terminal and explicit secure-store staged login."""
import argparse
import getpass
import sys
import warnings
import json
import time
from .native_auth import LoginError, NativeLogin


def hidden_input(prompt):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise LoginError('INTERACTIVE_TTY_REQUIRED')
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise LoginError('INTERACTIVE_TTY_REQUIRED') from None


def run_interactive(*, _factory=NativeLogin, _read=hidden_input, _verify=None, output=None):
    output = output or sys.stderr
    login = session = None
    try:
        login = _factory()  # Contract preflight BEFORE collecting any account data.
        contact = _read('Existing Muse account (hidden; Ctrl+C cancels): ')
        login.send(contact)
        contact = None
        code = _read('Verification code (hidden; Ctrl+C cancels): ')
        session = login.confirm(code)
        code = None
        if _verify is not None:
            _verify(session)
        print('In-memory login completed. Gateway not automatically verified. Nothing saved.', file=output)
        return 0
    except (KeyboardInterrupt, EOFError):
        print('CANCELLED: Login cancelled; nothing saved.', file=output)
        return 130
    except LoginError as exc:
        print(f'{exc.code}: {exc}', file=output)
        return 130 if exc.code == 'CANCELLED' else 2
    except Exception:
        print('LOGIN_FAILED: Login stopped; no diagnostic payload is displayed.', file=output)
        return 2
    finally:
        contact = code = None
        if session is not None:
            session.close()
        if login is not None:
            login.close()


def main(argv=None):
    from .readonly import Parser, ReadError
    from .secure_store import configured_store
    from .login_state import SavedLogin
    session = workflow = None
    try:
        parser = Parser(description='Muse OTP: hidden TTY input, no account/code arguments. Default session is memory-only.')
        parser.add_argument('action', nargs='?', default='session',
                            choices=['session', 'preflight', 'start', 'confirm', 'check', 'status', 'forget'])
        parser.add_argument('--store', choices=['secretservice', 'encrypted-file', 'plaintext-file'])
        parser.add_argument('--vault', help='absolute session file path in a user-prepared private durable directory')
        parser.add_argument('--profile', default='default')
        parser.add_argument('--wait', type=int, default=0,
                            help='check only: wait up to 300 seconds, polling read-only checks every 5 seconds')
        args = parser.parse_args(argv)
        if not 0 <= args.wait <= 300 or (args.wait and args.action != 'check'):
            raise ReadError('INVALID_ARGUMENTS')
        if args.action == 'session':
            if args.store or args.vault:
                raise ReadError('USE_STAGED_COMMANDS_FOR_STORAGE')
            return memory_terminal()
        if args.store is None:
            raise ReadError('EXPLICIT_STORE_REQUIRED')
        store = configured_store(args.store, args.profile, vault=args.vault, allow_secret_access=args.action != 'preflight')
        if args.action == 'preflight':
            store.preflight()
            print('Storage metadata preflight passed. No secret access, creation, unlock or prompt performed.')
            return 0
        with store.lock():
            workflow = SavedLogin(store)
            if args.action == 'start':
                workflow.start(hidden_input)
                print('OTP_SENT: Resume with confirm; do not start again.')
            elif args.action in ('confirm', 'check'):
                deadline = time.monotonic() + args.wait
                while True:
                    try:
                        session = workflow.resume(confirm=hidden_input if args.action == 'confirm' else None)
                        break
                    except LoginError as exc:
                        if args.action != 'check' or exc.code != 'WAITING_SESSION' or time.monotonic() >= deadline:
                            raise
                        if session:
                            session.close()
                            session = None
                        time.sleep(min(5, max(0, deadline-time.monotonic())))
                print('AUTHENTICATED: auth/check passed; session saved in the selected store. Gateway not verified; no gateway connection attempted.')
            elif args.action == 'status':
                value = store.load()
                from .login_state import STATES
                state = value.get('state') if value else 'absent'
                if state not in STATES and state != 'absent':
                    raise LoginError('STORE_CORRUPT')
                print(state)
            elif args.action == 'forget':
                store.forget()
                print('Local stored attempt deleted. Remote session was not revoked.')
        return 0
    except (KeyboardInterrupt, EOFError):
        print('CANCELLED: Use check/status before any new OTP attempt.', file=sys.stderr)
        return 130
    except (LoginError, ReadError) as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except Exception:
        print('LOGIN_FAILED: Details suppressed; use status/check before starting again.', file=sys.stderr)
        return 2
    finally:
        if workflow:
            for diagnostic in workflow.diagnostics:
                print(json.dumps({'confirm_shape': diagnostic}), file=sys.stderr)
        if session:
            session.close()


def memory_terminal():
    """One persistent PTY; EOF exits instead of repeatedly prompting/sending."""
    from .login_state import check_session
    from .readonly import read, ReadError
    from .gateway import Gateway
    login = NativeLogin(retain_pending=True)
    session = None
    try:
        login.send(hidden_input('Existing Muse account (hidden): '))
        try:
            session = login.confirm(hidden_input('Verification code (hidden): '))
            print('AUTHENTICATED: auth/check passed; memory only. Gateway not verified.')
        except LoginError as exc:
            print(exc.code + ': only check/quit are available; OTP will not be resent.', file=sys.stderr)
        finally:
            for diagnostic in login.diagnostics:
                print(json.dumps({'confirm_shape': diagnostic}), file=sys.stderr)
        while True:
            # This prompt only accepts read commands/IDs, never account or OTP.
            if not sys.stdin.isatty():
                raise LoginError('INTERACTIVE_TTY_REQUIRED')
            command = input('muse [check, identity, sessions, session ID, history ID, spaces, quit]> ').strip().split()
            if not command:
                continue
            if command == ['quit']:
                return 0
            gateway = None
            try:
                if command == ['check']:
                    checked = check_session(login)
                    if session is not None:
                        session.close()
                    session = checked
                    print('AUTHENTICATED: auth/check passed; memory only. Gateway not verified.')
                    continue
                if session is None:
                    raise LoginError('WAITING_SESSION')
                if command[0] not in ('identity', 'sessions', 'session', 'history', 'spaces') or len(command) != (2 if command[0] in ('session', 'history') else 1):
                    raise ReadError('INVALID_ARGUMENTS')
                gateway = Gateway(session._cookies)
                print(json.dumps(read(gateway, command[0], identifier=command[1] if len(command) == 2 else None), ensure_ascii=False))
            except (LoginError, ReadError) as exc:
                print(exc.code, file=sys.stderr)
            except Exception:
                print('READ_FAILED: no automatic retry.', file=sys.stderr)
            finally:
                if gateway:
                    gateway.close()
    finally:
        login.close()
        if session:
            session.close()


if __name__ == '__main__':
    raise SystemExit(main())
