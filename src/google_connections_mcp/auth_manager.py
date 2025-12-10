"""
Unified OAuth Authentication Module
Handles authentication for all Google services
"""

import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
import gspread

from google_connections_mcp.oauth_config import ALL_SCOPES


class GoogleAuthManager:
    """Manages OAuth credentials for all Google services"""
    
    def __init__(self):
        self.credentials = None
        self._load_credentials()
    
    def _load_credentials(self):
        """Load credentials from environment variable"""
        token_json = os.environ.get('GOOGLE_TOKEN_JSON')
        if token_json:
            try:
                creds_info = json.loads(token_json)
                self.credentials = Credentials.from_authorized_user_info(
                    creds_info,
                    ALL_SCOPES
                )
            except Exception as e:
                print(f"Error loading token: {e}")
                self.credentials = None
    
    def _refresh_if_needed(self):
        """Refresh credentials if expired"""
        if self.credentials and self.credentials.expired and self.credentials.refresh_token:
            try:
                self.credentials.refresh(GoogleRequest())
                # Print refreshed token so user can update Railway
                print("="*60)
                print("TOKEN REFRESHED - UPDATE GOOGLE_TOKEN_JSON:")
                print(self.credentials.to_json())
                print("="*60)
                return True
            except Exception as e:
                print(f"Error refreshing token: {e}")
                return False
        return True
    
    def get_credentials(self):
        """Get valid credentials, refreshing if necessary"""
        if not self.credentials or not self.credentials.valid:
            if not self._refresh_if_needed():
                raise Exception("No valid credentials. Visit /oauth/start to authorize")
        return self.credentials
    
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
        creds = self.get_credentials()
        return build('calendar', 'v3', credentials=creds)
    
    def get_gmail_service(self):
        """Get authenticated Gmail service"""
        creds = self.get_credentials()
        return build('gmail', 'v1', credentials=creds)
    
    def get_drive_service(self):
        """Get authenticated Google Drive service"""
        creds = self.get_credentials()
        return build('drive', 'v3', credentials=creds)
    
    def get_docs_service(self):
        """Get authenticated Google Docs service"""
        creds = self.get_credentials()
        return build('docs', 'v1', credentials=creds)
    
    def get_sheets_service(self):
        """Get authenticated Google Sheets service (API client)"""
        creds = self.get_credentials()
        return build('sheets', 'v4', credentials=creds)
    
    def get_sheets_client(self):
        """Get gspread client for Google Sheets"""
        creds = self.get_credentials()
        return gspread.authorize(creds)
    
    def get_tasks_service(self):
        """Get authenticated Google Tasks service"""
        creds = self.get_credentials()
        return build('tasks', 'v1', credentials=creds)
    
    def get_keep_service(self):
        """Get authenticated Google Keep service"""
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
