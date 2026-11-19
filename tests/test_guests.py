"""Guests on /analytics/mcp: any Google account connects their OWN Google account to
the analytics endpoint only, while the owner's flow and token stay as they were.

Drives the real ASGI app (SDK auth routes, bearer check, the guest gate, the
real tools) against a fake Google. No network.
"""
import asyncio
import base64
import datetime
import hashlib
import json
import os
import secrets
import shutil
import tempfile
from urllib.parse import parse_qs, urlparse

# The server reads these at import time, so they go first. A data dir of our own.
_DATA = tempfile.mkdtemp(prefix='gc-guests-')
os.environ.update(
    DATA_DIR=_DATA,
    OWNER_EMAIL='owner@example.com',
    PUBLIC_URL='https://gc.example.com',
    GOOGLE_CREDENTIALS=json.dumps({'web': {
        'client_id': 'c', 'client_secret': 's',
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'redirect_uris': ['https://gc.example.com/oauth/callback']}}),
)
os.environ.pop('GOOGLE_TOKEN_JSON', None)
os.environ.pop('GA4_PROPERTY_ID', None)

import httpx  # noqa: E402
import pytest  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import google_connections_mcp.auth_manager as AM  # noqa: E402
import google_connections_mcp.mcp_oauth as MO  # noqa: E402
import google_connections_mcp.server as S  # noqa: E402
from google_connections_mcp.oauth_config import ALL_SCOPES  # noqa: E402

BASE = 'https://gc.example.com'
REDIR = 'https://claude.ai/api/mcp/auth_callback'
GA = 'https://www.googleapis.com/auth/analytics.readonly'
GUEST = 'friend@example.com'
OTHER_GUEST = 'second-friend@example.com'
H = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}}
PRODUCT_SLUGS = [slug for slug, *_ in S.PRODUCTS]


def _future():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=1)


def _creds(token, refresh, scopes):
    return Credentials(token=token, refresh_token=refresh, client_id='c', client_secret='s',
                       token_uri='https://oauth2.googleapis.com/token', scopes=scopes, expiry=_future())


OWNER_TOKEN = json.loads(_creds('owner-broad-access', 'owner-broad-refresh', ALL_SCOPES).to_json())


# -- a fake Google ------------------------------------------------------------
class FakeGoogle:
    def __init__(self):
        self.email = None
        self.asked = []   # (scopes, authorization_url kwargs) per sign-in
        self.n = 0


GOOGLE = FakeGoogle()


class _Session:
    token = None


class FakeFlow:
    def __init__(self, state, scopes):
        self.state, self.scopes = state, list(scopes or [])
        self.code_verifier = 'gv'
        self.oauth2session = _Session()
        self.credentials = None

    def authorization_url(self, **kw):
        GOOGLE.asked.append((self.scopes, kw))
        return 'https://accounts.google.com/o/oauth2/auth?state=' + self.state, self.state

    def fetch_token(self, code):
        assert code == 'google-code'
        GOOGLE.n += 1
        payload = base64.urlsafe_b64encode(json.dumps(
            {'email': GOOGLE.email, 'email_verified': True}).encode()).decode().rstrip('=')
        self.oauth2session.token = {'id_token': 'h.' + payload + '.s'}
        who = GOOGLE.email.lower()
        self.credentials = _creds(f'g-access-{who}-{GOOGLE.n}', f'g-refresh-{who}', self.scopes)


MO._google_flow = lambda state=None, scopes=None: FakeFlow(state, scopes)


# -- a fake Google API: answers with whose access token called it ------------
class _Call:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeService:
    def __init__(self, name, creds):
        self.name, self.creds = name, creds

    def accountSummaries(self):
        return self

    def list(self, **kw):
        return _Call({'accountSummaries': [{'displayName': self.creds.token, 'propertySummaries': [
            {'displayName': 'site', 'property': 'properties/123'}]}]})

    def properties(self):
        return self

    def runReport(self, property, body):
        return _Call({'dimensionHeaders': [], 'metricHeaders': [{'name': 'who'}],
                      'rows': [{'metricValues': [{'value': self.creds.token}]}], 'property': property})

    runRealtimeReport = runReport


AM.build = lambda name, version, credentials=None: FakeService(name, credentials)


