"""
Markdown Drive, local: the six markdown_* tools over stdio, for an editor on
your own computer (VS Code with Continue or Cline and an Ollama model).

It signs in to Google on this computer with its own Desktop OAuth client and
asks only for Drive. Nothing goes through the hosted server.

    MARKDOWN_CLIENT_SECRET   path to the Desktop client's JSON (required)
    MARKDOWN_FOLDER_ID       the one Drive folder it may use (strongly recommended)
    MARKDOWN_TOKEN_PATH      where to keep the sign-in (default: your config folder)

Sign in once in a terminal:   python -m google_connections_mcp.local_markdown --login
Then the editor starts it:    python -m google_connections_mcp.local_markdown

Anything printed goes to stderr: stdout is the MCP channel and must stay clean.
"""

import os
import sys

from mcp.server.fastmcp import FastMCP

from google_connections_mcp.markdown_drive import MARKDOWN_INSTRUCTIONS, register_markdown_tools

SCOPES = ['https://www.googleapis.com/auth/drive']


def _log(*args):
    print(*args, file=sys.stderr, flush=True)


def token_path() -> str:
    explicit = os.environ.get('MARKDOWN_TOKEN_PATH')
    if explicit:
        return os.path.expanduser(explicit)
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    return os.path.join(base, 'markdown-drive-mcp', 'token.json')


def _save(creds) -> None:
    path = token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(creds.to_json())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def get_credentials(interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if os.path.exists(token_path()):
        creds = Credentials.from_authorized_user_file(token_path(), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except Exception as e:
            _log(f'[markdown] could not refresh the Google sign-in: {e}')
    secret = os.environ.get('MARKDOWN_CLIENT_SECRET')
    if not secret or not os.path.exists(os.path.expanduser(secret)):
        raise RuntimeError('Not signed in. Set MARKDOWN_CLIENT_SECRET to your Desktop OAuth client JSON and run '
                           'python -m google_connections_mcp.local_markdown --login')
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(os.path.expanduser(secret), SCOPES)
    # Opens the browser; the redirect lands on a one-off local port. Works from an
    # editor too, but signing in once with --login in a terminal is smoother.
    creds = flow.run_local_server(port=0, open_browser=True)
    _save(creds)
    return creds


_service = None


def drive_service():
    global _service
    from googleapiclient.discovery import build
    creds = get_credentials()
    if _service is None or getattr(_service, '_creds_token', None) != creds.token:
        _service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        _service._creds_token = creds.token
    return _service


def build_server() -> FastMCP:
    server = FastMCP('Markdown Drive', instructions=MARKDOWN_INSTRUCTIONS)
    register_markdown_tools(server, drive_service)
    return server


def main():
    if '--login' in sys.argv:
        get_credentials(interactive=True)
        _log(f'Signed in. The sign-in is saved at {token_path()}')
        folder = os.environ.get('MARKDOWN_FOLDER_ID')
        _log(f'Folder: {folder}' if folder else 'No MARKDOWN_FOLDER_ID set: the tools can reach every .md file in your Drive.')
        return
    if not os.environ.get('MARKDOWN_FOLDER_ID'):
        _log('[markdown] MARKDOWN_FOLDER_ID is not set: every .md file in your Drive is reachable.')
    build_server().run('stdio')


if __name__ == '__main__':
    main()
