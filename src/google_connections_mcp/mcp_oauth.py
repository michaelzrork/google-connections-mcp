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

Guests (GUEST_EMAILS) on /analytics/mcp only. Which endpoint a sign-in is for
is known before Google from the `resource` parameter of /authorize (RFC 8707:
MCP clients must send the address of the server they're connecting to, and the
SDK hands it to authorize() in AuthorizationParams). When it is /analytics/mcp
and there is at least one guest, Google is asked for only openid, email and
analytics.readonly. At the callback:
  - the owner keeps today's flow; through the narrow analytics sign-in their
    stored (broad) google_token is never replaced, and the MCP token is the
    owner's as always;
  - an invited guest on the analytics sign-in gets their Google token saved
    under guests[email] and MCP tokens tagged {guest: email, grant: analytics};
  - anyone else, or a guest on any other endpoint, is refused, nothing saved.
A guest-tagged token only works on /analytics/mcp (server.py, _GuestGate), and
stops working as soon as the email leaves GUEST_EMAILS (load_access_token).

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

from urllib.parse import urlparse

from google_connections_mcp.oauth_config import (
    ALL_SCOPES, ANALYTICS_GRANT, ANALYTICS_GUEST_PATH, ANALYTICS_GUEST_SCOPES,
    guest_emails, is_invited_guest,
)
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


class McpAccessToken(AccessToken):
    """An access token as the SDK knows it, plus who it belongs to: guest is
    None for the owner, else the guest's email (grant then says what it may
    reach; only 'analytics' exists)."""
    guest: Optional[str] = None
    grant: Optional[str] = None


class LenientClient(OAuthClientInformationFull):
    """A registered client that is never refused over a scope name.

    The SDK rejects any requested scope the client didn't register. This server
    has exactly one scope, so whatever a client asks for, it gets "mcp" (the
    Pockets by Hoopy server does the same: unknown scopes are cut, not refused).
    """

    def validate_scope(self, requested_scope):  # noqa: D401
        return [MCP_SCOPE]


FLOW_FULL = 'full'            # every scope: the owner's sign-in, as always
FLOW_ANALYTICS = 'analytics'  # openid, email, analytics.readonly: guests welcome


def flow_for_resource(resource: Optional[str]) -> str:
    """Which sign-in an /authorize request gets, decided before Google.

    By the RFC 8707 `resource` the MCP client sends (the connector's address).
    Only the path counts: the host is this server whatever spelling the client
    used. No guests configured, or no resource sent, means the full sign-in,
    exactly as before guests existed.
    """
    if not guest_emails() or not resource:
        return FLOW_FULL
    try:
        path = urlparse(str(resource)).path.rstrip('/')
    except Exception:
        return FLOW_FULL
    return FLOW_ANALYTICS if path == ANALYTICS_GUEST_PATH else FLOW_FULL


def _scopes_for(flow_kind: str):
    if flow_kind == FLOW_ANALYTICS:
        return list(ANALYTICS_GUEST_SCOPES)
    return ALL_SCOPES + SIGN_IN_SCOPES