# -- fixtures -----------------------------------------------------------------
@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """Every test starts with the owner already connected (broad token stored)
    and no guests."""
    store = S.get_store()
    with store._lock:
        for sec in store.SECTIONS:
            store._data[sec] = {}
        store._data['guests'] = {}
        store._data['google_token'] = dict(OWNER_TOKEN)
        store._data['connected_at'] = 1.0
        store._save()
    S.auth._load_credentials()
    GOOGLE.asked.clear()
    monkeypatch.delenv('GA4_PROPERTY_ID', raising=False)
    yield


@pytest.fixture(scope='module')
def client():
    with TestClient(S.build_app(), base_url=BASE) as c:
        yield c


def _register(c):
    r = c.post('/register', json={'redirect_uris': [REDIR], 'client_name': 'Claude',
                                  'token_endpoint_auth_method': 'client_secret_post',
                                  'grant_types': ['authorization_code', 'refresh_token'],
                                  'response_types': ['code']})
    assert r.status_code == 201, r.text
    return r.json()['client_id'], r.json()['client_secret']


def sign_in(c, email, path='/analytics/mcp', send_resource=True):
    """The whole connection: register, /authorize, Google, callback, /token.
    Returns (callback response, token json or None)."""
    cid, csec = _register(c)
    GOOGLE.email = email
    verifier = secrets.token_urlsafe(48)
    chal = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params = {'response_type': 'code', 'client_id': cid, 'redirect_uri': REDIR, 'code_challenge': chal,
              'code_challenge_method': 'S256', 'state': 'claude-state', 'scope': 'claudeai'}
    if send_resource:
        params['resource'] = BASE + path
    r = c.get('/authorize', params=params, follow_redirects=False)
    assert r.status_code in (302, 307), r.text
    pend = parse_qs(urlparse(r.headers['location']).query)['state'][0]
    cb = c.get('/oauth/callback', params={'state': pend, 'code': 'google-code'}, follow_redirects=False)
    code = parse_qs(urlparse(cb.headers.get('location', '')).query).get('code', [None])[0]
    if not code:
        return cb, None
    data = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIR, 'client_id': cid,
            'client_secret': csec, 'code_verifier': verifier}
    if send_resource:
        data['resource'] = BASE + path
    t = c.post('/token', data=data)
    assert t.status_code == 200, t.text
    tok = t.json()
    tok['_client'] = (cid, csec)
    return cb, tok


def call(c, path, token, name, args=None, rid=3):
    r = c.post(path, json={'jsonrpc': '2.0', 'id': rid, 'method': 'tools/call',
                           'params': {'name': name, 'arguments': args or {}}},
               headers=dict(H, Authorization='Bearer ' + token))
    return r


def tool_json(r):
    assert r.status_code == 200, (r.status_code, r.text[:300])
    return json.loads(r.json()['result']['content'][0]['text'])


def last_scopes():
    return set(GOOGLE.asked[-1][0])


# -- owner: unchanged -----------------------------------------------------------
def test_owner_full_sign_in_unchanged_without_guests(client):
    cb, tok = sign_in(client, 'Owner@Example.com', '/mcp')
    assert tok and cb.status_code == 302
    assert set(ALL_SCOPES) <= last_scopes()
    assert GOOGLE.asked[-1][1].get('include_granted_scopes') == 'true'
    assert S.get_store().google_token()['token'].startswith('g-access-owner@example.com')
    out = tool_json(call(client, '/mcp', tok['access_token'], 'analytics_list_properties'))
    assert out['properties'][0]['account'].startswith('g-access-owner@example.com')


def test_owner_with_no_token_at_all_keeps_narrow_one(client):
    # Nothing to downgrade: a fresh install connecting only /analytics/mcp
    # keeps that token so the analytics tools work; /mcp's sign-in replaces it.
    S.get_store().set_google_token(None)
    cb, tok = sign_in(client, 'owner@example.com', '/analytics/mcp')
    assert tok and last_scopes() == {'openid', 'email', GA}
    assert S.get_store().google_token()['token'].startswith('g-access-owner@example.com')
    assert not S.get_store()._data['guests']


