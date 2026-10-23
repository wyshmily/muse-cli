#!/usr/bin/env python3
"""Offline, non-secret Muse recovery plans. A valid plan is NOT authorization.

This tool never reads credential contents, sends a message, generates a key,
restores a login, or calls a network. Trusted owner approval/claim is a separate
server operation; neither this digest nor any model-supplied flag can replace it.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

SCHEMA_VERSION = 1
MAX_TTL = 600
MAX_SAFE_INTEGER = 2 ** 53 - 1
HOSTS = frozenset({'muse.ai', 'hatch.metaaivm.com'})
ACTIONS = frozenset({'auth_check', 'read_identity', 'read_sessions', 'read_history'})
FIELDS = frozenset({'schema_version', 'request_id', 'task_id', 'environment_instance_id',
                    'recipient_public_key_sha256', 'scope', 'cli_commit',
                    'created_at', 'expires_at', 'request_digest'})
SCOPE_FIELDS = frozenset({'actions', 'hosts', 'account_ref', 'vault_ref'})
BINDING_FIELDS = frozenset({'task_id', 'environment_instance_id',
                          'recipient_public_key_sha256', 'scope', 'cli_commit'})
TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', re.ASCII)


def fail(code):
    raise ValueError(code)


def canonical_bytes(plan):
    """v1 canonical bytes; call structural validation before digesting input."""
    return json.dumps({k: v for k, v in plan.items() if k != 'request_digest'},
                      sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def digest(plan):
    return hashlib.sha256(canonical_bytes(plan)).hexdigest()


def token(value):
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def hex_string(value, length):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None


def validate_binding(binding):
    if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS:
        fail('INVALID_BINDING_FIELDS')
    if not all(token(binding[k]) for k in ('task_id', 'environment_instance_id')):
        fail('INVALID_INSTANCE_OR_TASK')
    if not hex_string(binding['recipient_public_key_sha256'], 64) or not hex_string(binding['cli_commit'], 40):
        fail('INVALID_KEY_OR_COMMIT')
    scope = binding['scope']
    if not isinstance(scope, dict) or set(scope) != SCOPE_FIELDS:
        fail('INVALID_SCOPE_FIELDS')
    if not all(token(scope[k]) for k in ('account_ref', 'vault_ref')):
        fail('INVALID_ALIAS')
    for name, allowed in (('actions', ACTIONS), ('hosts', HOSTS)):
        values = scope[name]
        if (not isinstance(values, list) or not values or
                not all(isinstance(x, str) and x in allowed for x in values) or
                values != sorted(set(values))):
            fail('INVALID_SCOPE_' + name.upper())
    return binding


def validate(plan, *, expected_binding, now=None):
    """Validate non-authorizing plan against independently trusted current intent.

    expected_binding must NOT be copied from the untrusted incoming plan. The
    server must also verify owner approval, challenge, expiry and one-use claim.
    """
    if not isinstance(plan, dict) or set(plan) != FIELDS:
        fail('INVALID_PLAN_FIELDS')
    if type(plan['schema_version']) is not int or plan['schema_version'] != SCHEMA_VERSION:
        fail('INVALID_SCHEMA_VERSION')
    request_id = plan['request_id']
    try:
        parsed = uuid.UUID(request_id) if isinstance(request_id, str) else None
    except (ValueError, AttributeError):
        parsed = None
    if parsed is None or parsed.version != 4 or str(parsed) != request_id:
        fail('INVALID_REQUEST_ID')
    binding = {k: plan[k] for k in BINDING_FIELDS}
    validate_binding(binding)
    validate_binding(expected_binding)
    if binding != expected_binding:
        fail('BINDING_MISMATCH')
    for field in ('created_at', 'expires_at'):
        if type(plan[field]) is not int or not 0 <= plan[field] <= MAX_SAFE_INTEGER:
            fail('INVALID_TIMESTAMP')
    created, expires = plan['created_at'], plan['expires_at']
    now = int(time.time()) if now is None else now
    if not 0 < expires - created <= MAX_TTL:
        fail('INVALID_TTL')
    if created > now:
        fail('PLAN_NOT_YET_VALID')
    if now >= expires:
        fail('PLAN_EXPIRED')
    if not hex_string(plan['request_digest'], 64) or not hmac.compare_digest(plan['request_digest'], digest(plan)):
        fail('DIGEST_MISMATCH')
    return plan


def create(binding, *, ttl=300, now=None):
    validate_binding(binding)
    if type(ttl) is not int or not 1 <= ttl <= MAX_TTL:
        fail('INVALID_TTL')
    now = int(time.time()) if now is None else now
    # Copy inputs to prevent accidental mutation of the caller's scope lists.
    plan = json.loads(json.dumps(binding))
    plan.update(schema_version=SCHEMA_VERSION, request_id=str(uuid.uuid4()),
                created_at=now, expires_at=now + ttl)
    plan['request_digest'] = digest(plan)
    return validate(plan, expected_binding=binding, now=now)


def credential_status(path):
    """Only lstat metadata of the explicitly selected file, never open/read it.

    A private regular file is merely present_unverified, not a valid login.
    Reject symlink parent components as well as a symlink final component.
    """
    # Reject traversal before abspath can erase a symlink/.. component.
    if '..' in Path(path).parts:
        return 'blocked_unsafe_metadata'
    path = Path(os.path.abspath(path))
    try:
        for component in reversed(path.parents):
            if stat.S_ISLNK(component.lstat().st_mode):
                return 'blocked_unsafe_metadata'
        info = path.lstat()
    except FileNotFoundError:
        return 'needs_recovery'
    except OSError:
        return 'blocked_unreadable_metadata'
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        return 'blocked_unsafe_metadata'
    return 'present_unverified'


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def load_plan(path):
    # Bounded non-secret plan input. Credential files are never passed here.
    with open(path, 'rb') as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        fail('PLAN_TOO_LARGE')
    return json.loads(raw, object_pairs_hook=unique_object,
                      parse_constant=lambda _: fail('INVALID_JSON_NUMBER'))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Never reflect unexpected argument values into diagnostics.
        self.exit(2, 'INVALID_ARGUMENTS\n')


def add_binding_args(parser):
    for name in ('task-id', 'environment-instance-id', 'recipient-public-key-sha256',
                 'account-ref', 'vault-ref', 'cli-commit'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--actions', nargs='+', required=True)
    parser.add_argument('--hosts', nargs='+', required=True)


def args_binding(args):
    return {k: getattr(args, k) for k in BINDING_FIELDS if k != 'scope'} | {
        'scope': {k: getattr(args, k) for k in SCOPE_FIELDS}}


def main(argv=None):
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('describe', help='Offline schema and authorization boundary')
    inspect = commands.add_parser('inspect-status', help='Credential file metadata only; no auth verification')
    inspect.add_argument('--credential-file', required=True)
    make = commands.add_parser('create', help='Emit an authorization request plan, never an authorization')
    add_binding_args(make)
    make.add_argument('--credential-file', required=True)
    make.add_argument('--ttl-seconds', type=int, default=300)
    check = commands.add_parser('validate', help='Check exact trusted binding; does not approve or claim')
    add_binding_args(check)
    check.add_argument('--plan', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'describe':
            result = {'schema_version': SCHEMA_VERSION, 'fields': sorted(FIELDS),
                      'actions': sorted(ACTIONS), 'hosts': sorted(HOSTS),
                      'max_ttl_seconds': MAX_TTL, 'authorization_granted': False,
                      'network_used': False, 'credentials_read': False,
                      'canonical': 'ASCII compact JSON recursively sorted keys; omit request_digest; arrays sorted unique; SHA-256 lowercase hex',
                      'approval': 'Requires separate trusted owner approval and atomic server-side claim; no approved flag accepted'}
        elif args.command == 'inspect-status':
            status = credential_status(args.credential_file)
            result = {'credential_status': status, 'credentials_read': False,
                      'live_auth_verified': False}
            print(json.dumps(result, sort_keys=True))
            return 2 if status.startswith('blocked_') else 0
        elif args.command == 'create':
            status = credential_status(args.credential_file)
            if status.startswith('blocked_'):
                fail('CREDENTIAL_METADATA_BLOCKED')
            result = create(args_binding(args), ttl=args.ttl_seconds)
            print(json.dumps({'credential_status': status,
                              'plan_status': ('needs_owner_authorization' if status == 'needs_recovery'
                                              else 'draft_pending_session_verification'),
                              'authorization_granted': False, 'credentials_read': False},
                             sort_keys=True), file=sys.stderr)
        else:
            validate(load_plan(args.plan), expected_binding=args_binding(args))
            result = {'status': 'valid_non_authorizing_plan', 'authorization_granted': False}
        print(json.dumps(result, sort_keys=True, separators=(',', ':')))
        return 0
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        # Input contents, filesystem paths and exceptions may contain private data.
        print('RECOVERY_PLAN_REJECTED', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
