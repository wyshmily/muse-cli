"""Observed Muse website GET queries; never leases, wakes, or resets a VM."""
import re
from .readonly import ReadError, classify, safe_id

WEB_QUERIES = {'vm-status': '/api/session?vm_state=live'}
_VM_FIELDS = {'id', 'vm_id', 'vm_state', 'vm_state_source', 'vm_type', 'is_preferred'}


def _vm_fields(value):
    if not isinstance(value, dict):
        raise ReadError('INVALID_RESPONSE')
    result = {}
    for key in _VM_FIELDS & value.keys():
        item = value[key]
        if key == 'is_preferred':
            if type(item) is not bool:
                raise ReadError('INVALID_RESPONSE')
        elif key in ('id', 'vm_id'):
            try:
                safe_id(item)
            except ReadError:
                raise ReadError('INVALID_RESPONSE') from None
        elif item is not None and (not isinstance(item, str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', item)):
            raise ReadError('INVALID_RESPONSE')
        result[key] = item
    return result


def read_web(http, command):
    """http is the existing login's in-memory HTTP session, not a new login."""
    if command not in WEB_QUERIES:
        raise ReadError('UNSUPPORTED_READ')
    try:
        response = http.get('https://muse.ai' + WEB_QUERIES[command],
                            timeout=20, allow_redirects=False,
                            headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'})
        status = response.status_code
        if status != 200:
            raise ReadError({401: 'AUTH_INVALID', 403: 'FORBIDDEN', 404: 'NOT_FOUND',
                             429: 'RATE_LIMITED'}.get(status, 'API_FAILED'))
        data = response.json()
        if not isinstance(data, dict):
            raise ReadError('INVALID_RESPONSE')
        if command == 'vm-status':
            if data.get('status') not in ('assigned', 'none'):
                raise ReadError('INVALID_RESPONSE')
            if data['status'] == 'assigned' and (not isinstance(data.get('vms'), list)
                    or not data['vms'] or any(not isinstance(v, dict) or not v.get('id')
                                             for v in data['vms'])):
                raise ReadError('INVALID_RESPONSE')
            result = {'status': data['status'], **_vm_fields(data)}
            if 'vms' in data:
                if not isinstance(data['vms'], list):
                    raise ReadError('INVALID_RESPONSE')
                result['vms'] = [_vm_fields(v) for v in data['vms']]
            return result
    except ReadError:
        raise
    except (ValueError, TypeError):
        raise ReadError('INVALID_RESPONSE') from None
    except Exception as exc:
        raise ReadError(classify(exc)) from None