def _google_flow(state: Optional[str] = None, scopes=None) -> Flow:
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        raise ValueError('GOOGLE_CREDENTIALS environment variable not set')
    return Flow.from_client_config(
        json.loads(creds_json),
        scopes=scopes or (ALL_SCOPES + SIGN_IN_SCOPES),
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
        flow_kind = flow_for_resource(params.resource)
        flow = _google_flow(state=pending_id, scopes=_scopes_for(flow_kind))
        extra = {}
        if flow_kind == FLOW_FULL:
            # Unchanged for the owner. Left off the narrow sign-in so a guest's
            # token carries only what that sign-in asked for.
            extra['include_granted_scopes'] = 'true'
        google_url, _ = flow.authorization_url(
            access_type='offline',
            prompt='consent',            # always return a refresh token
            **extra,
        )
        self.store.put('pending', pending_id, {
            'client_id': client.client_id,
            'redirect_uri': str(params.redirect_uri),
            'redirect_uri_provided_explicitly': params.redirect_uri_provided_explicitly,
            'code_challenge': params.code_challenge,
            'state': params.state,
            'resource': params.resource,
            'flow': flow_kind,
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
            flow_kind = pending.get('flow') or FLOW_FULL
            flow = _google_flow(state=state, scopes=_scopes_for(flow_kind))
            if pending.get('google_code_verifier'):
                flow.code_verifier = pending['google_code_verifier']
            flow.fetch_token(code=code)
        except Exception as e:
            print(f"[mcp_oauth] Google token exchange failed: {e}")
            return back_to_client(error='server_error', error_description='Google sign-in failed.')

        email = _email_from_google(flow)
        guest = None
        creds = flow.credentials
        if email and email == owner_email():
            if flow_kind == FLOW_FULL:
                self._save_owner_token(creds)
            elif not self.store.google_token() and not os.environ.get('GOOGLE_TOKEN_JSON'):
                # The narrow analytics sign-in never replaces the owner's broad
                # token. Only when there is no owner token at all is this one
                # kept, so the analytics tools work; /mcp's sign-in replaces it.
                self._save_owner_token(creds)
            else:
                print("[mcp_oauth] owner signed in through the analytics sign-in; kept the existing Google token")
        elif email and flow_kind == FLOW_ANALYTICS and is_invited_guest(email):
            guest = email
            info = json.loads(creds.to_json())
            if not info.get('refresh_token'):
                old = self.store.guest_token(email) or {}
                if old.get('refresh_token'):
                    info['refresh_token'] = old['refresh_token']
            self.store.set_guest_token(email, info)
            print("[mcp_oauth] a guest connected to /analytics/mcp")
        else:
            print(f"[mcp_oauth] refused sign-in from {email or 'an unknown account'}")
            return _page('This server belongs to someone else',
                         'Only the owner’s Google account can connect to it. Nothing was saved.', 403)

        mcp_code = secrets.token_urlsafe(32)
        self.store.put('codes', mcp_code, {
            'guest': guest,
            'grant': ANALYTICS_GRANT if guest else None,
            'client_id': pending['client_id'],
            'redirect_uri': pending['redirect_uri'],
            'redirect_uri_provided_explicitly': pending['redirect_uri_provided_explicitly'],
            'code_challenge': pending['code_challenge'],
            'resource': pending.get('resource'),
            'scopes': [MCP_SCOPE],
            'expires_at': time.time() + CODE_TTL,
        })
        return back_to_client(code=mcp_code)

    def _save_owner_token(self, creds) -> None:
        """Today's owner path, unchanged."""
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

    # -- codes and tokens ---------------------------------------------------------
    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> Optional[AuthorizationCode]:
        row = self.store.get('codes', authorization_code)
        if not row or row['client_id'] != client.client_id:
            return None
        return AuthorizationCode(code=authorization_code, **{k: row[k] for k in (
            'scopes', 'expires_at', 'client_id', 'code_challenge', 'redirect_uri',
            'redirect_uri_provided_explicitly', 'resource')})

    def _issue(self, client_id: str, scopes, resource: Optional[str],
               guest: Optional[str] = None, grant: Optional[str] = None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(40), secrets.token_urlsafe(48)
        now = int(time.time())
        pair = token_hash(refresh)
        # The owner's rows look exactly as they always have; a guest's carry
        # who it is and what it may reach.
        tag = {'guest': guest, 'grant': grant} if guest else {}
        self.store.put('access', token_hash(access), {
            'client_id': client_id, 'scopes': scopes, 'resource': resource,
            'expires_at': now + ACCESS_TTL, 'refresh': pair, **tag})
        self.store.put('refresh', pair, {
            'client_id': client_id, 'scopes': scopes, 'resource': resource,
            'expires_at': now + REFRESH_TTL, **tag})
        self.store.mark_connected()
        return OAuthToken(access_token=access, token_type='Bearer', expires_in=ACCESS_TTL,
                          refresh_token=refresh, scope=' '.join(scopes))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        row = self.store.pop('codes', authorization_code.code)
        if not row:
            raise TokenError('invalid_grant', 'That code was already used.')
        guest = row.get('guest')
        if guest and not is_invited_guest(guest):
            raise TokenError('invalid_grant', 'This account is no longer invited.')
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource,
                           guest=guest, grant=row.get('grant'))

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> Optional[RefreshToken]:
        row = self.store.get('refresh', token_hash(refresh_token))
        if not row or row['client_id'] != client.client_id or row['expires_at'] < time.time():
            return None
        if row.get('guest') and not is_invited_guest(row['guest']):
            return None
        return RefreshToken(token=refresh_token, client_id=row['client_id'], scopes=row['scopes'], expires_at=row['expires_at'])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes) -> OAuthToken:
        h = token_hash(refresh_token.token)
        row = self.store.pop('refresh', h)
        if not row:
            raise TokenError('invalid_grant', 'Refresh token is no longer valid.')
        self.store.delete_where('access', refresh=h)  # its access tokens go with it
        if row.get('guest') and not is_invited_guest(row['guest']):
            raise TokenError('invalid_grant', 'This account is no longer invited.')
        return self._issue(client.client_id, row['scopes'], row.get('resource'),
                           guest=row.get('guest'), grant=row.get('grant'))

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        row = self.store.get('access', token_hash(token))
        if not row or row['expires_at'] < time.time():
            return None
        guest = row.get('guest')
        if guest and not is_invited_guest(guest):
            # Taken off GUEST_EMAILS: refused on the very next request.
            return None
        return McpAccessToken(token=token, client_id=row['client_id'], scopes=row['scopes'],
                              expires_at=row['expires_at'], resource=row.get('resource'),
                              guest=guest, grant=row.get('grant'))

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