def test_owner_full_flow_unchanged_on_every_other_endpoint(client, monkeypatch):
    for path in ['/mcp'] + [f'/{s}/mcp' for s in PRODUCT_SLUGS if s != 'analytics']:
        GOOGLE.asked.clear()
        cb, tok = sign_in(client, 'owner@example.com', path)
        assert tok, path
        assert set(ALL_SCOPES) <= last_scopes(), path
    assert not S.get_store()._data['guests']


def test_owner_never_downgraded_by_narrow_analytics_sign_in(client, monkeypatch):
    before = S.get_store().google_token()
    cb, tok = sign_in(client, 'owner@example.com', '/analytics/mcp')
    assert last_scopes() == {'openid', 'email', GA}       # the narrow sign-in
    assert tok and cb.status_code == 302                    # owner still gets in
    assert S.get_store().google_token() == before            # broad token untouched
    assert S.auth.credentials.token == 'owner-broad-access'  # and still in use
    # The owner's MCP token is the owner's: works on /mcp and every product.
    assert tool_json(call(client, '/mcp', tok['access_token'], 'analytics_list_properties'))[
        'properties'][0]['account'] == 'owner-broad-access'
    r = client.post('/gmail/mcp', json=INIT, headers=dict(H, Authorization='Bearer ' + tok['access_token']))
    assert r.status_code == 200
    assert not S.get_store()._data['guests']


def test_existing_owner_tokens_keep_working(client, monkeypatch):
    """Tokens issued before this change (rows without a guest tag) are the owner's."""
    cb, tok = sign_in(client, 'owner@example.com', '/mcp')
    store = S.get_store()
    row = store.get('access', MO.token_hash(tok['access_token']))
    row.pop('guest', None), row.pop('grant', None)
    store.put('access', MO.token_hash(tok['access_token']), row)
    for path in ['/mcp'] + [f'/{s}/mcp' for s in PRODUCT_SLUGS]:
        r = client.post(path, json=INIT, headers=dict(H, Authorization='Bearer ' + tok['access_token']))
        assert r.status_code == 200, path


def test_owner_instructions_and_analytics_wording(client):
    cb, tok = sign_in(client, 'owner@example.com', '/mcp')
    hb = dict(H, Authorization='Bearer ' + tok['access_token'])
    assert "the owner's own Google account" in client.post('/mcp', json=INIT, headers=hb).json()['result']['instructions']
    ins = client.post('/analytics/mcp', json=INIT, headers=hb).json()['result']['instructions']
    assert 'your Google account' in ins and "owner's" not in ins


def test_initialize_server_info_carries_each_endpoints_icon(client):
    cb, tok = sign_in(client, 'owner@example.com', '/mcp')
    hb = dict(H, Authorization='Bearer ' + tok['access_token'])
    for path, name in [('/mcp', 'google-connections')] + [(f'/{s}/mcp', s) for s in PRODUCT_SLUGS]:
        info = client.post(path, json=INIT, headers=hb).json()['result']['serverInfo']
        srcs = [i['src'] for i in info['icons']]
        assert srcs == [f'{BASE}/icons/{name}.png', f'{BASE}/icons/{name}.svg'], (path, info)
        assert client.get(srcs[0]).status_code == 200


# -- guests -----------------------------------------------------------------------
def test_guest_gets_narrow_scopes_and_own_token(client, monkeypatch):
    owner_before = S.get_store().google_token()
    cb, tok = sign_in(client, GUEST, '/analytics/mcp')
    assert tok, cb.text
    assert last_scopes() == {'openid', 'email', GA}
    assert 'include_granted_scopes' not in GOOGLE.asked[-1][1]
    store = S.get_store()
    assert store.google_token() == owner_before                     # owner untouched
    assert store.guest_token(GUEST)['token'].startswith(f'g-access-{GUEST}')
    row = store.get('access', MO.token_hash(tok['access_token']))
    assert row['guest'] == GUEST and row['grant'] == 'analytics'
    out = tool_json(call(client, '/analytics/mcp', tok['access_token'], 'analytics_list_properties'))
    assert out['properties'][0]['account'].startswith(f'g-access-{GUEST}')   # the guest's own Google
    # Owner's calls still use the owner's token after the guest connected.
    assert S.auth.get_credentials().token == 'owner-broad-access'


