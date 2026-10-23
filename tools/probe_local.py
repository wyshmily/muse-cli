#!/usr/bin/env python3
"""One explicitly authorized, memory-only Muse probe; never transfers credentials.
Input: separately approved temporary encrypted envelope, not a persistent login.
No retry, OTP, task, upload, generation, or persistent-login write is performed.
The caller must obtain current authorization for both transfer and gateway host.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat


SAFE_ERROR_CODES = frozenset({
    'AUTH_INVALID', 'SESSION_INVALID', 'WAITING_SESSION', 'INVALID_SEQUENCE',
    'STORE_CORRUPT', 'FORBIDDEN', 'NOT_FOUND', 'RATE_LIMITED', 'TIMEOUT',
    'GATEWAY_UNAVAILABLE', 'API_FAILED', 'TRANSPORT_FAILED', 'HTTP_REJECTED',
    'NETWORK_FAILED', 'REGION_UNSUPPORTED', 'CHECKPOINT_REQUIRED',
    'INVALID_RESPONSE', 'READ_CONTRACT_CHANGED', 'CANCELLED',
})


def safe_error_code(exc, stage, classify):
    code = getattr(exc, 'code', None)
    if isinstance(code, str) and code in SAFE_ERROR_CODES:
        return code
    if stage == 'decrypt':
        return 'LOCAL_ENVELOPE_FAILED'
    classified = classify(exc)
    return classified if isinstance(classified, str) and classified in SAFE_ERROR_CODES else 'LOCAL_PROBE_FAILED'


def sessions_shape(payload):
    """Use existing cli.py::cmd_threads contract; return metadata only."""
    if not isinstance(payload, dict) or not isinstance(payload.get('sessions'), list):
        return None, None, 'SESSION_LIST_SHAPE_UNRECOGNIZED'
    rows = payload['sessions']
    if not rows:
        return 0, None, 'NO_SESSIONS'
    for row in rows:
        identifier = row.get('session_id') if isinstance(row, dict) else None
        if isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', identifier):
            return len(rows), identifier, None
    return len(rows), None, 'SESSION_ID_SHAPE_UNRECOGNIZED'


def history_shape(payload):
    """Use existing cli.py::cmd_history contract; never return message bodies."""
    if not isinstance(payload, dict) or not isinstance(payload.get('chat_events'), list):
        return None, 'HISTORY_RESPONSE_SHAPE_UNRECOGNIZED'
    return len(payload['chat_events']), None


def validate_envelope_dir(root):
    # Only an explicitly selected private temporary directory is eligible for
    # credential input/cleanup. No arbitrary recursive deletion or symlinks.
    if not root.is_absolute() or root.parent != Path('/tmp') or not root.name.startswith('muse-live-'):
        raise ValueError('INVALID_TEMP_DIRECTORY')
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('INVALID_TEMP_DIRECTORY')
    if {x.name for x in root.iterdir()} - {'ephemeral.key', 'sealed.json', 'public.hex'}:
        raise ValueError('UNEXPECTED_TEMP_FILES')
    for name in ('ephemeral.key', 'sealed.json'):
        info = (root / name).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError('INVALID_TEMP_FILE')


def cleanup(root):
    # Known files only; unexpected contents leave the directory for inspection.
    for name in ('ephemeral.key', 'sealed.json', 'public.hex'):
        path = root / name
        if path.is_symlink() or path.is_file():
            path.unlink()
    root.rmdir()
    return not root.exists()


def probe(root, aad):
    import base64
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from muse_cli.login_state import restore, check_session
    from muse_cli.gateway import Gateway
    from muse_cli.readonly import read, classify
    login = session = gateway = None
    private = shared = key = plaintext = value = None
    stage = 'decrypt'
    report = {'auth_check': False, 'identity_read': False, 'identity_response_valid': False, 'sessions_read': False,
              'history_read': False, 'task_sent': False, 'persistent_login_written': False}
    # Validation is before any secret read. Validation failures deliberately do
    # not remove an untrusted or wrong directory.
    validate_envelope_dir(root)
    try:
        sealed = json.loads((root / 'sealed.json').read_text())
        private = X25519PrivateKey.from_private_bytes((root / 'ephemeral.key').read_bytes())
        shared = private.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(sealed['ephemeral_public'])))
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=aad).derive(shared)
        plaintext = AESGCM(key).decrypt(bytes.fromhex(sealed['nonce']), base64.b64decode(sealed['ciphertext'], validate=True), aad)
        value = json.loads(plaintext)
        login = restore(value)
        private = shared = key = plaintext = value = None
        stage = 'auth_check'
        session = check_session(login)
        report['auth_check'] = True
        stage = 'gateway_connect'
        gateway = Gateway(session._cookies)
        stage = 'identity'
        identity = read(gateway, 'identity')
        report['identity_read'] = True
        if not isinstance(identity, dict) or not identity or identity.get('ok') is False:
            report.update(result='stopped', stopped_at=stage, error_code='INVALID_IDENTITY_RESPONSE')
            return report
        report['identity_response_valid'] = True
        identity = None
        stage = 'sessions'
        payload = read(gateway, 'sessions')
        report['sessions_read'] = True
        count, identifier, reason = sessions_shape(payload)
        payload = None
        report['session_count'] = count
        if reason:
            report.update(result='partial', history_skipped=reason)
            return report
        stage = 'history'
        payload = read(gateway, 'history', identifier=identifier, limit=2)
        identifier = None
        report['history_read'] = True
        count, reason = history_shape(payload)
        payload = None
        report['history_entry_count'] = count
        if reason:
            report.update(result='partial', history_shape_error=reason)
        else:
            report['result'] = 'completed'
    except (KeyboardInterrupt, EOFError):
        report.update(result='stopped', stopped_at=stage, error_code='CANCELLED')
    except Exception as exc:
        report.update(result='stopped', stopped_at=stage,
                      error_code=safe_error_code(exc, stage, classify))
    finally:
        for obj in (gateway, session, login):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        private = shared = key = plaintext = value = None
        # Python does not guarantee physical zeroization; process exit releases
        # this short-lived process, and disk credentials were never serialized.
        try:
            report['temporary_directory_removed'] = cleanup(root)
        except Exception:
            report['temporary_directory_removed'] = False
            report['cleanup_error'] = 'LOCAL_CLEANUP_REQUIRES_INSPECTION'
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--envelope-dir', required=True, type=Path)
    p.add_argument('--aad', required=True, help='Non-secret envelope context agreed by producing agent')
    args = p.parse_args()
    try:
        report = probe(args.envelope_dir, args.aad.encode('ascii'))
    except Exception:
        print(json.dumps({'result': 'not_started', 'error_code': 'LOCAL_PREFLIGHT_FAILED',
                          'cleanup_attempted': False}))
        return 2
    print(json.dumps(report))
    return 0 if report.get('result') == 'completed' and report.get('temporary_directory_removed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
