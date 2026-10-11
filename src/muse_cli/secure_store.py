"""Explicit Linux Secret Service storage; never auto-select plaintext keyrings."""
import contextlib
import json
import os
import re
import stat
from .native_auth import LoginError

SERVICE = 'dotlink.muse-cli.linux.v1'


def configured_store(kind, profile, *, vault=None, allow_secret_access=False):
    if kind == 'plaintext-file':
        if not vault: raise LoginError('INVALID_INPUT')
        from .plaintext_store import PlaintextStore
        return PlaintextStore(vault, profile, allow_secret_access=allow_secret_access)
    if kind == 'encrypted-file':
        if not vault: raise LoginError('INVALID_INPUT')
        from .encrypted_store import EncryptedStore
        return EncryptedStore(vault, profile, allow_secret_access=allow_secret_access)
    if kind != 'secretservice' or vault is not None:
        raise LoginError('INVALID_INPUT')
    return SecretStore(profile, allow_secret_access=allow_secret_access)


class SecretStore:
    def __init__(self, profile='default', *, _backend=None, allow_secret_access=False):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', profile):
            raise LoginError('INVALID_INPUT')
        self.profile = profile
        self.allow_secret_access = allow_secret_access
        if _backend is not None:
            self.backend = _backend
            self.allow_secret_access = True  # exclusively injected test doubles
            return
        try:
            import sys
            if not sys.platform.startswith('linux'):
                raise RuntimeError()
            from .secret_service import ExistingSecretService
            self.backend = ExistingSecretService()
        except LoginError:
            raise
        except Exception:
            raise LoginError('STORE_UNAVAILABLE') from None

    def __repr__(self):
        return '<SecretStore redacted>'

    def load(self):
        self._require_access()
        try:
            raw = self.backend.get_password(SERVICE, self.profile)
        except LoginError:
            raise
        except Exception:
            raise LoginError('STORE_FAILED') from None
        if raw is None:
            return None
        try:
            if len(raw) > 262144:
                raise ValueError()
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get('version') != 1:
                raise ValueError()
            return value
        except Exception:
            raise LoginError('STORE_CORRUPT') from None

    def save(self, value):
        self._require_access()
        try:
            self.backend.set_password(SERVICE, self.profile, json.dumps(value))
        except LoginError:
            raise
        except Exception:
            raise LoginError('STORE_FAILED') from None

    def forget(self):
        self._require_access()
        try:
            self.backend.delete_password(SERVICE, self.profile)
        except LoginError:
            raise
        except Exception:
            raise LoginError('STORE_FAILED') from None

    def _require_access(self):
        if not self.allow_secret_access:
            raise LoginError('STORE_ACCESS_NOT_ENABLED')

    def preflight(self):
        root = os.environ.get('XDG_RUNTIME_DIR', '')
        try:
            if not root or not os.path.isabs(root):
                raise OSError()
            info = os.lstat(root)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise OSError()
        except (OSError, AttributeError):
            raise LoginError('STORE_USER_ACTION_REQUIRED') from None

    @contextlib.contextmanager
    def lock(self):
        """Only nonsecret lock files; Linux flock releases on process death."""
        fd = None
        try:
            import fcntl
            root = os.environ.get('XDG_RUNTIME_DIR', '')
            if not root or not os.path.isabs(root):
                raise LoginError('STORE_UNAVAILABLE')
            info = os.lstat(root)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise LoginError('STORE_UNAVAILABLE')
            path = os.path.join(root, 'dotlink-muse-' + self.profile + '.lock')
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise LoginError('STORE_UNAVAILABLE')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LoginError('BUSY') from None
            yield
        except LoginError:
            raise
        except (OSError, ImportError):
            raise LoginError('STORE_UNAVAILABLE') from None
        finally:
            if fd is not None:
                os.close(fd)
