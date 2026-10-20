"""Verify a delivered source manifest. Offline; no install, download or credentials."""
import hashlib
import json
import re
from pathlib import Path
import sys

def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'SOURCE-MANIFEST.json').read_text())
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or not isinstance(manifest.get('sha256'), dict) or not manifest['sha256']:
        raise ValueError('INVALID_MANIFEST')
    for name, digest in manifest['sha256'].items():
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('INVALID_MANIFEST')
        path = root / rel
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('INVALID_SOURCE_PATH')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('SOURCE_MISMATCH')
    return len(manifest['sha256'])

if __name__ == '__main__':
    try:
        count = verify(sys.argv[1] if len(sys.argv) == 2 else Path(__file__).resolve().parents[1])
        print(json.dumps({'verified_files': count, 'network_used': False, 'credentials_used': False}))
    except (OSError, ValueError, TypeError):
        print('SOURCE_VERIFICATION_FAILED', file=sys.stderr)
        sys.exit(2)
