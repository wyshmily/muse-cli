"""Bounded structural diagnostics. Never include server-supplied strings/keys."""
_KNOWN = frozenset(('flow', 'registration_state', 'error_type', 'error_code',
                   'error', 'type', 'success', 'result', 'data', 'account',
                   'user', 'accounts', 'csrf_token', 'access_token',
                   'auth_meta_session', 'frl_access_token', 'frl_account_id',
                   'redirect_to', 'checkpoint_url'))


def redact(value):
    """Strip credential fields and URL queries from read-only structured output."""
    import re
    if isinstance(value, dict):
        return {k: '<redacted>' if re.search(r'token|cookie|secret|password|authorization', k, re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'(https?://[^\s?"<>]+)\?[^\s"<>]+', r'\1?<redacted>', value)
    return value


def response_shape(value):
    def shape(v, depth=0):
        if depth >= 3:
            return {'type': type(v).__name__}
        if isinstance(v, dict):
            return {'type': 'object', 'fields': [
                {'field': k if k in _KNOWN else '<unknown>', 'shape': shape(x, depth+1)}
                for k, x in list(v.items())[:32]], 'count': len(v)}
        if isinstance(v, list):
            return {'type': 'array', 'count': len(v),
                    'items': [shape(x, depth+1) for x in v[:3]]}
        return {'type': 'null' if v is None else type(v).__name__}
    return shape(value)


def stored_diagnostics(values):
    """Revalidate diagnostic strings before displaying persisted structures."""
    types = {'object', 'array', 'null', 'str', 'int', 'float', 'bool', 'dict', 'list', 'non-json'}
    def clean(v, depth=0):
        if depth > 10 or not isinstance(v, dict):
            return {}
        result = {}
        for k, x in v.items():
            if k == 'field': result[k] = x if isinstance(x, str) and x in _KNOWN else '<unknown>'
            elif k == 'type': result[k] = x if isinstance(x, str) and x in types else 'unknown'
            elif k in ('count', 'http_status') and type(x) is int: result[k] = max(0, min(x, 1000000))
            elif k in ('body', 'shape'): result[k] = clean(x, depth+1)
            elif k in ('fields', 'items') and isinstance(x, list): result[k] = [clean(y, depth+1) for y in x[:32]]
        return result
    return [clean(v) for v in values[:8]] if isinstance(values, list) else []