def test_guest_refused_on_mcp_and_every_other_product(client, monkeypatch):
    cb, tok = sign_in(client, GUEST, '/analytics/mcp')
    hb = dict(H, Authorization='Bearer ' + tok['access_token'])
    for path in ['/mcp'] + [f'/{s}/mcp' for s in PRODUCT_SLUGS if s != 'analytics']:
        r = client.post(path, json=INIT, headers=hb)
        assert r.status_code in (401, 403), (path, r.status_code)
        r = call(client, path, tok['access_token'], 'get_time', {'timezone': 'UTC'})
        assert r.status_code in (401, 403), (path, r.status_code)
    assert client.post('/analytics/mcp', json=INIT, headers=hb).status_code == 200


def test_guest_cannot_reach_owner_only_services_even_if_called():
    # Defense in depth below the gate: a guest context can't build Gmail etc.
    t = AM.current_guest.set(GUEST)
    try:
        with pytest.raises(AM.GuestNotAllowed):
            S.auth.get_gmail_service()
        with pytest.raises(AM.GuestNotAllowed):
            S.auth.get_drive_service()
    finally:
        AM.current_guest.reset(t)


def test_guest_sign_in_on_other_endpoint_is_refused_and_nothing_saved(client, monkeypatch):
    before = S.get_store().google_token()
    for path in ['/mcp', '/gmail/mcp', '/search-console/mcp']:
        cb, tok = sign_in(client, GUEST, path)
        assert tok is None and cb.status_code == 403, path
    cb, tok = sign_in(client, GUEST, '/analytics/mcp', send_resource=False)  # no resource: full flow
    assert tok is None and cb.status_code == 403 and 'Nothing was saved' in cb.text
    assert not S.get_store()._data['guests'] and S.get_store().google_token() == before


def test_any_account_can_connect_as_guest_on_analytics_but_nowhere_else(client):
    """No invite list: any non-owner account is a guest at /analytics/mcp, and
    refused (nothing saved) at every other address."""
    before = S.get_store().google_token()
    for i, who in enumerate(['stranger@example.com', 'Someone.Else@Example.org', 'x@another.test']):
        for path in ['/mcp'] + [f'/{s}/mcp' for s in PRODUCT_SLUGS if s != 'analytics']:
            cb, tok = sign_in(client, who, path)
            assert tok is None and cb.status_code == 403 and 'Nothing was saved' in cb.text, (who, path)
            assert set(ALL_SCOPES) <= last_scopes()
        assert S.get_store().guest_token(who) is None
        cb, tok = sign_in(client, who, '/analytics/mcp')
        assert tok and last_scopes() == {'openid', 'email', GA}, who
        assert S.get_store().guest_token(who)['token'].startswith(f'g-access-{who.lower()}')
        out = tool_json(call(client, '/analytics/mcp', tok['access_token'], 'analytics_list_properties'))
        assert out['properties'][0]['account'].startswith(f'g-access-{who.lower()}')
        for path in ['/mcp'] + [f'/{s}/mcp' for s in PRODUCT_SLUGS if s != 'analytics']:
            assert call(client, path, tok['access_token'], 'get_time', {'timezone': 'UTC'}).status_code in (401, 403)
    assert S.get_store().google_token() == before   # the owner's token never touched
    assert len(S.get_store()._data['guests']) == 3


def test_guest_refresh_keeps_guest_tag(client, monkeypatch):
    cb, tok = sign_in(client, GUEST, '/analytics/mcp')
    cid, csec = tok['_client']
    r = client.post('/token', data={'grant_type': 'refresh_token', 'refresh_token': tok['refresh_token'],
                                    'client_id': cid, 'client_secret': csec})
    new = r.json()
    assert r.status_code == 200
    assert call(client, '/mcp', new['access_token'], 'get_time', {'timezone': 'UTC'}).status_code in (401, 403)
    out = tool_json(call(client, '/analytics/mcp', new['access_token'], 'analytics_list_properties'))
    assert out['properties'][0]['account'].startswith(f'g-access-{GUEST}')


