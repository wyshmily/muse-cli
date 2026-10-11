"""Explicit plaintext storage in an operator-selected private Linux directory.

No fallback, discovery, permission repair, backups, or secret-bearing output.
The existing directory must be 0700; newly created files are 0600 from open.
"""
import json
import os
import stat
from .encrypted_store import EncryptedStore
from .native_auth import LoginError


class PlaintextStore(EncryptedStore):
    def __repr__(self):
        return '<PlaintextStore redacted>'

    def preflight(self):
        super().preflight()
        with self._directory() as fd:
            if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
                raise LoginError('STORE_USER_ACTION_REQUIRED')

    @staticmethod
    def _private_file(info):
        EncryptedStore._private_file(info)
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise LoginError('STORE_USER_ACTION_REQUIRED')

    def load(self):
        self._require_access()
        fd = None
        try:
            try:
                fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._dirfd)
            except FileNotFoundError:
                return None
            self._private_file(os.fstat(fd))
            with os.fdopen(fd, 'rb') as stream:
                fd = None
                raw = stream.read(262145)
            if len(raw) > 262144:
                raise ValueError()
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get('version') != 1:
                raise ValueError()
            return value
        except LoginError:
            raise
        except (ValueError, UnicodeError):
            raise LoginError('STORE_CORRUPT') from None
        except OSError:
            raise LoginError('STORE_FAILED') from None
        finally:
            if fd is not None:
                os.close(fd)

    def save(self, value):
        self._require_access()
        # Refuse damaged or insecure existing state before any replacement.
        self.load()
        name = '.muse-' + os.urandom(12).hex() + '.tmp'
        fd = None
        try:
            if not isinstance(value, dict) or value.get('version') != 1:
                raise ValueError()
            raw = json.dumps(value, allow_nan=False).encode('utf-8')
            if len(raw) > 262144:
                raise ValueError()
            fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=self._dirfd)
            self._private_file(os.fstat(fd))
            with os.fdopen(fd, 'wb') as stream:
                fd = None
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Revalidate the named target after writing, before atomic replace.
            self.load()
            os.replace(name, self.path.name, src_dir_fd=self._dirfd, dst_dir_fd=self._dirfd)
            os.fsync(self._dirfd)
        except LoginError:
            raise
        except (OSError, ValueError, TypeError):
            raise LoginError('STORE_FAILED') from None
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(name, dir_fd=self._dirfd)
            except FileNotFoundError:
                pass
