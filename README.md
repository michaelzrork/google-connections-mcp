# Google Connections MCP

A Model Context Protocol (MCP) server that provides AI assistants with access to Google Workspace APIs. Deploy once on Railway (or any hosting platform), connect from Claude or any MCP-compatible client.

## Features

- **Google Sheets** - Query, append, update, and delete rows with formula-safe cell-level updates
- **Google Calendar** - List, create, update, and delete events across all your calendars
- **Gmail** - Read, send, search, label, archive, and manage messages
- **Google Tasks** - Full task and task list management
- **Google Drive** - Search files, get metadata, and download content (text, PDFs, images)
- **Time** - Get current date/time in any IANA timezone

## How It Works

1. You deploy this server to Railway (or similar)
2. You set up OAuth credentials in Google Cloud Console
3. You authorize with your Google account once
4. Your AI assistant connects to the server and can access your Google services

Each user deploys their own instance with their own credentials - your data stays yours.

## Quick Start

### Prerequisites

- Python 3.10+
- A Google Cloud project with OAuth 2.0 credentials
- Railway account (free tier works) or another hosting platform
- Claude.ai account (or another MCP-compatible client)

### 1. Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., "My MCP Server")
3. Enable these APIs (APIs & Services → Enable APIs):
   - Google Calendar API
   - Gmail API
   - Google Drive API
   - Google Sheets API
   - Google Tasks API

4. Configure OAuth consent screen (APIs & Services → OAuth consent screen):
   - User Type: **External**
   - App name: Whatever you want (e.g., "My Google Connections")
   - User support email: Your email
   - Developer contact: Your email
   - Scopes: Add the following:
     - `https://www.googleapis.com/auth/calendar`
     - `https://www.googleapis.com/auth/gmail.modify`
     - `https://www.googleapis.com/auth/gmail.send`
     - `https://www.googleapis.com/auth/drive`
     - `https://www.googleapis.com/auth/spreadsheets`
     - `https://www.googleapis.com/auth/tasks`
   - Test users: Add your email
   - **Important**: Click "Publish App" to move from Testing to Production (this prevents tokens from expiring every 7 days)

