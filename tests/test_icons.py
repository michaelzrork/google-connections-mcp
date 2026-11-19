"""Icons: the favicon and /icons/* files are served without a sign-in, with the
right content types, and every endpoint's serverInfo names its own icon.
(test_guests.py checks the same serverInfo through a real signed-in initialize.)"""
import json
import os
import tempfile

# The server reads these at import time. setdefault: when pytest has already
# imported test_guests.py, its values (the same ones) are in place.
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='gc-icons-'))
os.environ.setdefault('OWNER_EMAIL', 'owner@example.com')
os.environ.setdefault('PUBLIC_URL', 'https://gc.example.com')
os.environ.setdefault('GOOGLE_CREDENTIALS', json.dumps({'web': {
    'client_id': 'c', 'client_secret': 's',
    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
    'token_uri': 'https://oauth2.googleapis.com/token',
    'redirect_uris': ['https://gc.example.com/oauth/callback']}}))

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import google_connections_mcp.server as S  # noqa: E402
from google_connections_mcp.mcp_oauth import public_url  # noqa: E402

SLUGS = [slug for slug, *_ in S.PRODUCTS]
NAMES = ['google-connections'] + SLUGS


@pytest.fixture(scope='module')
def client():
    # No `with`: the lifespan (MCP session managers) can run once per process and
    # test_guests.py runs it; none of these requests reach a session manager.
    return TestClient(S.build_app(), base_url='https://gc.example.com')


@pytest.mark.parametrize('path,ctype,magic', [
    ('/favicon.ico', 'image/x-icon', b'\x00\x00\x01\x00'),
    ('/favicon.svg', 'image/svg+xml', b'<svg'),
    ('/apple-touch-icon.png', 'image/png', b'\x89PNG'),
])
def test_favicons_served_without_sign_in(client, path, ctype, magic):
    r = client.get(path)  # no Authorization header
    assert r.status_code == 200, r.text[:200]
    assert r.headers['content-type'].split(';')[0] == ctype
    assert r.content.startswith(magic)
    assert 'max-age' in r.headers.get('cache-control', '')


@pytest.mark.parametrize('name', NAMES)
def test_every_endpoint_icon_served_as_svg_and_png(client, name):
    svg = client.get(f'/icons/{name}.svg')
    assert svg.status_code == 200 and svg.headers['content-type'].startswith('image/svg+xml')
    assert svg.content.startswith(b'<svg')
    png = client.get(f'/icons/{name}.png')
    assert png.status_code == 200 and png.headers['content-type'] == 'image/png'
    assert png.content.startswith(b'\x89PNG')
    assert png.content[16:24] == (256).to_bytes(4, 'big') * 2  # IHDR: 256x256


def test_home_page_links_the_favicon(client):
    r = client.get('/')
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
    assert 'rel="icon"' in r.text and '/favicon.ico' in r.text and 'apple-touch-icon' in r.text


def test_unknown_icon_is_404(client):
    assert client.get('/icons/nope.png').status_code == 404


def test_icons_do_not_open_the_mcp_endpoints(client):
    # Serving icons must not loosen the sign-in on the MCP endpoints.
    for path in ['/mcp'] + [f'/{s}/mcp' for s in SLUGS]:
        r = client.post(path, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                        headers={'Accept': 'application/json, text/event-stream'})
        assert r.status_code == 401, (path, r.status_code)


def _server_info(server):
    return server._mcp_server.create_initialization_options()


def test_server_info_names_each_endpoints_icon():
    base = public_url()
    servers = {'google-connections': S.mcp, **S.product_servers}
    assert set(servers) == set(NAMES)
    for name, server in servers.items():
        icons = _server_info(server).icons
        assert [i.src for i in icons] == [f'{base}/icons/{name}.png', f'{base}/icons/{name}.svg'], name
        assert icons[0].mimeType == 'image/png' and icons[0].sizes == ['256x256']
        assert icons[1].mimeType == 'image/svg+xml'
