"""Pinned, observed read-only Next action. No recovery, purchases, or retries."""
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import quote
from .readonly import ReadError, classify

BASE = 'https://muse.ai/'
DEPENDENCY = '/_next/static/chunks/0id24ziqkc-v9.js'
ACTION_ASSET = '/_next/static/chunks/42t7iubel_7xb.js'
ACTION_ID = '4029ac5c4bd03136487d91ebde5de39c64b35229b4'


def _response(response, content_type=None):
    if response.status_code != 200:
        raise ReadError({401: 'AUTH_INVALID', 403: 'FORBIDDEN', 429: 'RATE_LIMITED',
                         404: 'READ_CONTRACT_CHANGED'}.get(response.status_code, 'API_FAILED'))
    if content_type and not response.headers.get('content-type', '').startswith(content_type):
        raise ReadError('READ_CONTRACT_CHANGED')
    if len(response.text) > 8_000_000:
        raise ReadError('INVALID_RESPONSE')
    return response.text


def _trim_tree(tree, depth=0):
    if depth > 30 or not isinstance(tree, list) or len(tree) < 2 or not isinstance(tree[1], dict):
        raise ReadError('READ_CONTRACT_CHANGED')
    segment = tree[0]
    if isinstance(segment, str):
        if segment.startswith('$'):
            raise ReadError('READ_CONTRACT_CHANGED')
        if segment.startswith('__PAGE__?'):
            segment = '__PAGE__'
    elif isinstance(segment, list) and len(segment) >= 3:
        if any(not isinstance(s, str) or s.startswith('$') for s in segment[:3]):
            raise ReadError('READ_CONTRACT_CHANGED')
        segment = segment[:3] + [None]
    else:
        raise ReadError('READ_CONTRACT_CHANGED')
    result = [segment, {k: _trim_tree(v, depth+1) for k, v in tree[1].items()}]
    if len(tree) > 3 and tree[3] not in (None, '$undefined', False, ''):
        if not isinstance(tree[3], str) or tree[3].startswith('$'):
            raise ReadError('READ_CONTRACT_CHANGED')
        result += [None, tree[3]]
    if len(tree) > 4 and tree[4] != '$undefined':
        if type(tree[4]) is not int:
            raise ReadError('READ_CONTRACT_CHANGED')
        result += [None] * (5-len(result))
        result[4] = tree[4]
    return result


def page_context(html):
    deployment = re.search(r'<html[^>]+data-dpl-id="([A-Za-z0-9_-]+)"', html)
    if not deployment or DEPENDENCY not in html:
        raise ReadError('READ_CONTRACT_CHANGED')
    chunks = []
    decoder = json.JSONDecoder()
    for match in re.finditer(r'self\.__next_f\.push\(', html):
        value, _ = decoder.raw_decode(html[match.end():])
        if isinstance(value, list) and len(value) == 2 and value[0] == 1 and isinstance(value[1], str):
            chunks.append(value[1])
    roots = [json.loads(line[2:]) for line in ''.join(chunks).splitlines() if line.startswith('0:')]
    if len(roots) != 1:
        raise ReadError('READ_CONTRACT_CHANGED')
    tree = _trim_tree(roots[0]['f'][0][0])
    return deployment.group(1), quote(json.dumps(tree, separators=(',', ':')), safe="~!*'()-._")


def action_result(text):
    """Only support observed plain JSON Flight records and a root action ref."""
    records = {}
    for line in text.splitlines():
        if not line:
            continue
        match = re.fullmatch(r'([0-9a-f]+):(.*)', line)
        if not match or match.group(1) in records:
            raise ReadError('READ_CONTRACT_CHANGED')
        records[match.group(1)] = json.loads(match.group(2))
    root = records.get('0')
    if not isinstance(root, dict):
        raise ReadError('READ_CONTRACT_CHANGED')
    result = root.get('a')
    if isinstance(result, str) and re.fullmatch(r'\$@?[0-9a-f]+', result):
        result = records.get(result.lstrip('$@'))
    if not isinstance(result, dict):
        raise ReadError('READ_CONTRACT_CHANGED')
    if result.get('sessionRecovery') is not None:
        raise ReadError('AUTH_RECOVERY_REQUIRED')
    if result.get('success') is not True:
        raise ReadError('API_FAILED')
    subscription = result.get('subscription')
    if not isinstance(subscription, dict):
        raise ReadError('INVALID_RESPONSE')
    usage = subscription.get('usage')
    if not isinstance(usage, dict) or not isinstance(usage.get('state'), str):
        raise ReadError('INVALID_RESPONSE')
    clean = {}
    for key in ('state', 'quotaStatus'):
        value = usage.get(key)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch('[A-Z_]{1,60}', value):
                raise ReadError('INVALID_RESPONSE')
            clean[key] = value
    for key in ('percentUsed', 'resetsAt'):
        value = usage.get(key)
        if value is not None:
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ReadError('INVALID_RESPONSE')
            clean[key] = value
    if 'resetsAt' in clean:
        value = clean['resetsAt']
        if type(value) is not int or not 1_000_000_000 <= value <= 253_402_300_799:
            raise ReadError('INVALID_RESPONSE')
        clean['resetsAtUTC'] = datetime.fromtimestamp(value, timezone.utc).isoformat()
    result = {'usage': clean}
    for key in ('topupBalance', 'topupTotal'):
        value = subscription.get(key)
        if value is not None:
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ReadError('INVALID_RESPONSE')
            result[key] = value
    # Do not expose account/billing records, server error text, or action URLs.
    return result


def read_quota(login):
    try:
        headers = dict(login.headers)
        html = _response(login.http.get(BASE, headers=headers, timeout=20, allow_redirects=False))
        deployment, tree = page_context(html)
        deps = _response(login.http.get(BASE.rstrip('/') + DEPENDENCY, timeout=20, allow_redirects=False))
        if ACTION_ASSET.rsplit('/', 1)[1] not in deps:
            raise ReadError('READ_CONTRACT_CHANGED')
        source = _response(login.http.get(BASE.rstrip('/') + ACTION_ASSET, timeout=20, allow_redirects=False))
        actions = re.findall(r'createServerReference\)\("([a-f0-9]{42})",([A-Za-z_$][A-Za-z0-9_$]*)\.callServer,void 0,\2\.findSourceMapURL,"fetchSubscriptionAction"\)', source)
        if len(actions) != 1 or actions[0][0] != ACTION_ID:
            raise ReadError('READ_CONTRACT_CHANGED')
        headers.update({'Accept': 'text/x-component', 'Next-Action': ACTION_ID,
                        'Next-Router-State-Tree': tree, 'x-deployment-id': deployment,
                        'Content-Type': 'text/plain;charset=UTF-8'})
        response = login.http.post(BASE, headers=headers, data='[{"includeAgreement":false}]',
                                   timeout=20, allow_redirects=False)
        return action_result(_response(response, 'text/x-component'))
    except ReadError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        raise ReadError('READ_CONTRACT_CHANGED') from None
    except Exception as exc:
        raise ReadError(classify(exc)) from None