def test_guest_refreshed_google_token_saved_under_guest(monkeypatch):
    store = S.get_store()
    expired = json.loads(_creds('guest-old', 'guest-refresh', [GA]).to_json())
    expired['expiry'] = '2000-01-01T00:00:00Z'
    store.set_guest_token(GUEST, expired)
    owner_before = store.google_token()

    def fake_refresh(self, request):
        self.token = 'guest-new'
        self.expiry = _future()
    monkeypatch.setattr(Credentials, 'refresh', fake_refresh)
    t = AM.current_guest.set(GUEST)
    try:
        assert S.auth.get_credentials().token == 'guest-new'
    finally:
        AM.current_guest.reset(t)
    assert store.guest_token(GUEST)['token'] == 'guest-new'
    assert store.guest_token(GUEST)['refresh_token'] == 'guest-refresh'
    assert store.google_token() == owner_before


# -- GA4_PROPERTY_ID ----------------------------------------------------------------
def test_ga4_property_id_not_applied_for_guests(client, monkeypatch):
    monkeypatch.setenv('GA4_PROPERTY_ID', '999')
    cb, tok = sign_in(client, GUEST, '/analytics/mcp')
    out = tool_json(call(client, '/analytics/mcp', tok['access_token'], 'analytics_report', {'params': {}}))
    assert not out['success'] and 'analytics_list_properties' in out['error'] and '999' not in json.dumps(out)
    out = tool_json(call(client, '/analytics/mcp', tok['access_token'], 'analytics_realtime'))
    assert not out['success'] and 'analytics_list_properties' in out['error']
    out = tool_json(call(client, '/analytics/mcp', tok['access_token'], 'analytics_report',
                         {'params': {'property_id': '123'}}))
    assert out['success'] and out['property'] == 'properties/123'
    # The owner still gets the default.
    cb, otok = sign_in(client, 'owner@example.com', '/mcp')
    out = tool_json(call(client, '/analytics/mcp', otok['access_token'], 'analytics_report', {'params': {}}))
    assert out['success'] and out['property'] == 'properties/999'


# -- isolation ----------------------------------------------------------------------
def test_contextvar_isolates_owner_and_guests_concurrently(monkeypatch):
    """Many owner and guest calls in flight at once, interleaved at every await:
    each must get its own credentials, never another's."""
    store = S.get_store()
    store.set_guest_token(GUEST, json.loads(_creds('tok-guest-1', 'r1', [GA]).to_json()))
    store.set_guest_token(OTHER_GUEST, json.loads(_creds('tok-guest-2', 'r2', [GA]).to_json()))
    want = {None: 'owner-broad-access', GUEST: 'tok-guest-1', OTHER_GUEST: 'tok-guest-2'}

    async def one(who, i):
        # What _GuestGate does around a request.
        t = AM.current_guest.set(who)
        try:
            await asyncio.sleep(0.001 * (i % 7))
            got = []
            for _ in range(3):
                got.append(S.auth.get_credentials().token)
                await asyncio.sleep(0)
            return who, got
        finally:
            AM.current_guest.reset(t)

    async def main():
        whos = [None, GUEST, OTHER_GUEST] * 40
        return await asyncio.gather(*(one(w, i) for i, w in enumerate(whos)))

    for who, got in asyncio.run(main()):
        assert got == [want[who]] * 3, (who, got)
    assert AM.current_guest.get() is None


def test_http_concurrent_owner_and_guest_calls_isolated(client, monkeypatch):
    """The same through the real app: owner and guest requests at once over HTTP."""
    cb, gtok = sign_in(client, GUEST, '/analytics/mcp')
    cb, otok = sign_in(client, 'owner@example.com', '/analytics/mcp')  # narrow flow: keeps broad token
    guest_google = S.get_store().guest_token(GUEST)['token']
    app = client.app

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as ac:
            async def one(who, i):
                tok = gtok if who == 'guest' else otok
                r = await ac.post('/analytics/mcp', json={
                    'jsonrpc': '2.0', 'id': i, 'method': 'tools/call',
                    'params': {'name': 'analytics_list_properties', 'arguments': {}}},
                    headers=dict(H, Authorization='Bearer ' + tok['access_token']))
                return who, json.loads(r.json()['result']['content'][0]['text'])['properties'][0]['account']
            return await asyncio.gather(*(one('guest' if i % 2 else 'owner', i) for i in range(60)))

    results = client.portal.call(main)
    for who, account in results:
        assert account == (guest_google if who == 'guest' else 'owner-broad-access'), (who, account)


def teardown_module(_m):
    shutil.rmtree(_DATA, ignore_errors=True)
