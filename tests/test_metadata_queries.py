import contextlib
import io
import unittest
from unittest.mock import Mock, patch
from muse_cli.metadata_queries import read_metadata
from muse_cli.readonly import ReadError, main
from muse_cli.gateway import ROUTES, GatewayError

FIXTURES = {
    'model': {'selected_model':'provider/example', 'default_model':'provider/example',
              'model_identity_visibility':'visible','generation':1,'available_models':[
                  {'id':'provider/example','provider':'provider','model':'example',
                   'context_window_tokens':123,'preview_model':False,'token':'SECRET'}]},
    'computer-context': {'tasks':[{'browser_task_id':'synthetic-task','status':'running',
                'owner_kind':'main_agent','control_owner':'agent',
                'latest_tab':{'url':'https://private.invalid/?token=SECRET'},'title':'PRIVATE'}],
                'default_desktop_image':{'url':'https://private.invalid/image'}},
    'voice-catalog': {'voices':[{'id':'voice-id','source':'custom','name':'PRIVATE',
             'description':'PRIVATE','is_selected':True,'preview_url':'https://private.invalid'}],
             'total':1,'offset':0,'limit':20},
    'voice-filters': {'filter_options':{'gender':[{'value':'X','label':'Synthetic','count':1}],
                                      'extra_private':{'password':'SECRET'}}},
    'connector-marketplace': {'version':'1','custom_count':1,'featured':[
        {'id':'test','state':'connected','is_custom':True,'name':'PRIVATE',
         'consent':{'url':'https://private.invalid/?token=SECRET'}}],
         'categories':[{'id':'test','title':'Test','connectors':[]}]},
    'library': {'entries':[{'name':'sample.mp4','path':'artifacts/sample.mp4','size':12,
          'modified_ms':1800000000000,'media':{'url':'https://private.invalid/?token=SECRET'}}],
          'total':1,'has_more':False},
}


class MetadataTests(unittest.TestCase):
    def test_whitelists_strip_private_content(self):
        for command, data in FIXTURES.items():
            with self.subTest(command=command):
                gateway=Mock();gateway.call_json.return_value=data
                result=read_metadata(gateway,command)
                self.assertNotIn('SECRET',str(result));self.assertNotIn('PRIVATE',str(result))
                self.assertNotIn('https://',str(result))
                gateway.call_json.assert_called_once()

    def test_library_is_exact_semantic_read_post_no_arbitrary_path(self):
        gateway=Mock();gateway.call_json.return_value=FIXTURES['library']
        read_metadata(gateway,'library',preset='media',limit=4,offset=8)
        gateway.call_json.assert_called_once_with('fs.library',body={'preset':'media','limit':4,'offset':8})
        for preset in ['/', '../', 'credentials']:
            with self.assertRaises(ReadError):read_metadata(gateway,'library',preset=preset)
        self.assertEqual(gateway.call_json.call_count,1)

    def test_get_queries_match_web_contract(self):
        expected={'model':('model.get',{}), 'computer-context':('computer.context',{}),
          'voice-catalog':('voice.catalog',{'query':{'source':'library','limit':20,'offset':0,'pin_selected':'true'}}),
          'voice-filters':('voice.catalog_filters',{'query':{'source':'library'}}),
          'connector-marketplace':('connectors.homepage',{'query':{'preview_limit':5}})}
        for command,(method,kwargs) in expected.items():
            gateway=Mock();gateway.call_json.return_value=FIXTURES[command]
            read_metadata(gateway,command)
            gateway.call_json.assert_called_once_with(method,**kwargs)

    def test_hidden_models_never_leak(self):
        gateway=Mock();gateway.call_json.return_value={'model_identity_visibility':'hidden',
                            'selected_model':'SECRET','available_models':[{'token':'SECRET'}]}
        self.assertEqual(read_metadata(gateway,'model'),{'model_identity_visibility':'hidden'})

    def test_unknown_visibility_and_malformed_scalars_fail(self):
        for command,data in [('model',{'model_identity_visibility':'new'}),
            ('model',{'selected_model':'https://bad.invalid/?token=SECRET'}),
            ('voice-catalog',{'voices':[],'total':True}),
            ('computer-context',{'tasks':[{'control_owner':'new'}]}),
            ('library',{'entries':[{'path':'https://private.invalid/?token=SECRET'}]})]:
            gateway=Mock();gateway.call_json.return_value=data
            with self.assertRaises(ReadError):read_metadata(gateway,command)

    def test_urls_and_credential_strings_inside_allowed_fields_are_rejected(self):
        for bad in ['https://private.invalid/?token=SECRET', 'wss://private.invalid/socket',
                    'Bearer SECRET', 'access_token=SECRET']:
            for command,data in [('model',{'display_name':bad}),
                ('voice-catalog',{'voices':[{'id':'v','source':'custom','accent':bad}]}),
                ('connector-marketplace',{'featured':[], 'categories':[{'id':'x','title':bad,'connectors':[]}]}),
                ('voice-filters',{'filter_options':{'gender':[{'label':bad}]}})]:
                gateway=Mock();gateway.call_json.return_value=data
                with self.assertRaises(ReadError) as cm:read_metadata(gateway,command)
                self.assertNotIn('SECRET',str(cm.exception))

    def test_changed_route_fails_without_network(self):
        gateway=Mock()
        with patch.dict(ROUTES,{'fs.library':{'http':'POST','path':'/fs/write'}}):
            with self.assertRaises(ReadError):read_metadata(gateway,'library')
        gateway.call_json.assert_not_called()

    def test_error_is_redacted_and_not_retried(self):
        gateway=Mock();gateway.call_json.side_effect=GatewayError(403,'SECRET')
        with self.assertRaises(ReadError) as cm:read_metadata(gateway,'library')
        self.assertEqual(str(cm.exception),'FORBIDDEN');gateway.call_json.assert_called_once()

    def test_main_restores_in_memory_without_resume_or_save(self):
        for command,data in FIXTURES.items():
            store,login,gateway=Mock(),Mock(),Mock()
            login.http.cookies.jar=[];store.lock.return_value=contextlib.nullcontext()
            gateway.call_json.return_value=data
            with patch('muse_cli.secure_store.configured_store',return_value=store), \
                 patch('muse_cli.login_state.restore',return_value=login), \
                 patch('muse_cli.login_state.SavedLogin') as resume, \
                 patch('muse_cli.gateway.Gateway',return_value=gateway), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([command]),0)
            resume.assert_not_called();store.save.assert_not_called()
            gateway.close.assert_called_once();login.close.assert_called_once()

    def test_invalid_arguments_before_credentials(self):
        for args in [['library','--offset','-1'],['model','--offset','1'],
                     ['model','--preset','media'],['library','--preset','/']]:
            with patch('muse_cli.secure_store.configured_store') as store, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),2)
            store.assert_not_called()


if __name__ == '__main__':unittest.main()
