import contextlib
import io
import json
import unittest
from unittest.mock import patch
from muse_cli.discovery import COMMANDS, discover, describe
from muse_cli.readonly import main, ReadError

class DiscoveryTests(unittest.TestCase):
    def test_groups_cover_every_command_once(self):
        rows=[c['command'] for g in discover()['groups'] for c in g['commands']]
        self.assertEqual(set(rows),set(COMMANDS)); self.assertEqual(len(rows),len(set(rows)))
    def test_details(self):
        for name in COMMANDS:
            self.assertIn('example',describe(name)); self.assertIn('storage_effect',describe(name))
        self.assertEqual(describe('library')['parameters'][-1]['choices'],['artifacts','media','recents'])
        self.assertIn('Legacy',describe('history')['storage_effect'])
    def test_unknown_not_echoed(self):
        with self.assertRaisesRegex(ReadError,'UNKNOWN_COMMAND'): describe('Bearer private')
        with self.assertRaisesRegex(ReadError,'UNKNOWN_GROUP'): discover('private')
    def test_offline_never_opens_store(self):
        with patch('muse_cli.secure_store.configured_store',side_effect=AssertionError('accessed')):
            for argv in [['discover'],['discover','--group','account'],['describe','quota']]:
                out=io.StringIO()
                with contextlib.redirect_stdout(out): self.assertEqual(main(argv),0)
                self.assertEqual(json.loads(out.getvalue())['schema_version'],1)
    def test_invalid_combinations(self):
        for argv in [['describe'],['describe','quota','--group','account'],['discover','quota'],['quota','--group','account'],['discover','--id','x']]:
            with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(argv),2)
    def test_parser_registry_match_and_no_gateway(self):
        from muse_cli import readonly
        seen={}
        original=readonly.Parser.add_argument
        def capture(parser,*args,**kwargs):
            if args == ('command',): seen['commands']=set(kwargs['choices'])
            return original(parser,*args,**kwargs)
        with patch.object(readonly.Parser,'add_argument',capture), patch('muse_cli.gateway.Gateway',side_effect=AssertionError('gateway accessed')):
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(main(['discover']),0)
        self.assertEqual(seen['commands'],set(COMMANDS))
