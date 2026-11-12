"""End-to-end check of the /mcp sign-in against a fake Google: discovery, client
registration, Google sign-in (owner only), code + PKCE, a tool call over /mcp,
refresh rotation, revoke, and the old /sse closing. Run: pytest tests/
(test_mcp_oauth.py runs this in a fresh process with the env it needs)."""
import base64, hashlib, json, os, secrets, sys
from urllib.parse import urlparse, parse_qs
ok_all = True
def ok(n, c, x=''):
    global ok_all; ok_all &= bool(c); print(('PASS ' if c else 'FAIL ') + n, '' if c else str(x)[:400])

import google_connections_mcp.mcp_oauth as MO
EMAIL = {'v': 'owner@example.com'}
class FakeCreds:
    token = 'g-access'; refresh_token = 'g-refresh'; scopes = ['https://www.googleapis.com/auth/drive']
    def to_json(self): return json.dumps({'token': self.token, 'refresh_token': self.refresh_token, 'client_id': 'c', 'client_secret': 's', 'token_uri': 'https://oauth2.googleapis.com/token', 'scopes': self.scopes})
class FakeSession: pass
class FakeFlow:
    def __init__(self, state): self.state = state; self.code_verifier = 'gv-' + (state or '')[:6]; self.credentials = FakeCreds(); self.oauth2session = FakeSession()
    def authorization_url(self, **kw): return ('https://accounts.google.com/o/oauth2/auth?state=' + self.state, self.state)
    def fetch_token(self, code):
        assert code == 'google-code'
        payload = base64.urlsafe_b64encode(json.dumps({'email': EMAIL['v'], 'email_verified': True}).encode()).decode().rstrip('=')
        self.oauth2session.token = {'id_token': 'h.' + payload + '.s'}
MO._google_flow = lambda state=None: FakeFlow(state)

import google_connections_mcp.server as S
from starlette.testclient import TestClient
installed = {}
S.oauth_provider.on_google_token = lambda c: installed.update(json=c.to_json())

