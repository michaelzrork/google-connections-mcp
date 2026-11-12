"""
Google Connections MCP Server
A Model Context Protocol server for Google Workspace APIs
"""

__version__ = "0.1.0"
__all__ = ["main"]


def main():
    # Imported here, not at package import, so the local Markdown server
    # (local_markdown.py) can load without the hosted server's sign-in setup.
    from google_connections_mcp.server import main as _main
    _main()
