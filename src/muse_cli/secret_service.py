"""Pinned, existing Secret Service collection. No collection creation/unlock/UI."""
import contextlib
from .native_auth import LoginError


class PinnedConnection:
    def __init__(self, bus, owner):
        self.bus, self.owner = bus, owner

    def __getattr__(self, name):
        return getattr(self.bus, name)

    def send_and_get_reply(self, message, *args, **kwargs):
        from jeepney.low_level import HeaderFields
        # Unique destination prevents D-Bus autoactivation if the provider exits.
        if message.header.fields.get(HeaderFields.destination) == 'org.freedesktop.secrets':
            message.header.fields[HeaderFields.destination] = self.owner
        return self.bus.send_and_get_reply(message, *args, **kwargs)


class ExistingSecretService:
    def __init__(self):
        self.collection_path = None
        with self.collection() as collection:
            self.collection_path = collection.collection_path

    @contextlib.contextmanager
    def collection(self):
        import secretstorage
        from secretstorage.util import DBusAddressWrapper
        from secretstorage.exceptions import ItemNotFoundException, LockedException
        bus = None
        try:
            bus = secretstorage.dbus_init()
            dbus = DBusAddressWrapper('/org/freedesktop/DBus', 'org.freedesktop.DBus', bus)
            dbus.bus_name = 'org.freedesktop.DBus'
            present, = dbus.call('NameHasOwner', 's', 'org.freedesktop.secrets')
            if not present:
                raise LoginError('STORE_UNAVAILABLE')
            owner, = dbus.call('GetNameOwner', 's', 'org.freedesktop.secrets')
            if not isinstance(owner, str) or not owner.startswith(':'):
                raise LoginError('STORE_UNAVAILABLE')
            pinned = PinnedConnection(bus, owner)
            if self.collection_path is None:
                collection = secretstorage.get_collection_by_alias(pinned, 'default')
            else:
                collection = secretstorage.Collection(pinned, self.collection_path)
            if collection.is_locked():
                raise LoginError('STORE_USER_ACTION_REQUIRED')
            yield collection
        except (ItemNotFoundException, LockedException):
            raise LoginError('STORE_USER_ACTION_REQUIRED') from None
        except Exception as exc:
            if getattr(exc, 'name', None) == 'org.freedesktop.Secret.Error.IsLocked':
                raise LoginError('STORE_USER_ACTION_REQUIRED') from None
            raise
        finally:
            if bus is not None:
                bus.close()

    @staticmethod
    def encrypted_session(collection):
        from secretstorage.dhcrypto import Session
        from secretstorage.defines import ALGORITHM_DH, SS_PATH
        from secretstorage.util import DBusAddressWrapper, SERVICE_IFACE
        service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, collection.connection)
        session = Session()
        output, path = service.call('OpenSession', 'sv', ALGORITHM_DH,
                                   ('ay', session.my_public_key.to_bytes(128, 'big')))
        signature, public = output
        if signature != 'ay' or not isinstance(path, str) or not path.startswith('/') or path == '/':
            raise LoginError('STORE_FAILED')
        session.set_server_public_key(int.from_bytes(public, 'big'))
        session.object_path = path
        if not session.encrypted:
            raise LoginError('STORE_FAILED')
        collection.session = session
        return session

    @staticmethod
    def matching(collection, service, profile):
        items = list(collection.search_items({'service': service, 'username': profile}))
        if len(items) > 1:
            raise LoginError('STORE_CORRUPT')
        collection.ensure_not_locked()
        for item in items:
            if item.is_locked():
                raise LoginError('STORE_USER_ACTION_REQUIRED')
        return items[0] if items else None

    def get_password(self, service, profile):
        with self.collection() as collection:
            item = self.matching(collection, service, profile)
            if item is None:
                return None
            item.session = self.encrypted_session(collection)
            collection.ensure_not_locked()
            return item.get_secret().decode('utf-8')

    def set_password(self, service, profile, value):
        from secretstorage.util import format_secret
        from secretstorage.defines import SS_PREFIX
        with self.collection() as collection:
            item = self.matching(collection, service, profile)
            session = self.encrypted_session(collection)
            collection.ensure_not_locked()
            if item is not None:
                item.session = session
                item.set_secret(value.encode('utf-8'))
                return
            # Collection.create_item may run exec_prompt: use its wire operation
            # explicitly, never execute an optional prompt or retry uncertain work.
            props = {SS_PREFIX+'Item.Label': ('s', 'DotLink Muse session'),
                     SS_PREFIX+'Item.Attributes': ('a{ss}', {'service': service, 'username': profile})}
            path, prompt = collection._collection.call('CreateItem', 'a{sv}(oayays)b',
                props, format_secret(session, value.encode('utf-8'), 'text/plain'), False)
            if prompt != '/':
                raise LoginError('STORE_USER_ACTION_REQUIRED')
            if not isinstance(path, str) or path == '/' or not path.startswith('/'):
                raise LoginError('STORE_FAILED')

    def delete_password(self, service, profile):
        with self.collection() as collection:
            item = self.matching(collection, service, profile)
            if item is None:
                return
            collection.ensure_not_locked()
            item.ensure_not_locked()
            prompt, = item._item.call('Delete', '')
            if prompt != '/':
                raise LoginError('STORE_USER_ACTION_REQUIRED')
