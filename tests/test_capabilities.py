import contextlib
import io
import json
import unittest
from unittest.mock import patch
from muse_cli.capabilities import capabilities
from muse_cli.readonly import main


class CatalogTests(unittest.TestCase):
    def test_offline_inventory_does_not_access_credentials(self):
        out = io.StringIO()
        with patch('muse_cli.secure_store.configured_store') as store, contextlib.redirect_stdout(out):
            self.assertEqual(main(['capabilities', '--id', 'voice.', '--limit', '100']), 0)
        store.assert_not_called()
        result = json.loads(out.getvalue())
        self.assertTrue(result['routes'])
        self.assertTrue(all(r['method'].startswith('voice.') for r in result['routes']))
        self.assertTrue(all(r['execution_authorized'] is False for r in result['routes']))
        self.assertTrue(all(r['verification']=='static_confirmed' for r in result['routes']))

    def test_list_is_bounded_and_not_runtime_allowlist(self):
        result = capabilities(limit=2)
        self.assertEqual(result['returned'],2)
        self.assertGreater(result['total_matches'], result['returned'])
        row=capabilities(prefix='ssh.operator.enable')['routes'][0]
        self.assertEqual(row['http'], 'POST')
        self.assertFalse(row['runtime_route_available'])
        self.assertFalse(row['execution_authorized'])

    def test_no_duplicate_methods_or_implicit_permissions(self):
        from pathlib import Path
        from muse_cli import capabilities as module
        rows=json.loads(Path(module.__file__).with_name('web_route_catalog.json').read_text())['routes']
        self.assertEqual(len(rows),len({r['method'] for r in rows}))
        self.assertTrue(all(r['source'].startswith('https://muse.ai/_next/static/chunks/') for r in rows))


if __name__ == '__main__': unittest.main()
