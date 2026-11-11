"""
Sign-in for the MCP endpoint (/mcp): an OAuth 2.1 authorization server whose
login IS Google.

How a connection goes (Claude, ChatGPT, any MCP client):
  1. The client calls /mcp with no token, gets 401, and finds this server's
     OAuth endpoints through the discovery documents the SDK serves.
  2. It registers itself (/register) and sends you to /authorize.
  3. /authorize sends you straight on to Google's sign-in, asking for every
     Google permission the tools need (the same list as ALL_SCOPES) plus your
     email address.
  4. Google sends you back to /oauth/callback. If the email is OWNER_EMAIL,
     the Google token is saved (token store) and the client gets a one-time
     code; any other account is turned away and nothing is saved.
  5. The client trades the code for an access token (1 hour) and a refresh
     token (90 days, replaced on every use) at /token, and calls /mcp with it.

So reconnecting the connector in claude.ai is also how new Google permissions
are granted: one sign-in does both. The MCP SDK (mcp.server.auth) supplies the
OAuth endpoints, discovery, PKCE checks and the bearer-token check on /mcp;
this module supplies the storage and the Google step.
"""

import base64
import json
import os
import secrets
import time
from typing import Optional

import requests
from google_auth_oauthlib.flow import Flow
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from google_connections_mcp.oauth_config import ALL_SCOPES
from google_connections_mcp.token_store import get_store, token_hash

# Google can return the granted scopes in a different order or with extras
# (include_granted_scopes); oauthlib treats any difference as an error unless told not to.
os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')

MCP_SCOPE = 'mcp'
ACCESS_TTL = 60 * 60              # 1 hour
REFRESH_TTL = 90 * 24 * 60 * 60   # 90 days, rotated on every use
CODE_TTL = 5 * 60
PENDING_TTL = 15 * 60
SIGN_IN_SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email']


def public_url() -> str:
    """This server's public address, e.g. https://my-app.up.railway.app"""
    url = os.environ.get('PUBLIC_URL') or os.environ.get('MCP_PUBLIC_URL')
    if not url and os.environ.get('RAILWAY_PUBLIC_DOMAIN'):
        url = 'https://' + os.environ['RAILWAY_PUBLIC_DOMAIN']
    if not url:
        url = f"http://localhost:{os.environ.get('PORT', '8000')}"
    return url.rstrip('/')


def google_redirect_uri() -> str:
    # The same callback the original /oauth/start flow uses, so the redirect
    # URI already registered in Google Cloud keeps working.
    return public_url() + '/oauth/callback'


def owner_email() -> str:
    return (os.environ.get('OWNER_EMAIL') or '').strip().lower()


class LenientClient(OAuthClientInformationFull):
    """A registered client that is never refused over a scope name.

    The SDK rejects any requested scope the client didn't register. This server
    has exactly one scope, so whatever a client asks for, it gets "mcp" (the
    Pockets by Hoopy server does the same: unknown scopes are cut, not refused).
    """

    def validate_scope(self, requested_scope):  # noqa: D401
        return [MCP_SCOPE]


def _google_flow(state: Optional[str] = None) -> Flow:
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        raise ValueError('GOOGLE_CREDENTIALS environment variable not set')
    return Flow.from_client_config(
        json.loads(creds_json),
        scopes=ALL_SCOPES + SIGN_IN_SCOPES,
        redirect_uri=google_redirect_uri(),
        state=state,
    )


def _email_from_google(flow: Flow) -> Optional[str]:
    """The signed-in Google account's email.

    The ID token comes straight from Google's token endpoint over TLS, so its
    claims can be read without checking the signature (OpenID Connect Core
    3.1.3.7). If it's missing, ask Google's userinfo endpoint instead.
    """
    tok = getattr(flow, 'oauth2session', None)
    id_token = (tok.token or {}).get('id_token') if tok else None
    if id_token:
        try:
            payload = id_token.split('.')[1]
            payload += '=' * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            if claims.get('email') and claims.get('email_verified', True):
                return claims['email'].lower()
        except Exception:
            pass
    try:
        r = requests.get('https://openidconnect.googleapis.com/v1/userinfo',
                         headers={'Authorization': f'Bearer {flow.credentials.token}'}, timeout=10)
        if r.ok and r.json().get('email'):
            return r.json()['email'].lower()
    except Exception:
        pass
    return None


