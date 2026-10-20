"""Offline observed-route inventory, deliberately separate from execution routes."""
import json
from pathlib import Path
from .readonly import ReadError, safe_id


def capabilities(*, prefix=None, limit=20):
    if not 1 <= limit <= 100:
        raise ReadError('INVALID_LIMIT')
    if prefix is not None:
        safe_id(prefix)
    catalog = json.loads(Path(__file__).with_name('web_route_catalog.json').read_text())
    rows = [row for row in catalog['routes'] if prefix is None or row['method'].startswith(prefix)]
    from .gateway import ROUTES
    result = []
    for row in rows[:limit]:
        item = dict(row)
        item['runtime_route_available'] = row['method'] in ROUTES
        item['execution_authorized'] = False
        item['runtime_verified'] = row['method'] in {'vm.health', 'vm.enrollment_health',
            'model.get', 'computer.context', 'voice.catalog', 'voice.catalog_filters',
            'connectors.homepage', 'fs.library'}
        if row['method'] == 'fs.library':
            item['runtime_validation_scope'] = 'preset=artifacts only; media/recents statically confirmed' 
        item['read_safety_review_required'] = True
        result.append(item)
    return {'observed_on': catalog['observed_on'], 'scope': catalog['scope'],
            'total_matches': len(rows), 'returned': len(result), 'routes': result}
