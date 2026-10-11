"""Real SecretStorage objects over a synthetic D-Bus transport; never real IPC."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from muse_cli.native_auth import LoginError, MemorySession
from muse_cli.secure_store import SecretStore


class Errors:
    def fails(self, code, fn):
        with self.assertRaises(LoginError) as cm: fn()
        self.assertEqual(cm.exception.code, code)


@unittest.skipUnless(importlib.util.find_spec('secretstorage'), 'SecretStorage installed on Linux')
class ServiceTests(Errors, unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from jeepney.low_level import HeaderFields, MessageType
        from secretstorage.dhcrypto import Session
        from secretstorage.util import format_secret
        self.calls=[]
        self.present=True
        self.alias='/org/freedesktop/secrets/collection/synthetic'
        self.collection_locked=False
        self.item_locked=False
        self.items=True
        self.prompt=False
        self.race=False
        self.remote_lock=False
        self.remote=None
        self.payload=json.dumps({'version':1,'fixture':'synthetic only'})
        outer=self
        class Bus:
            def close(self): pass
            def send_and_get_reply(self, msg, *a, **kw):
                member=msg.header.fields[HeaderFields.member]
                destination=msg.header.fields[HeaderFields.destination]
                path=msg.header.fields[HeaderFields.path]
                outer.calls.append((member,destination))
                if member in ('Unlock','CreateCollection','Prompt','Dismiss'):
                    raise AssertionError('forbidden wire mutation '+member)
                if member=='NameHasOwner': body=(outer.present,)
                elif member=='GetNameOwner': body=(':1.42',)
                elif member=='ReadAlias': body=(outer.alias,)
                elif member=='Get':
                    prop=msg.body[1]
                    if prop=='Label': body=(('s','synthetic'),)
                    elif prop=='Locked': body=(('b',outer.item_locked if '/item/' in path else outer.collection_locked),)
                    else: raise AssertionError(prop)
                elif member=='SearchItems': body=(['/org/freedesktop/secrets/item/synthetic'] if outer.items else [],)
                elif member=='OpenSession':
                    from secretstorage.defines import ALGORITHM_DH
                    self_test=msg.body[0]
                    if self_test != ALGORITHM_DH: raise AssertionError('plaintext negotiation')
                    outer.remote=Session()
                    remote_public=outer.remote.my_public_key.to_bytes(128,'big')
                    outer.remote.set_server_public_key(int.from_bytes(msg.body[1][1],'big'))
                    outer.remote.object_path='/org/freedesktop/secrets/session/synthetic'
                    body=(('ay',remote_public),outer.remote.object_path)
                    if outer.race: outer.collection_locked=True
                elif member=='GetSecret':
                    if outer.remote_lock:
                        return SimpleNamespace(header=SimpleNamespace(message_type=MessageType.error,
                            fields={HeaderFields.error_name:'org.freedesktop.Secret.Error.IsLocked'}),body=('synthetic lock race',))
                    body=(format_secret(outer.remote,outer.payload.encode(),'text/plain'),)
                elif member=='SetSecret': body=()
                elif member=='CreateItem': body=('/' if outer.prompt else '/org/freedesktop/secrets/item/synthetic', '/prompt/synthetic' if outer.prompt else '/')
                elif member=='Delete': body=('/prompt/synthetic' if outer.prompt else '/',)
                else: raise AssertionError(member)
                return SimpleNamespace(header=SimpleNamespace(message_type=MessageType.method_return),body=body)
        self.mock=patch('secretstorage.dbus_init',side_effect=lambda:Bus())
        self.mock.start()
        self.platform=patch('sys.platform','linux')
        self.platform.start()
        self.addCleanup(self.mock.stop)
        self.addCleanup(self.platform.stop)

    def test_preflight_uses_only_metadata_and_blocks_secret_methods(self):
        store=SecretStore()
        self.assertTrue(set(m for m,_ in self.calls) <= {'NameHasOwner','GetNameOwner','ReadAlias','Get'})
        self.fails('STORE_ACCESS_NOT_ENABLED',store.load)
        self.fails('STORE_ACCESS_NOT_ENABLED',lambda:store.save({'version':1}))
        self.fails('STORE_ACCESS_NOT_ENABLED',store.forget)
        for member,destination in self.calls:
            if member not in ('NameHasOwner','GetNameOwner'):
                self.assertEqual(destination,':1.42')

    def test_absent_provider_never_activated(self):
        self.present=False
        self.fails('STORE_UNAVAILABLE',SecretStore)
        self.assertEqual(self.calls,[('NameHasOwner','org.freedesktop.DBus')])

    def test_missing_default_collection_never_created(self):
        self.alias='/'
        self.fails('STORE_USER_ACTION_REQUIRED',SecretStore)
        self.assertNotIn('CreateCollection',[m for m,_ in self.calls])

    def test_locked_collection_never_unlocked(self):
        self.collection_locked=True
        self.fails('STORE_USER_ACTION_REQUIRED',SecretStore)

    def test_relocks_after_preflight_blocks_every_operation(self):
        store=SecretStore(allow_secret_access=True)
        self.collection_locked=True
        for action in (store.load, lambda:store.save({'version':1}), store.forget):
            self.fails('STORE_USER_ACTION_REQUIRED',action)
        self.assertFalse({'GetSecret','SetSecret','CreateItem','Delete'} & {m for m,_ in self.calls})

    def test_locked_item_never_unlocked(self):
        store=SecretStore(allow_secret_access=True)
        self.item_locked=True
        self.fails('STORE_USER_ACTION_REQUIRED',store.load)
        self.assertNotIn('OpenSession',[m for m,_ in self.calls])

    def test_race_relock_before_secret_access_fails_closed(self):
        store=SecretStore(allow_secret_access=True)
        self.race=True
        self.fails('STORE_USER_ACTION_REQUIRED',store.load)
        self.assertNotIn('GetSecret',[m for m,_ in self.calls])
        self.race=self.collection_locked=False
        self.remote_lock=True
        self.fails('STORE_USER_ACTION_REQUIRED',store.load)
        self.assertEqual([m for m,_ in self.calls].count('GetSecret'),1)

    def test_approved_read_uses_real_dependency_decryption_without_unlock(self):
        store=SecretStore(allow_secret_access=True)
        self.assertEqual(store.load(),json.loads(self.payload))
        self.assertIn('GetSecret',[m for m,_ in self.calls])

    def test_approved_update_does_not_use_keyring_helpers(self):
        store=SecretStore(allow_secret_access=True)
        store.save({'version':1})
        self.assertIn('SetSecret',[m for m,_ in self.calls])

    def test_create_and_delete_prompt_never_executed(self):
        store=SecretStore(allow_secret_access=True)
        self.items=False
        self.prompt=True
        self.fails('STORE_USER_ACTION_REQUIRED',lambda:store.save({'version':1}))
        self.items=True
        self.fails('STORE_USER_ACTION_REQUIRED',store.forget)
        self.assertNotIn('Prompt',[m for m,_ in self.calls])


@unittest.skipUnless(os.name=='posix', 'Linux private directory and flock')
class VaultTests(Errors, unittest.TestCase):
    def setUp(self):
        from muse_cli.encrypted_store import EncryptedStore
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        os.chmod(self.root,0o700)
        self.path=self.root/'session.enc'
        self.make=lambda **kw:EncryptedStore(str(self.path),**kw)
        self.password='synthetic fixture passphrase'

    def test_preflight_does_not_create_read_or_prompt(self):
        store=self.make(_read=lambda _:self.fail('prompt'))
        store.preflight()
        self.assertEqual(list(self.root.iterdir()),[])
        self.fails('STORE_ACCESS_NOT_ENABLED',store.load)

    def test_no_permissions_repair_or_directory_creation(self):
        os.chmod(self.root,0o755)
        self.fails('STORE_USER_ACTION_REQUIRED',self.make)
        self.assertEqual(self.root.stat().st_mode&0o777,0o755)

    def test_encrypt_restart_and_wrong_password(self):
        value={'version':1,'private':'SYNTHETIC_CLEAR_VALUE'}
        store=self.make(allow_secret_access=True,_read=lambda _:self.password)
        with store.lock(): store.save(value)
        self.assertNotIn(b'SYNTHETIC_CLEAR_VALUE',self.path.read_bytes())
        self.assertNotIn(self.password.encode(),self.path.read_bytes())
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        restarted=self.make(allow_secret_access=True,_read=lambda _:self.password)
        with restarted.lock(): self.assertEqual(restarted.load(),value)
        wrong=self.make(allow_secret_access=True,_read=lambda _:'wrong synthetic password')
        before=self.path.read_bytes()
        with wrong.lock(): self.fails('VAULT_UNLOCK_FAILED',lambda:wrong.save(value))
        self.assertEqual(self.path.read_bytes(),before)

    def test_corruption_not_overwritten(self):
        self.path.write_bytes(b'broken')
        os.chmod(self.path,0o600)
        store=self.make(allow_secret_access=True,_read=lambda _:self.fail('prompt'))
        with store.lock(): self.fails('STORE_CORRUPT',lambda:store.save({'version':1}))
        self.assertEqual(self.path.read_bytes(),b'broken')

    def test_symlink_refused(self):
        target=self.root/'target'
        target.write_text('synthetic')
        self.path.symlink_to(target)
        self.fails('STORE_USER_ACTION_REQUIRED',self.make)


class IdentityTests(Errors,unittest.TestCase):
    def test_invalid_identity_never_becomes_retryable(self):
        from muse_cli.gateway import AuthError, GatewayError
        for error,code in ((AuthError('synthetic'),'SESSION_INVALID'),
                           (GatewayError(401,'synthetic'),'SESSION_INVALID'),
                           (GatewayError(403,'synthetic'),'HTTP_REJECTED'),
                           (TimeoutError('synthetic'),'TIMEOUT')):
            class Gateway:
                def call_json(self,*a): raise error
                def close(self): pass
            session=MemorySession('synthetic fixture')
            self.fails(code,lambda:session.verify_readonly(_gateway_factory=lambda _:Gateway()))
