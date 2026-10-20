"""Offline, curated command help. Not a gateway route execution allowlist."""
from .readonly import ReadError

# This registry describes only muse-read, never the legacy raw/write surface.
COMMANDS = {}
def _add(name, group, summary, *, params=None, verified='static', notes='', sensitive=True):
    COMMANDS[name] = dict(command=name, group=group, summary=summary,
        parameters=params or [], example='muse-read ' + name,
        effect='offline' if group == 'discovery' else 'read-only',
        verification=verified, verification_notes=notes,
        may_return_private_content=sensitive,
        authorization='Existing user authorization and selected login required; no authority granted by this schema.'
                      if group != 'discovery' else 'No login or network required.',
        storage_effect='none' if group == 'discovery' else
            ('Legacy SavedLogin.resume may update selected login storage.' if name in ('identity','sessions','session','history','spaces') else 'Restore existing login in memory; no saved-login writes.'))

LIMIT = dict(flag='--limit', type='integer', default=20, minimum=1, maximum=100)
OFFSET = dict(flag='--offset', type='integer', default=0, minimum=0, maximum=100000)
ID = dict(flag='--id', type='string', required=True, pattern='[A-Za-z0-9_.:-]{1,200}')
for n, text in [('identity','Read account identity'),('sessions','List sessions'),('session','Read one session'),('history','Read session messages'),('spaces','List spaces')]:
    _add(n,'conversations',text,params=([ID, LIMIT] if n=='history' else [ID] if n=='session' else []),
         verified='legacy-existing; not revalidated in this delivery',sensitive=True)
    if n in ('session','history'): COMMANDS[n]['example'] += ' --id SESSION_ID'
for n,text in [('vm-status','Read web VM inventory; never wake/reset'),('vm-health','Read gateway health'),('vm-enrollment-health','Read enrollment health'),('quota','Read usage, quota status and reset time')]:
    _add(n,'account',text,verified='live-contract-verified',notes='2026-10-20 original server/account; packaged CLI not deployed. Quota fails closed on frontend contract changes.')
for n,text in [('model','Read selected/default/available models'),('computer-context','Read bounded computer task metadata'),('voice-catalog','List public library voices'),('voice-filters','List voice filter values'),('connector-marketplace','List public connector metadata'),('library','List library file metadata; never file contents')]:
    params = [LIMIT,OFFSET] if n in ('library','voice-catalog') else [LIMIT] if n in ('computer-context','connector-marketplace') else []
    if n=='library': params += [dict(flag='--preset',type='string',default='artifacts',choices=['artifacts','media','recents'])]
    _add(n,'library' if n=='library' else 'metadata',text,params=params,verified='live-contract-verified',
         notes=('Only artifacts preset tested live; media/recents static callsites confirmed.' if n=='library' else '2026-10-20 contract verified; computer task entries static only (live list empty).') ,sensitive=True)
_add('media','unsupported','Legacy media query is intentionally disabled',verified='unsupported',notes='Returns MEDIA_SCHEMA_UNVERIFIED before authentication. Use library --preset media for metadata listing.')
COMMANDS['media']['effect']='none; exits nonzero'
COMMANDS['media']['storage_effect']='none'
COMMANDS['media']['authorization']='No login required; unsupported command exits nonzero.'
COMMANDS['media']['may_return_private_content']=False
for n,summary,params in [
    ('discover','List curated command groups',[dict(flag='--group',type='string',required=False)]),
    ('describe','Describe one supported command',[dict(name='target',type='string',required=True)]),
    ('capabilities','Inspect observed low-level routes, not permission to execute',[dict(flag='--id',type='string',description='Optional method prefix'),LIMIT])]:
    _add(n,'discovery',summary,params=params,verified='offline-unit-tested',sensitive=False)
COMMANDS['describe']['example']='muse-read describe quota'

GROUPS = ('account','conversations','library','metadata','discovery','unsupported')

def discover(group=None):
    if group is not None and group not in GROUPS:
        raise ReadError('UNKNOWN_GROUP')
    return {'schema_version':1, 'scope':'curated muse-read commands only; observed routes are not executable permissions',
            'groups':[{'group':g,'commands':[{'command':v['command'],'summary':v['summary'],'verification':v['verification']} for v in COMMANDS.values() if v['group']==g]} for g in GROUPS if group is None or g==group]}

def describe(name):
    if name not in COMMANDS:
        raise ReadError('UNKNOWN_COMMAND')
    result = dict(COMMANDS[name])
    result['schema_version']=1
    result['global_options'] = [] if result['group']=='discovery' or name=='media' else [
        {'flag':'--store','choices':['secretservice','encrypted-file','plaintext-file'],'default':'secretservice'},
        {'flag':'--profile','default':'default'}, {'flag':'--vault','description':'Existing selected encrypted vault path; never put secret values in argv.'}]
    result['failure_policy']='No automatic retry after 401/403; inspect state before any uncertain-operation retry. No automatic secret recovery.'
    return result
