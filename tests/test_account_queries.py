"""Read-only health contracts; all data synthetic, no account/network access."""
import unittest
from unittest.mock import Mock, patch
from muse_cli.gateway import ROUTES, GatewayError
from muse_cli.readonly import read, ReadError


class HealthTests(unittest.TestCase):
    def test_exact_get_routes_and_redaction(self):
        for command, method, path in [('vm-health', 'vm.health', '/health'),
                ('vm-enrollment-health', 'vm.enrollment_health', '/health/enrollment')]:
            gateway = Mock()
            gateway.call_json.return_value = {'cvm_enroll_state': 'ENROLLED', 'access_token': 'SYNTHETIC',
                                             'private_diagnostic': {'text': 'SYNTHETIC'}}
            result = read(gateway, command)
            gateway.call_json.assert_called_once_with(method)
            self.assertEqual(ROUTES[method]['http'], 'GET')
            self.assertEqual(ROUTES[method]['path'], path)
            self.assertEqual(result, {'cvm_enroll_state': 'ENROLLED'})

    def test_route_change_fails_closed(self):
        gateway = Mock()
        with patch.dict(ROUTES, {'vm.health': {'http': 'POST', 'path': '/health'}}):
            with self.assertRaises(ReadError) as cm:
                read(gateway, 'vm-health')
        self.assertEqual(cm.exception.code, 'READ_CONTRACT_CHANGED')
        gateway.call_json.assert_not_called()

    def test_errors_do_not_leak_response(self):
        for status, expected in [(401, 'AUTH_INVALID'), (403, 'FORBIDDEN'),
                                  (429, 'RATE_LIMITED'), (503, 'API_FAILED')]:
            gateway = Mock()
            gateway.call_json.side_effect = GatewayError(status, 'SYNTHETIC_SECRET')
            with self.assertRaises(ReadError) as cm:
                read(gateway, 'vm-health')
            self.assertEqual(str(cm.exception), expected)

class WebQueriesTests(unittest.TestCase):
    def test_vm_inventory_without_gateway_or_sensitive_fields(self):
        from muse_cli.account_queries import read_web
        http = Mock()
        http.get.return_value.status_code = 200
        http.get.return_value.json.return_value = {
            'status': 'assigned', 'vm_state': 'running',
            'endpoint_url': 'wss://secret.example/?token=SECRET',
            'vms': [{'id': 'synthetic-vm', 'is_preferred': True,
                     'vm_type': 'hatch_cvm', 'notary_token_expiration_ts': 123,
                     'avatar_name': 'PRIVATE', 'access_token': 'SECRET'}]}
        result = read_web(http, 'vm-status')
        self.assertEqual(result, {'status': 'assigned', 'vm_state': 'running',
            'vms': [{'id': 'synthetic-vm', 'is_preferred': True, 'vm_type': 'hatch_cvm'}]})
        self.assertEqual(http.get.call_args.args, ('https://muse.ai/api/session?vm_state=live',))
        self.assertFalse(http.get.call_args.kwargs['allow_redirects'])
        http.post.assert_not_called()

    def test_web_fail_closed(self):
        from muse_cli.account_queries import read_web
        for status, expected in [(302, 'API_FAILED'), (401, 'AUTH_INVALID'),
                                 (429, 'RATE_LIMITED'), (500, 'API_FAILED')]:
            http = Mock()
            http.get.return_value.status_code = status
            with self.assertRaises(ReadError) as cm:
                read_web(http, 'vm-status')
            self.assertEqual(cm.exception.code, expected)
            http.get.return_value.json.assert_not_called()
        for data in [[], {}, {'status': 'new-unverified'}, {'status': 'assigned', 'vms': {}}]:
            http = Mock()
            http.get.return_value.status_code = 200
            http.get.return_value.json.return_value = data
            with self.assertRaises(ReadError) as cm:
                read_web(http, 'vm-status')
            self.assertEqual(cm.exception.code, 'INVALID_RESPONSE')

    def test_quota_unverified_before_credential_access(self):
        import contextlib
        import io
        from muse_cli.readonly import main
        output = io.StringIO()
        with patch('muse_cli.secure_store.configured_store') as store, contextlib.redirect_stderr(output):
            self.assertEqual(main(['quota']), 2)
        store.assert_not_called()
        self.assertEqual(output.getvalue().strip(), 'QUOTA_QUERY_UNVERIFIED')

    def test_web_cli_does_not_resume_save_or_connect_gateway(self):
        import contextlib
        import io
        from muse_cli.readonly import main
        store, login = Mock(), Mock()
        store.lock.return_value = contextlib.nullcontext()
        login.http.get.return_value.status_code = 200
        login.http.get.return_value.json.return_value = {'status': 'none'}
        with patch('muse_cli.secure_store.configured_store', return_value=store), \
             patch('muse_cli.login_state.restore', return_value=login), \
             patch('muse_cli.login_state.SavedLogin') as saved, \
             patch('muse_cli.gateway.Gateway') as gateway, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['vm-status']), 0)
        store.save.assert_not_called()
        saved.assert_not_called()
        gateway.assert_not_called()
        login.close.assert_called_once()


    def test_health_cli_restores_memory_without_saving(self):
        import contextlib
        import io
        from muse_cli.readonly import main
        store, login, gateway = Mock(), Mock(), Mock()
        store.lock.return_value = contextlib.nullcontext()
        login.http.cookies.jar = []
        gateway.call_json.return_value = {'all_healthy': True}
        with patch('muse_cli.secure_store.configured_store', return_value=store), \
             patch('muse_cli.login_state.restore', return_value=login), \
             patch('muse_cli.login_state.SavedLogin') as saved, \
             patch('muse_cli.gateway.Gateway', return_value=gateway), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['vm-health']), 0)
        saved.assert_not_called()
        store.save.assert_not_called()
        login.close.assert_called_once()
        gateway.close.assert_called_once()

    def test_malformed_health_and_vm_fields_fail_closed(self):
        from muse_cli.account_queries import read_web
        for data in [{'status': 'assigned'}, {'status': 'assigned', 'vms': [{}]},
                     {'status': 'none', 'vm_state': True},
                     {'status': 'assigned', 'vms': [{'id': 'wss://bad/?token=secret'}]}]:
            http = Mock()
            http.get.return_value.status_code = 200
            http.get.return_value.json.return_value = data
            with self.assertRaises(ReadError):
                read_web(http, 'vm-status')
        for data in [{'all_healthy': 'SECRET'}, {'cvm_enroll_state': 'unknown'},
                     {'active_turn_count': True}]:
            gateway = Mock()
            gateway.call_json.return_value = data
            with self.assertRaises(ReadError):
                read(gateway, 'vm-health')


if __name__ == '__main__':
    unittest.main()
