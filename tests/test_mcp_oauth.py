import json
import os
import subprocess
import sys
import tempfile


def test_mcp_sign_in_end_to_end():
    with tempfile.TemporaryDirectory() as data_dir:
        env = dict(os.environ,
                   DATA_DIR=data_dir,
                   OWNER_EMAIL='owner@example.com',
                   PUBLIC_URL='https://gc.example.com',
                   GOOGLE_CREDENTIALS=json.dumps({'web': {
                       'client_id': 'c', 'client_secret': 's',
                       'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                       'token_uri': 'https://oauth2.googleapis.com/token',
                       'redirect_uris': ['https://gc.example.com/oauth/callback']}}))
        env.pop('GOOGLE_TOKEN_JSON', None)
        env.pop('LEGACY_SSE', None)
        here = os.path.dirname(__file__)
        r = subprocess.run([sys.executable, os.path.join(here, 'e2e_oauth.py')], env=env,
                           capture_output=True, text=True, timeout=180)
        print(r.stdout[-4000:])
        assert r.returncode == 0 and 'ALL PASS' in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