app = S.build_app()
BASE = 'https://gc.example.com'
with TestClient(app, base_url=BASE) as c:
    h = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
    init = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}}
    r = c.post('/mcp', json=init, headers=h)
    ok('E1 /mcp with no token: 401 pointing at the resource metadata', r.status_code == 401 and 'resource_metadata=' in r.headers.get('www-authenticate', ''), (r.status_code, r.headers))
    r = c.get('/.well-known/oauth-protected-resource/mcp')
    ok('E2 protected-resource metadata names this server as the authorization server', r.status_code == 200 and r.json()['authorization_servers'][0].rstrip('/') == BASE, r.text)
    r = c.get('/.well-known/oauth-authorization-server'); meta = r.json()
    ok('E3 authorization-server metadata lists register, authorize, token, revoke', r.status_code == 200 and all(k in meta for k in ('registration_endpoint', 'authorization_endpoint', 'token_endpoint', 'revocation_endpoint')), meta)
    r = c.get('/oauth/start', follow_redirects=False)
    ok('E4 before any /mcp connection, the old /oauth/start still works', r.status_code in (302, 307), r.status_code)
    REDIR = 'https://claude.ai/api/mcp/auth_callback'
    r = c.post('/register', json={'redirect_uris': [REDIR], 'client_name': 'Claude', 'token_endpoint_auth_method': 'client_secret_post', 'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']})
    reg = r.json(); cid, csec = reg.get('client_id'), reg.get('client_secret')
    ok('E5 dynamic client registration', r.status_code == 201 and cid, r.text)

    def sign_in(email):
        EMAIL['v'] = email
        verifier = secrets.token_urlsafe(48)
        chal = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        r = c.get('/authorize', params={'response_type': 'code', 'client_id': cid, 'redirect_uri': REDIR, 'code_challenge': chal, 'code_challenge_method': 'S256', 'state': 'claude-state', 'scope': 'claudeai'}, follow_redirects=False)
        loc = r.headers.get('location', '')
        pend = parse_qs(urlparse(loc).query).get('state', [None])[0]
        r2 = c.get('/oauth/callback', params={'state': pend, 'code': 'google-code'}, follow_redirects=False)
        return r, r2, verifier
    r, r2, _ = sign_in('stranger@example.com')
    ok('E6 /authorize sends you to Google (an unknown scope like "claudeai" is not refused)', r.status_code in (302, 307) and r.headers['location'].startswith('https://accounts.google.com/'), (r.status_code, r.text))
    ok('E7 a different Google account is turned away and nothing is saved', r2.status_code == 403 and not installed and not S.get_store().google_token(), (r2.status_code, installed))
    r, r2, verifier = sign_in('Owner@Example.com')
    q = parse_qs(urlparse(r2.headers.get('location', '')).query)
    ok('E8 the owner (any letter case) goes back to the app with a code and its own state', r2.status_code == 302 and r2.headers['location'].startswith(REDIR) and q.get('state') == ['claude-state'] and q.get('code'), (r2.status_code, r2.headers.get('location')))
    ok('E9 the Google token from that sign-in is installed', 'g-refresh' in installed.get('json', ''), installed)
    code = q['code'][0]
    r = c.post('/token', data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIR, 'client_id': cid, 'client_secret': csec, 'code_verifier': 'wrong-' + verifier})
    ok('E10 a wrong PKCE verifier is refused', r.status_code == 400, r.text)
    r = c.post('/token', data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIR, 'client_id': cid, 'client_secret': csec, 'code_verifier': verifier})
    tok = r.json()
    ok('E11 the code becomes an access token and a refresh token', r.status_code == 200 and tok.get('access_token') and tok.get('refresh_token'), r.text)
    r = c.post('/token', data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIR, 'client_id': cid, 'client_secret': csec, 'code_verifier': verifier})
    ok('E12 the same code can\'t be used twice', r.status_code == 400, r.text)
    hb = dict(h, Authorization='Bearer ' + tok['access_token'])
    r = c.post('/mcp', json=init, headers=hb)
    ok('E13 /mcp initialize with the token, and the server sends its instructions', r.status_code == 200 and 'Ask before anything that sends' in (r.json()['result'].get('instructions') or ''), r.text[:300])
    r = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, headers=hb)
    names = [t['name'] for t in r.json()['result']['tools']]
    ok(f'E14 tools/list over /mcp ({len(names)} tools, the new ones included)', 'search_console_query' in names and 'send_gmail_message' in names or 'search_console_query' in names, names[:5])
    r = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'get_time', 'arguments': {'timezone': 'America/New_York'}}}, headers=hb)
    ok('E15 a tool call runs through /mcp', r.status_code == 200 and not r.json()['result'].get('isError') and 'America/New_York' in r.text, r.text[:300])
    all_names = set(names)
    ok(f'E15a /mcp lists every tool, the six markdown ones included ({len(all_names)})', len(all_names) == 113 and {'markdown_list_files', 'markdown_read', 'markdown_create', 'markdown_insert', 'markdown_remove_text', 'markdown_replace_text'} <= all_names, len(all_names))
    covered = {'get_time'}
    for slug, prefix in [('gmail', 'gmail_'), ('calendar', 'calendar_'), ('drive', 'drive_'), ('docs', 'docs_'), ('sheets', 'sheets_'), ('tasks', 'tasks_'), ('search-console', 'search_console_'), ('analytics', 'analytics_'), ('markdown', 'markdown_')]:
        path = f'/{slug}/mcp'
        r = c.post(path, json=init, headers=h)
        www = r.headers.get('www-authenticate', '')
        ok(f'P1 {path} with no token: 401 pointing at its own resource metadata', r.status_code == 401 and f'oauth-protected-resource/{slug}/mcp' in www, (r.status_code, www))
        r = c.get(f'/.well-known/oauth-protected-resource/{slug}/mcp')
        ok(f'P2 {path} metadata names {path} as the resource and this server as the authorization server', r.status_code == 200 and r.json()['resource'].rstrip('/') == BASE + path and r.json()['authorization_servers'][0].rstrip('/') == BASE, r.text)
        r = c.post(path, json=init, headers=hb)
        ok(f'P3 {path} initialize with the same token', r.status_code == 200 and r.json()['result'].get('instructions'), r.text[:200])
        r = c.post(path, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, headers=hb)
        pn = {t['name'] for t in r.json()['result']['tools']}
        covered |= pn
        ok(f'P4 {path} lists only its own tools ({len(pn) - 1} + get_time)', len(pn) > 1 and all(n == 'get_time' or n.startswith(prefix) for n in pn) and pn == {n for n in all_names if n == 'get_time' or n.startswith(prefix)}, sorted(pn)[:8])
    ok('P5 the product endpoints together cover every tool on /mcp', covered == all_names, sorted(all_names - covered))
    r = c.post('/markdown/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'gmail_get_profile', 'arguments': {}}}, headers=hb)
    ok('P6 a tool from another product cannot be called through /markdown/mcp', r.status_code == 200 and (r.json().get('error') or r.json()['result'].get('isError')), r.text[:200])
    r = c.get('/health')
    ok('P7 /health lists the product addresses', r.json().get('product_urls', {}).get('markdown') == BASE + '/markdown/mcp', r.text)
    # A connector added at /gmail/mcp signs in with resource=<that address>.
    EMAIL['v'] = 'owner@example.com'
    v2 = secrets.token_urlsafe(48)
    ch2 = base64.urlsafe_b64encode(hashlib.sha256(v2.encode()).digest()).decode().rstrip('=')
    r = c.get('/authorize', params={'response_type': 'code', 'client_id': cid, 'redirect_uri': REDIR, 'code_challenge': ch2, 'code_challenge_method': 'S256', 'state': 's2', 'scope': 'claudeai', 'resource': BASE + '/gmail/mcp'}, follow_redirects=False)
    pend = parse_qs(urlparse(r.headers.get('location', '')).query).get('state', [None])[0]
    r2 = c.get('/oauth/callback', params={'state': pend, 'code': 'google-code'}, follow_redirects=False)
    code2 = parse_qs(urlparse(r2.headers.get('location', '')).query).get('code', [None])[0]
    r = c.post('/token', data={'grant_type': 'authorization_code', 'code': code2, 'redirect_uri': REDIR, 'client_id': cid, 'client_secret': csec, 'code_verifier': v2, 'resource': BASE + '/gmail/mcp'})
    gtok = r.json().get('access_token')
    r = c.post('/gmail/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, headers=dict(h, Authorization='Bearer ' + str(gtok)))
    ok('P8 a sign-in made for /gmail/mcp (resource=that address) works there', gtok and r.status_code == 200 and any(t['name'].startswith('gmail_') for t in r.json()['result']['tools']), (r.status_code, r.text[:200]))
    r = c.get('/oauth/start', follow_redirects=False)
    ok('E16 after the first /mcp connection the old /oauth/start is closed', r.status_code == 410, r.status_code)
    r = c.get('/sse')
    ok('E17 …and the open /sse is closed too', r.status_code == 410 and '/mcp' in r.text, (r.status_code, r.text[:200]))
    r = c.post('/messages/?session_id=x', json={})
    ok('E18 …and /messages', r.status_code == 410, r.status_code)
    r = c.post('/token', data={'grant_type': 'refresh_token', 'refresh_token': tok['refresh_token'], 'client_id': cid, 'client_secret': csec})
    tok2 = r.json()
    ok('E19 refresh gives a new pair', r.status_code == 200 and tok2['access_token'] != tok['access_token'] and tok2['refresh_token'] != tok['refresh_token'], r.text)
    r = c.post('/mcp', json=init, headers=hb)
    ok('E20 the old access token stops working once its refresh token is used', r.status_code == 401, r.status_code)
    r = c.post('/token', data={'grant_type': 'refresh_token', 'refresh_token': tok['refresh_token'], 'client_id': cid, 'client_secret': csec})
    ok('E21 the used refresh token is refused', r.status_code == 400, r.text)
    r = c.post('/revoke', data={'token': tok2['refresh_token'], 'client_id': cid, 'client_secret': csec})
    r2 = c.post('/mcp', json=init, headers=dict(h, Authorization='Bearer ' + tok2['access_token']))
    ok('E22 revoking the refresh token cuts off its access token too', r.status_code == 200 and r2.status_code == 401, (r.status_code, r2.status_code))
    store = json.load(open(os.path.join(os.environ['DATA_DIR'], 'mcp_store.json')))
    ok('E23 the store keeps token hashes, never the tokens themselves', tok2['access_token'] not in json.dumps(store) and tok['refresh_token'] not in json.dumps(store) and store['connected_at'], list(store))
    r = c.get('/health')
    ok('E24 /health reports the /mcp address and that legacy is off', r.json().get('mcp_url') == BASE + '/mcp' and r.json().get('legacy_sse') is False, r.text)
print('ALL PASS' if ok_all else 'FAILURES')
sys.exit(0 if ok_all else 1)
