"""Opt-in encrypted file. Passphrase is entered privately, never persisted.

No directories are created or chmodded. Linux private durable storage and a
private user-operated terminal must be provided and approved by the operator.
"""
import contextlib
import json
import os
from pathlib import Path
import re
import stat
from .native_auth import LoginError
from .secure_store import SecretStore

MAGIC = b'DOTMUSE1'


class EncryptedStore(SecretStore):
    def __init__(self, path, profile='default', *, allow_secret_access=False, _read=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', profile):
            raise LoginError('INVALID_INPUT')
        self.path = Path(path)
        self.profile, self.allow_secret_access = profile, allow_secret_access
        self._dirfd = self._key = self._salt = None
        self._read = _read
        self.preflight()

    @contextlib.contextmanager
    def _directory(self):
        fd = None
        try:
            if os.name != 'posix' or not self.path.is_absolute() or self.path.parent.resolve(strict=True) != self.path.parent:
                raise OSError()
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise OSError()
            yield fd
        except OSError:
            raise LoginError('STORE_USER_ACTION_REQUIRED') from None
        finally:
            if fd is not None: os.close(fd)

    @staticmethod
    def _private_file(info):
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise LoginError('STORE_USER_ACTION_REQUIRED')

    def preflight(self):
        with self._directory() as fd:
            try:
                info = os.stat(self.path.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            self._private_file(info)

    @contextlib.contextmanager
    def lock(self):
        import fcntl
        with self._directory() as directory:
            fd = None
            try:
                fd = os.open(self.path.name+'.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                self._private_file(os.fstat(fd))
                try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: raise LoginError('BUSY') from None
                self._dirfd = directory
                yield
            finally:
                self._dirfd = self._key = self._salt = None
                if fd is not None: os.close(fd)

    def _require_access(self):
        super()._require_access()
        if self._dirfd is None:
            raise LoginError('STORE_ACCESS_NOT_ENABLED')

    def _derive(self, salt, *, new=False):
        if self._key is not None and self._salt == salt:
            return self._key
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        from .native_login import hidden_input
        reader = self._read or hidden_input
        password = reader('Vault passphrase (hidden; never saved): ')
        try:
            if not isinstance(password, str) or len(password) < 12:
                raise LoginError('INVALID_INPUT')
            if new and password != reader('Confirm vault passphrase (hidden): '):
                raise LoginError('INVALID_INPUT')
            self._key = Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(password.encode())
            self._salt = salt
            return self._key
        finally:
            password = None

    def load(self):
        self._require_access()
        fd = None
        try:
            try: fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._dirfd)
            except FileNotFoundError: return None
            self._private_file(os.fstat(fd))
            blob = os.read(fd, 262145)
            if len(blob) > 262144 or len(blob) < 52 or not blob.startswith(MAGIC):
                raise LoginError('STORE_CORRUPT')
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = self._derive(blob[8:24])
            raw = AESGCM(key).decrypt(blob[24:36], blob[36:], MAGIC+self.profile.encode())
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get('version') != 1:
                raise LoginError('STORE_CORRUPT')
            return value
        except LoginError: raise
        except Exception:
            self._key = self._salt = None
            raise LoginError('VAULT_UNLOCK_FAILED') from None
        finally:
            if fd is not None: os.close(fd)

    def save(self, value):
        self._require_access()
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        # Authenticate any existing file before replacement; never overwrite a
        # corrupt vault or a vault for which the supplied passphrase is wrong.
        if self._key is None:
            if self.load() is None: self._derive(os.urandom(16), new=True)
        raw = json.dumps(value).encode()
        if len(raw) > 250000: raise LoginError('STORE_FAILED')
        nonce = os.urandom(12)
        blob = MAGIC+self._salt+nonce+AESGCM(self._key).encrypt(nonce, raw, MAGIC+self.profile.encode())
        name = '.muse-'+os.urandom(12).hex()+'.tmp'
        fd = None
        try:
            fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=self._dirfd)
            with os.fdopen(fd, 'wb') as out:
                fd = None
                out.write(blob)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path.name, src_dir_fd=self._dirfd, dst_dir_fd=self._dirfd)
            os.fsync(self._dirfd)
        except OSError:
            raise LoginError('STORE_FAILED') from None
        finally:
            if fd is not None: os.close(fd)
            try: os.unlink(name, dir_fd=self._dirfd)
            except FileNotFoundError: pass

    def forget(self):
        self._require_access()
        if self.load() is not None:
            os.unlink(self.path.name, dir_fd=self._dirfd)
            os.fsync(self._dirfd)
