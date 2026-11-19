"""
Unified OAuth Authentication Module
Handles authentication for all Google services
"""

import os
import json
from contextvars import ContextVar
from typing import Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
import gspread

from google_connections_mcp.oauth_config import ALL_SCOPES, ANALYTICS_GUEST_SCOPES
from google_connections_mcp.token_store import get_store


# Whose Google account the current request acts for. None = the owner (the
# default, and what every request had before guests existed). A guest's email
# when the request came in on /analytics/mcp with a guest's MCP token.
#
# Set per request by the gate that sits right after the bearer-token check
# (server.py, _GuestGate), and read here. A ContextVar, not an attribute on the
# shared GoogleAuthManager: every request runs in its own asyncio task with its
# own copy of the context, so two calls in flight at once each see their own
# value and one user's credentials can never be handed to another's call.
current_guest: ContextVar[Optional[str]] = ContextVar('current_guest', default=None)


class GuestNotAllowed(Exception):
    """A guest request reached something only the owner may use."""


class GoogleAuthManager:
    """Manages OAuth credentials for all Google services"""
    
    def __init__(self):
        self.credentials = None
        self._load_credentials()
    
    def _load_credentials(self):
        """Load the Google token: the one the sign-in saved (token store) first,
        then the GOOGLE_TOKEN_JSON variable (the old copy-from-the-logs setup)."""
        stored = get_store().google_token()
        token_json = json.dumps(stored) if stored else os.environ.get('GOOGLE_TOKEN_JSON')
        if token_json:
            try:
                creds_info = json.loads(token_json)
                # Use the scopes the token was actually GRANTED (saved in the
                # token JSON), not the app's full list. A refresh asks Google
                # for exactly these scopes, and asking for one the token was
                # never granted (say, a scope added to ALL_SCOPES since you
                # last authorized) can fail the refresh and take every tool
                # down until you re-authorize. Older tokens without a
                # "scopes" entry fall back to ALL_SCOPES as before.
                self.credentials = Credentials.from_authorized_user_info(
                    creds_info,
                    None if creds_info.get('scopes') else ALL_SCOPES
                )
            except Exception as e:
                print(f"Error loading token: {e}")
                self.credentials = None
    
    def _refresh_if_needed(self):
        """Refresh credentials if expired"""
        if self.credentials and self.credentials.expired and self.credentials.refresh_token:
            try:
                self.credentials.refresh(GoogleRequest())
                # Keep the refreshed token in the store (it survives restarts
                # when DATA_DIR is a volume). It used to be printed to the
                # logs for copying into GOOGLE_TOKEN_JSON; no longer needed.
                try:
                    get_store().set_google_token(json.loads(self.credentials.to_json()))
                except Exception as e:
                    print(f"Could not save refreshed token: {e}")
                return True
            except Exception as e:
                print(f"Error refreshing token: {e}")
                return False
        return True
    
    def _guest_credentials(self, email):
        """A guest's own Google credentials, from the store, refreshed and saved
        back under the guest when expired. Built fresh per call (no shared
        object), so nothing about one guest can linger into another call."""
        store = get_store()
        info = store.guest_token(email)
        if not info:
            raise Exception("No Google sign-in saved for this account. Reconnect the connector.")
        creds = Credentials.from_authorized_user_info(
            info, None if info.get('scopes') else ANALYTICS_GUEST_SCOPES)
        if not creds.valid:
            if not creds.refresh_token:
                raise Exception("Your Google sign-in has expired. Reconnect the connector.")
            try:
                creds.refresh(GoogleRequest())
            except Exception as e:
                raise Exception(f"Your Google sign-in could not be refreshed ({e}). Reconnect the connector.")
            try:
                store.set_guest_token(email, json.loads(creds.to_json()))
            except Exception as e:
                print(f"Could not save a guest's refreshed token: {e}")
        return creds

    def _owner_only(self):
        if current_guest.get():
            raise GuestNotAllowed("Guests can use only the Google Analytics tools.")

    def get_credentials(self):
        """Get valid credentials, refreshing if necessary.

        The owner's (the single stored google_token, exactly as before) unless
        this request belongs to a guest on /analytics/mcp."""
        guest = current_guest.get()
        if guest:
            return self._guest_credentials(guest)
        if not self.credentials or not self.credentials.valid:
            if not self._refresh_if_needed():
                raise Exception("No valid credentials. Visit /oauth/start to authorize")
        return self.credentials
    
    def set_credentials(self, credentials):
        """Install a Google token from the sign-in and keep it in the store."""
        self.credentials = credentials
        get_store().set_google_token(json.loads(credentials.to_json()))

    def is_authenticated(self):
        """Check if we have valid credentials"""
        try:
            self.get_credentials()
            return True
        except:
            return False
    
    # Service-specific getters
    
    def get_calendar_service(self):
        """Get authenticated Google Calendar service"""
        self._owner_only()
        creds = self.get_credentials()
        return build('calendar', 'v3', credentials=creds)
    
    def get_gmail_service(self):
        """Get authenticated Gmail service"""
        self._owner_only()
        creds = self.get_credentials()
        return build('gmail', 'v1', credentials=creds)
    
    def get_drive_service(self):
        """Get authenticated Google Drive service"""
        self._owner_only()
        creds = self.get_credentials()
        return build('drive', 'v3', credentials=creds)
    
    def get_docs_service(self):
        """Get authenticated Google Docs service"""
        self._owner_only()
        creds = self.get_credentials()
        return build('docs', 'v1', credentials=creds)
    
    def get_sheets_service(self):
        """Get authenticated Google Sheets service (API client)"""
        self._owner_only()
        creds = self.get_credentials()
        return build('sheets', 'v4', credentials=creds)
    
    def get_sheets_client(self):
        """Get gspread client for Google Sheets"""
        self._owner_only()
        creds = self.get_credentials()
        return gspread.authorize(creds)
    
    def get_tasks_service(self):
        """Get authenticated Google Tasks service"""
        self._owner_only()
        creds = self.get_credentials()
        return build('tasks', 'v1', credentials=creds)
    
    def has_scope(self, scope):
        """True if the current token was granted this scope"""
        creds = self.get_credentials()
        granted = getattr(creds, 'granted_scopes', None) or creds.scopes or []
        return scope in granted

    def get_search_console_service(self):
        """Get authenticated Search Console service"""
        self._owner_only()
        creds = self.get_credentials()
        return build('searchconsole', 'v1', credentials=creds)

    def get_analytics_data_service(self):
        """Get authenticated Google Analytics Data API (GA4 reports) service"""
        creds = self.get_credentials()
        return build('analyticsdata', 'v1beta', credentials=creds)

    def get_analytics_admin_service(self):
        """Get authenticated Google Analytics Admin API service (property list)"""
        creds = self.get_credentials()
        return build('analyticsadmin', 'v1beta', credentials=creds)

    def get_keep_service(self):
        """Get authenticated Google Keep service"""
        self._owner_only()
        creds = self.get_credentials()
        return build('keep', 'v1', credentials=creds)


# Global auth manager instance
auth_manager = GoogleAuthManager()


def get_auth_manager():
    """Get the global auth manager instance"""
    return auth_manager


def create_oauth_flow(redirect_uri):
    """Create OAuth flow for initial authorization"""
    credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS environment variable not set")
    
    credentials_info = json.loads(credentials_json)
    
    flow = Flow.from_client_config(
        credentials_info,
        scopes=ALL_SCOPES,
        redirect_uri=redirect_uri
    )
    
    return flow