class GoogleOAuthProvider:
    """OAuthAuthorizationServerProvider for the SDK, backed by the token store."""

    def __init__(self, on_google_token=None):
        self.store = get_store()
        self.on_google_token = on_google_token  # called with the new Google credentials

    # -- clients ----------------------------------------------------------------
    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        info = self.store.get('clients', client_id)
        return LenientClient.model_validate(info) if info else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.scope:
            client_info.scope = MCP_SCOPE
        self.store.put('clients', client_info.client_id, json.loads(client_info.model_dump_json()))

    # -- authorize: hand off to Google -------------------------------------------
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not owner_email():
            raise AuthorizeError('server_error', 'OWNER_EMAIL is not set on this server, so nobody can sign in.')
        self.store.prune()
        pending_id = secrets.token_urlsafe(32)
        flow = _google_flow(state=pending_id)
        google_url, _ = flow.authorization_url(
            access_type='offline',
            prompt='consent',            # always return a refresh token
            include_granted_scopes='true',
        )
        self.store.put('pending', pending_id, {
            'client_id': client.client_id,
            'redirect_uri': str(params.redirect_uri),
            'redirect_uri_provided_explicitly': params.redirect_uri_provided_explicitly,
            'code_challenge': params.code_challenge,
            'state': params.state,
            'resource': params.resource,
            'google_code_verifier': getattr(flow, 'code_verifier', None),
            'expires_at': time.time() + PENDING_TTL,
        })
        return google_url

    async def google_callback(self, request: Request):
        """Google's redirect back. Returns a response, or None when the state
        isn't one of ours (the original /oauth/start flow uses this path too)."""
        state = request.query_params.get('state')
        pending = self.store.get('pending', state) if state else None
        if not pending:
            return None
        self.store.pop('pending', state)
        if pending.get('expires_at', 0) < time.time():
            return _page('That sign-in took too long', 'Start the connection again from your AI app.', 400)

        def back_to_client(**params):
            return RedirectResponse(construct_redirect_uri(pending['redirect_uri'], state=pending.get('state'), **params), status_code=302)

        if request.query_params.get('error'):
            return back_to_client(error='access_denied', error_description='Google sign-in was cancelled.')
        code = request.query_params.get('code')
        if not code:
            return back_to_client(error='invalid_request', error_description='Google returned no code.')
        try:
            flow = _google_flow(state=state)
            if pending.get('google_code_verifier'):
                flow.code_verifier = pending['google_code_verifier']
            flow.fetch_token(code=code)
        except Exception as e:
            print(f"[mcp_oauth] Google token exchange failed: {e}")
            return back_to_client(error='server_error', error_description='Google sign-in failed.')

        email = _email_from_google(flow)
        if not email or email != owner_email():
            print(f"[mcp_oauth] refused sign-in from {email or 'an unknown account'}")
            return _page('This server belongs to someone else',
                         'Only the owner’s Google account can connect to it. Nothing was saved.', 403)

        creds = flow.credentials
        if not creds.refresh_token:
            # Without one, the token dies in an hour. prompt=consent should
            # always give one; keep the old refresh token if Google didn't.
            old = self.store.google_token() or {}
            if old.get('refresh_token'):
                creds._refresh_token = old['refresh_token']
        if self.on_google_token:
            self.on_google_token(creds)
        else:
            self.store.set_google_token(json.loads(creds.to_json()))

        mcp_code = secrets.token_urlsafe(32)
        self.store.put('codes', mcp_code, {
            'client_id': pending['client_id'],
            'redirect_uri': pending['redirect_uri'],
            'redirect_uri_provided_explicitly': pending['redirect_uri_provided_explicitly'],
            'code_challenge': pending['code_challenge'],
            'resource': pending.get('resource'),
            'scopes': [MCP_SCOPE],
            'expires_at': time.time() + CODE_TTL,
        })
        return back_to_client(code=mcp_code)

    # -- codes and tokens ---------------------------------------------------------
    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> Optional[AuthorizationCode]:
        row = self.store.get('codes', authorization_code)
        if not row or row['client_id'] != client.client_id:
            return None
        return AuthorizationCode(code=authorization_code, **{k: row[k] for k in (
            'scopes', 'expires_at', 'client_id', 'code_challenge', 'redirect_uri',
            'redirect_uri_provided_explicitly', 'resource')})

    def _issue(self, client_id: str, scopes, resource: Optional[str]) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(40), secrets.token_urlsafe(48)
        now = int(time.time())
        pair = token_hash(refresh)
        self.store.put('access', token_hash(access), {
            'client_id': client_id, 'scopes': scopes, 'resource': resource,
            'expires_at': now + ACCESS_TTL, 'refresh': pair})
        self.store.put('refresh', pair, {
            'client_id': client_id, 'scopes': scopes, 'resource': resource,
            'expires_at': now + REFRESH_TTL})
        self.store.mark_connected()
        return OAuthToken(access_token=access, token_type='Bearer', expires_in=ACCESS_TTL,
                          refresh_token=refresh, scope=' '.join(scopes))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        if not self.store.pop('codes', authorization_code.code):
            raise TokenError('invalid_grant', 'That code was already used.')
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> Optional[RefreshToken]:
        row = self.store.get('refresh', token_hash(refresh_token))
        if not row or row['client_id'] != client.client_id or row['expires_at'] < time.time():
            return None
        return RefreshToken(token=refresh_token, client_id=row['client_id'], scopes=row['scopes'], expires_at=row['expires_at'])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes) -> OAuthToken:
        h = token_hash(refresh_token.token)
        row = self.store.pop('refresh', h)
        if not row:
            raise TokenError('invalid_grant', 'Refresh token is no longer valid.')
        self.store.delete_where('access', refresh=h)  # its access tokens go with it
        return self._issue(client.client_id, row['scopes'], row.get('resource'))

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        row = self.store.get('access', token_hash(token))
        if not row or row['expires_at'] < time.time():
            return None
        return AccessToken(token=token, client_id=row['client_id'], scopes=row['scopes'],
                           expires_at=row['expires_at'], resource=row.get('resource'))

    async def revoke_token(self, token) -> None:
        h = token_hash(token.token)
        if isinstance(token, RefreshToken):
            self.store.pop('refresh', h)
            self.store.delete_where('access', refresh=h)
        else:
            row = self.store.pop('access', h)
            if row and row.get('refresh'):
                self.store.pop('refresh', row['refresh'])


def _page(title: str, text: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1 style='font-size:1.3rem'>{title}</h1><p>{text}</p></body>", status_code=status)
