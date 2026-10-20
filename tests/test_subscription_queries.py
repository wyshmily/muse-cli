"""Synthetic Flight fixtures; no credentials, real account data or network."""
import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch
from muse_cli.readonly import ReadError, main
from muse_cli.subscription_queries import (ACTION_ID, DEPENDENCY, ACTION_ASSET,
                                           read_quota, action_result, page_context)


def response(text, status=200, content_type='text/html'):
    return Mock(text=text, status_code=status, headers={'content-type': content_type})


def page():
    tree = ['', {'children': ['__PAGE__?{"q":"test"}', {}, '$undefined', '$undefined', 4096]}, '$undefined', '$undefined', 4112]
    record = '0:' + json.dumps({'f': [[tree]]}) + '\n'
    return '<html data-dpl-id="dpl_synthetic"><script src="'+DEPENDENCY+'"></script><script>self.__next_f.push('+json.dumps([1,record])+')</script>'


def flight(usage=None):
    sub = {'usage': usage or {'state': 'METERED', 'percentUsed': 75,
           'resetsAt': 1800000000, 'quotaStatus': 'SYNTHETIC'},
           'topupBalance': 3, 'topupTotal': 10, 'access_token': 'SECRET',
           'agreement': {'billingAddress': 'PRIVATE'}}
    return '0:{"a":"$@1","f":"","q":"","i":false}\n1:'+json.dumps({'success':True,'subscription':sub})+'\n'


def login_fixture(post=None):
    login = Mock()
    login.headers = {'Origin': 'https://muse.ai', 'Referer': 'https://muse.ai/',
                     'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty'}
    login.http.get.side_effect = [response(page()), response(ACTION_ASSET.rsplit('/',1)[1]),
        response('createServerReference)("'+ACTION_ID+'",l.callServer,void 0,l.findSourceMapURL,"fetchSubscriptionAction")')]
    login.http.post.return_value = post or response(flight(), content_type='text/x-component')
    return login


class QuotaTests(unittest.TestCase):
    def test_exact_single_read_action_and_sanitized_output(self):
        login = login_fixture()
        result = read_quota(login)
        args = login.http.post.call_args
        self.assertEqual(args.args, ('https://muse.ai/',))
        self.assertEqual(args.kwargs['data'], '[{"includeAgreement":false}]')
        self.assertEqual(args.kwargs['headers']['x-deployment-id'], 'dpl_synthetic')
        self.assertEqual(args.kwargs['headers']['Referer'], login.headers['Referer'])
        self.assertEqual(args.kwargs['headers']['Next-Action'], ACTION_ID)
        self.assertFalse(args.kwargs['allow_redirects'])
        self.assertEqual(login.http.post.call_count, 1)
        self.assertEqual(result['usage']['resetsAtUTC'], '2027-01-15T08:00:00+00:00')
        self.assertNotIn('SECRET', str(result)); self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(result['topupBalance'], 3)
        login._save.assert_not_called()

    def test_403_stops_no_recovery_retry_or_error_body(self):
        login = login_fixture(response('{"error":"SECRET"}',403,'application/json'))
        with self.assertRaises(ReadError) as cm:read_quota(login)
        self.assertEqual(str(cm.exception), 'FORBIDDEN')
        self.assertEqual(login.http.post.call_count, 1)
        login._request.assert_not_called()
        login._save.assert_not_called()

    def test_changed_page_or_action_never_posts(self):
        for replies in [[response('<html>changed</html>')],
            [response(page()), response('new-file.js')],
            [response(page()),response(ACTION_ASSET),response('unknown action')]]:
            login = login_fixture(); login.http.get.side_effect = replies
            with self.assertRaises(ReadError):read_quota(login)
            login.http.post.assert_not_called()

    def test_action_name_must_bind_to_same_reference(self):
        login = login_fixture()
        source = ('createServerReference)("'+ACTION_ID+'",l.callServer,void 0,l.findSourceMapURL,"differentAction"),'
                  'other=createServerReference)("'+'4'*42+'",l.callServer,void 0,l.findSourceMapURL,"fetchSubscriptionAction")')
        login.http.get.side_effect = [response(page()), response(ACTION_ASSET), response(source)]
        with self.assertRaises(ReadError) as cm:read_quota(login)
        self.assertEqual(cm.exception.code, 'READ_CONTRACT_CHANGED')
        login.http.post.assert_not_called()

    def test_strict_flight_and_usage(self):
        for text in ['0:{"a":"$@99"}', '0:{"a":"$@1"}\n1:E{"message":"SECRET"}',
                     '0:{"a":{"success":false,"error":"SECRET"}}',
                     '0:{"a":{"success":true,"sessionRecovery":{}}}',
                     flight({'state':'METERED','resetsAt':1800000000000}),
                     flight({'state':'METERED','percentUsed':True}),
                     flight({'state':'$@2'})]:
            with self.assertRaises((ReadError, ValueError)) as cm:action_result(text)
            self.assertNotIn('SECRET', str(cm.exception))

    def test_main_never_resumes_saves_or_connects_gateway(self):
        store, login = Mock(), login_fixture()
        store.lock.return_value = contextlib.nullcontext()
        with patch('muse_cli.secure_store.configured_store',return_value=store), \
             patch('muse_cli.login_state.restore',return_value=login), \
             patch('muse_cli.login_state.SavedLogin') as resume, \
             patch('muse_cli.gateway.Gateway') as gateway, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['quota']),0)
        resume.assert_not_called();store.save.assert_not_called();gateway.assert_not_called()
        login.close.assert_called_once()


if __name__ == '__main__':unittest.main()