5. Create OAuth 2.0 credentials (APIs & Services → Credentials):
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: **Web application**
   - Name: Whatever you want
   - Authorized redirect URIs: `https://your-app-name.up.railway.app/oauth/callback`
     (Use your actual Railway URL - you'll get this after deploying)
   - Click "Create" and download the JSON file

### 2. Deploy to Railway

1. Fork this repository to your GitHub account
2. Go to [Railway](https://railway.app/) and create a new project
3. Choose "Deploy from GitHub repo" and select your fork
4. Railway will auto-detect the Python app and start deploying
5. Go to Settings → Networking → Generate Domain (note this URL)
6. Go back to Google Cloud and update your OAuth redirect URI with the actual Railway URL

7. Add environment variables in Railway (Settings → Variables):
   ```
   GOOGLE_CREDENTIALS = (paste the entire contents of your downloaded OAuth JSON file)
   ```
   
8. Trigger a redeploy after adding the environment variable

### 3. Authorize Your Google Account

1. Visit `https://your-railway-url/oauth/start` in your browser
2. Sign in with Google and grant permissions
3. You'll see a success message
4. Check Railway logs - you'll see the token JSON printed there
5. Copy the token JSON and add it as another environment variable:
   ```
   GOOGLE_TOKEN_JSON = (paste the token JSON from the logs)
   ```
6. Redeploy one more time

### 4. Connect to Claude

1. In Claude.ai, go to Settings → Connections
2. Add a new MCP connection:
   - URL: `https://your-railway-url/sse`
3. The connection should show as active

You're done! Claude can now access your Google services.

## Available Tools

### Google Sheets

| Tool | Description |
|------|-------------|
| `query_sheet` | Query with filters, sorting, column selection. Supports date comparisons. |
| `append_rows` | Add new rows (formula-safe - won't overwrite formula columns) |
| `update_row_by_id` | Update specific cells by ID column (formula-safe) |
| `delete_row_by_id` | Delete a row by ID column |
| `find_row_by_id` | Find row number and data by ID |

**Query Operators**: `==`, `!=`, `>`, `<`, `>=`, `<=`, `in`, `not in`, `contains`, `not contains`, `is_null`, `not_null`

**Date Handling**: Date columns are automatically parsed and compared correctly, regardless of format (`MM/DD/YYYY`, `YYYY-MM-DD`, etc.)

### Google Calendar

| Tool | Description |
|------|-------------|
| `list_calendars` | List all calendars |
| `list_calendar_events` | List events with time range and search |
| `get_calendar_event` | Get specific event details |
| `create_calendar_event` | Create new event with optional attendees/reminders |
| `update_calendar_event` | Modify existing event |
| `delete_calendar_event` | Remove event |

### Gmail

| Tool | Description |
|------|-------------|
| `list_gmail_messages` | Search/list messages with Gmail query syntax |
| `get_gmail_message` | Get full message content |
| `send_gmail_message` | Send email (with CC/BCC support) |
| `modify_gmail_message` | Add/remove labels |
| `batch_modify_gmail` | Bulk label operations |
| `mark_gmail_read` / `mark_gmail_unread` | Mark messages as read/unread |
| `star_gmail` / `unstar_gmail` | Star/unstar messages |
| `archive_gmail` | Archive messages |
| `move_to_inbox` | Move messages back to inbox |
| `trash_gmail` | Move to trash |
| `spam_gmail` | Mark as spam |
| `list_gmail_labels` | List all labels |
| `create_gmail_label` | Create new label |

### Google Tasks

| Tool | Description |
|------|-------------|
| `list_task_lists` | List all task lists |
| `create_task_list` / `delete_task_list` / `update_task_list` | Manage task lists |
| `list_tasks` | List tasks (with completed/hidden options) |
| `get_task` | Get task details |
| `create_task` | Create task with notes, due date, parent task |
| `update_task` | Modify task |
| `complete_task` | Mark complete |
| `delete_task` | Remove task |
| `move_task_to_list` | Move between lists |
| `star_task` / `unstar_task` | Star/unstar tasks |
| `clear_completed_tasks` | Clear completed from list |

### Google Drive

| Tool | Description |
|------|-------------|
| `search_drive` | Search files by query (name, type, etc.) |
| `get_drive_file` | Get file metadata |
| `download_drive_file` | Download and return file content |

**Download supports**:
- Text files → returns text content
- PDFs → extracts and returns text (requires PyMuPDF)
- Google Docs → exports as plain text
- Google Sheets → exports as CSV
- Google Slides → exports as plain text
- Images → returns base64-encoded data

### Utility

| Tool | Description |
|------|-------------|
| `get_time` | Get current date/time for any IANA timezone |

## Local Development

```bash
# Clone the repository
git clone https://github.com/michaelzrork/google-connections-mcp.git
cd google-connections-mcp

# Install uv if you don't have it
pip install uv

# Install dependencies
uv sync

# Set environment variables
export GOOGLE_CREDENTIALS='{"web":{"client_id":"..."}}'
export GOOGLE_TOKEN_JSON='{"token":"...","refresh_token":"..."}'

# Run the server
python -m google_connections_mcp.server
```

The server runs on port 8000 by default (or `$PORT` if set).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_CREDENTIALS` | Yes | OAuth client configuration JSON from Google Cloud Console |
| `GOOGLE_TOKEN_JSON` | Yes* | User authorization token (obtained via `/oauth/start` flow) |
| `PORT` | No | Server port (default: 8000) |

*Not required for initial deploy - you'll add this after authorizing.

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `/sse` | MCP SSE connection endpoint (what Claude connects to) |
| `/messages/` | MCP message handling |
| `/oauth/start` | Begin OAuth authorization flow |
| `/oauth/callback` | OAuth callback handler |
| `/health` | Health check (returns auth status) |

## Troubleshooting

### "Token expired" or constant reauthorization
Make sure you've published your OAuth app to Production in Google Cloud Console. Testing mode tokens expire every 7 days.

### Can't connect from Claude
- Check that your Railway deployment is running (`/health` endpoint should return `{"status": "ok"}`)
- Verify the URL is correct (should end in `/sse`)
- Check Railway logs for errors

### OAuth callback fails
- Make sure your redirect URI in Google Cloud Console exactly matches your Railway URL
- The URL should be `https://` (not `http://`)
- Include the full path: `https://your-app.up.railway.app/oauth/callback`

### PDF text extraction not working
PyMuPDF should be included in dependencies. Check that your deployment includes it. PDFs will fall back to base64 if text extraction fails.

## Architecture

This server uses:
- [FastMCP](https://github.com/jlowin/fastmcp) for MCP protocol handling
- [gspread](https://github.com/burnash/gspread) for Google Sheets
- [google-api-python-client](https://github.com/googleapis/google-api-python-client) for other Google APIs
- [PyMuPDF](https://pymupdf.readthedocs.io/) for PDF text extraction
- [Starlette](https://www.starlette.io/) for HTTP/SSE transport
- [uv](https://github.com/astral-sh/uv) for fast dependency management

## Known Limitations

- **Images from Drive**: Returned as base64. AI assistants need to decode and save locally to view.
- **Large files**: Very large files may timeout. Consider using `get_drive_file` for metadata and accessing via `webViewLink` instead.
- **Google Workspace files**: Docs/Sheets/Slides are exported to text/CSV, not native format.

## License

MIT

## Contributing

Issues and pull requests welcome!

## Author

[Michael Z Rork](https://github.com/michaelzrork)