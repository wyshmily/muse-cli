"""Small, reviewed metadata queries. No arbitrary routes, filesystem reads or URLs."""
import re
from .readonly import ReadError, classify

CONTRACTS = {
    'model': ('model.get', 'GET', '/model'),
    'computer-context': ('computer.context', 'GET', '/api/computer/context'),
    'voice-catalog': ('voice.catalog', 'GET', '/api/voice/catalog'),
    'voice-filters': ('voice.catalog_filters', 'GET', '/api/voice/catalog/filters'),
    'connector-marketplace': ('connectors.homepage', 'GET', '/connectors/homepage'),
    # This POST is the website's bounded library listing query, not a write.
    'library': ('fs.library', 'POST', '/fs/library'),
}


def obj(value):
    if not isinstance(value, dict):
        raise ReadError('INVALID_RESPONSE')
    return value


def array(value):
    if not isinstance(value, list) or len(value) > 10000:
        raise ReadError('INVALID_RESPONSE')
    return value


def string(value, limit=500):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ReadError('INVALID_RESPONSE')
    if re.search(r'(?i)(?:[a-z][a-z0-9+.-]*://|(?:authorization|cookie|password|access[_ -]?token|refresh[_ -]?token|api[_ -]?key|secret|token)\s*[:=]|\bbearer\s+)', value):
        raise ReadError('INVALID_RESPONSE')
    return value


def integer(value):
    if type(value) is not int or value < 0:
        raise ReadError('INVALID_RESPONSE')
    return value


def boolean(value):
    if type(value) is not bool:
        raise ReadError('INVALID_RESPONSE')
    return value


def identifier(value):
    value = string(value, 200)
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', value):
        raise ReadError('INVALID_RESPONSE')
    return value


def model_id(value):
    value = string(value, 200)
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+(?:/[A-Za-z0-9_.:-]+)+', value):
        raise ReadError('INVALID_RESPONSE')
    return value


def fields(value, schema):
    value = obj(value)
    return {k: None if value[k] is None else check(value[k])
            for k, check in schema.items() if k in value}


def enum(value, choices):
    if value not in choices:
        raise ReadError('INVALID_RESPONSE')
    return value


def _model(data):
    visibility = data.get('model_identity_visibility', 'visible')
    if visibility not in ('visible', 'hidden'):
        raise ReadError('INVALID_RESPONSE')
    if visibility == 'hidden':
        return {'model_identity_visibility': 'hidden'}
    result = fields(data, {'selected_model': model_id, 'default_model': model_id,
                          'generation': integer, 'display_name': string})
    result['model_identity_visibility'] = 'visible'
    result['available_models'] = [fields(v, {'id': model_id, 'provider': string,
        'model': string, 'context_window_tokens': integer, 'display_name': string,
        'preview_model': boolean}) for v in array(data.get('available_models', []))]
    return result


def _computer(data):
    tasks = array(data.get('tasks'))
    return {'task_count': len(tasks), 'tasks': [fields(v, {
        'browser_task_id': identifier, 'activity_thread_id': identifier,
        'session_id': identifier, 'status': identifier,
        'preview_available': boolean, 'queue_position': integer,
        'updated_at_ms': integer, 'control_owner': lambda v: enum(v, ('agent', 'user')),
        'owner_kind': lambda v: enum(v, ('user', 'main_agent', 'cron'))}) for v in tasks]}


def _voices(data):
    result = fields(data, {'total': integer, 'limit': integer, 'offset': integer})
    rows = []
    for voice in array(data.get('voices')):
        row = fields(voice, {'id': identifier, 'gender': string, 'accent': string,
                            'tone': string, 'source': identifier, 'is_selected': boolean})
        # A pinned selected voice may be custom. Do not return its free text.
        if row.get('source', '').lower() == 'library' and 'name' in voice:
            row['name'] = string(voice['name'])
        rows.append(row)
    result['voices'] = rows
    return result


def _filters(data):
    options = obj(data.get('filter_options'))
    return {'filter_options': {key: [fields(v, {'value': string, 'label': string,
                                               'count': integer}) for v in array(options[key])]
                               for key in ('gender', 'accent', 'tone') if key in options}}


def _connector(value):
    row = fields(value, {'id': identifier, 'state': identifier,
                        'supports_multiple_accounts': boolean, 'is_custom': boolean,
                        'needs_reauth': boolean, 'management_kind': identifier})
    if row.get('is_custom') is False and 'name' in value:
        row['name'] = string(value['name'])
    return row


def _marketplace(data):
    result = fields(data, {'version': string, 'custom_count': integer})
    result['featured'] = [_connector(v) for v in array(data.get('featured'))]
    result['categories'] = []
    for category in array(data.get('categories')):
        row = fields(category, {'id': identifier, 'title': string})
        row['connectors'] = [_connector(v) for v in array(category.get('connectors'))]
        result['categories'].append(row)
    return result


def _path(value):
    value = string(value, 4096)
    if '://' in value:
        raise ReadError('INVALID_RESPONSE')
    return value


def _library(data):
    return {**fields(data, {'total': integer, 'has_more': boolean}),
            'entries': [fields(v, {'name': string, 'path': _path, 'size': integer,
                                   'modified_ms': integer}) for v in array(data.get('entries'))]}


NORMALIZERS = {'model': _model, 'computer-context': _computer,
               'voice-catalog': _voices, 'voice-filters': _filters,
               'connector-marketplace': _marketplace, 'library': _library}


def read_metadata(gateway, command, *, limit=20, offset=0, preset='artifacts'):
    if command not in CONTRACTS:
        raise ReadError('UNSUPPORTED_READ')
    if not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 100000:
        raise ReadError('INVALID_LIMIT')
    if preset not in ('artifacts', 'media', 'recents'):
        raise ReadError('INVALID_ARGUMENTS')
    method, verb, path = CONTRACTS[command]
    from .gateway import ROUTES
    route = ROUTES.get(method, {})
    if route.get('http') != verb or route.get('path') != path:
        raise ReadError('READ_CONTRACT_CHANGED')
    kwargs = {}
    if command == 'voice-catalog':
        kwargs['query'] = {'source': 'library', 'limit': limit, 'offset': offset, 'pin_selected': 'true'}
    elif command == 'voice-filters':
        kwargs['query'] = {'source': 'library'}
    elif command == 'connector-marketplace':
        kwargs['query'] = {'preview_limit': min(limit, 5)}
    elif command == 'library':
        kwargs['body'] = {'preset': preset, 'limit': limit, 'offset': offset}
    try:
        result = NORMALIZERS[command](obj(gateway.call_json(method, **kwargs)))
        if command in ('voice-catalog', 'library'):
            key = 'voices' if command == 'voice-catalog' else 'entries'
            if len(result[key]) > limit:
                raise ReadError('INVALID_RESPONSE')
        if command == 'computer-context':
            result['tasks'] = result['tasks'][:limit]
            result['returned_tasks'] = len(result['tasks'])
        return result
    except ReadError:
        raise
    except Exception as exc:
        raise ReadError(classify(exc)) from None
