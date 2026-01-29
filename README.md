# Google Connections MCP

A Model Context Protocol (MCP) server that provides AI assistants with access to Google Workspace APIs. Deploy once on Railway (or any hosting platform), connect from Claude or any MCP-compatible client.

## Features

- **Google Sheets** - Full spreadsheet control with flexible row/column addressing (by header name or column letter), cell-level operations, and worksheet management
- **Google Calendar** - List, create, update, and delete events across all your calendars
- **Gmail** - Read, send, search, label, archive, and manage messages
- **Google Tasks** - Full task and task list management
- **Google Drive** - Search, list folders, create/move/rename/delete/share/copy files, download content
- **Google Docs** - Create documents, read/edit content, formatting (bold, italic, fonts, headings, bullets, margins)
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
5. **Important: Format the token correctly** (see below)
6. Add it as environment variable: `GOOGLE_TOKEN_JSON`
7. Redeploy one more time

#### Formatting the Token JSON

Railway logs wrap the token in extra metadata. You need to extract just the token data.

**What Railway logs show:**
```json
{
  "message": "",
  "attributes": {
    "token": "ya29.a0ARrdaM...",
    "refresh_token": "1//0eXy...",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "12345...apps.googleusercontent.com",
    "client_secret": "GOCSPX-...",
    "scopes": ["https://www.googleapis.com/auth/calendar", ...],
    "expiry": "2025-12-15T12:00:00Z"
  },
  "tags": { ... },
  "timestamp": "2025-12-15T..."
}
```

**What you need to paste (extract from `attributes`):**
```json
{"token": "ya29.a0ARrdaM...", "refresh_token": "1//0eXy...", "token_uri": "https://oauth2.googleapis.com/token", "client_id": "12345...apps.googleusercontent.com", "client_secret": "GOCSPX-...", "scopes": ["https://www.googleapis.com/auth/calendar", ...], "expiry": "2025-12-15T12:00:00Z"}
```

**Quick method:** Copy the Railway log output, paste it to Claude or ChatGPT, and ask: "Extract just the token JSON from this Railway log output and format it on one line."


### 4. Connect to Claude

1. In Claude.ai, go to Settings → Connections
2. Add a new MCP connection:
   - URL: `https://your-railway-url/sse`
3. The connection should show as active

You're done! Claude can now access your Google services.

## Available Tools

### Google Sheets

All Sheets tools support a `mode` parameter: `"header"` (default) uses column header names, `"letter"` uses column letters (A, B, C...).

| Tool | Description |
|------|-------------|
| `query_sheet` | Query with filters, sorting, column selection. Supports date comparisons. |
| `get_row` | Get complete row(s) by row number or unique ID lookup |
| `get_cell` | Get cell value(s) by A1 notation (e.g., "A1", "B5") |
| `get_column` | Get all values in a column with row numbers (for easy update_cells follow-up) |
| `find_row_by_unique_id` | Find row number(s) by searching a column for a value |
| `update_row` | Update specific cells in existing row(s) by row number or unique ID |
| `update_cells` | Update cell(s) directly by A1 notation - the core write primitive |
| `add_row` | Append new row(s) to the sheet |
| `delete_row` | Delete row(s) by row number or unique ID lookup |
| `add_column` | Add a new column with a header (auto-detects next empty column) |
| `delete_column` | Delete a column by header name or letter |
| `create_spreadsheet` | Create a new Google Sheets document with optional worksheets |
| `add_worksheet` | Add a new worksheet (tab) to an existing spreadsheet |
| `delete_worksheet` | Delete a worksheet from a spreadsheet |
| `list_worksheets` | List all worksheets in a spreadsheet with their properties |
| `rename_worksheet` | Rename a worksheet |
| `get_spreadsheet_info` | Get spreadsheet metadata (title, URL, all worksheets) |
| `clear_range` | Clear cell contents in a range without deleting rows/columns |
| `sort_worksheet` | Sort entire worksheet by a column |
| `copy_worksheet` | Copy a worksheet to the same or a different spreadsheet |
| `merge_cells` | Merge a range of cells into one |
| `unmerge_cells` | Unmerge previously merged cells |
| `freeze_rows_columns` | Freeze rows and/or columns (headers stay visible while scrolling) |

**Query Operators**: `==`, `!=`, `>`, `<`, `>=`, `<=`, `in`, `not in`, `contains`, `not contains`, `is_null`, `not_null`

**Date Handling**: Date columns are automatically parsed and compared correctly. Use `==` with full date strings (e.g., `1/27/2026` or `2026-01-27`) for exact matching. Avoid `contains` for dates as it does substring matching.

**Row Identification**: Tools that modify rows accept either `{"row": 6}` for direct row numbers, or `{"unique_id_column": "ID", "unique_id_value": "abc123"}` for lookup-based identification.

### Google Calendar

| Tool | Description |
|------|-------------|
| `list_calendars` | List all calendars |
| `list_calendar_events` | List events with time range and search |
| `get_calendar_event` | Get specific event details |
| `create_calendar_event` | Create new event with optional attendees/reminders/timezone |
| `update_calendar_event` | Modify existing event |
| `delete_calendar_event` | Remove event |

**Timezone**: `create_calendar_event` and `update_calendar_event` accept an optional `timezone` parameter (IANA format, e.g., `'America/New_York'`, `'Europe/London'`, `'UTC'`). If omitted, uses the calendar's default timezone.

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
| `list_folder` | List contents of a folder (simpler than search) |
| `create_folder` | Create a new folder |
| `move_file` | Move a file to a different folder |
| `rename_file` | Rename a file or folder |
| `delete_file` | Delete/trash a file or folder |
| `share_file` | Share a file with another user |
| `copy_file` | Create a copy of a file |

**Download supports**:
- Text files → returns text content
- PDFs → extracts and returns text (requires PyMuPDF)
- Google Docs → exports as plain text
- Google Sheets → exports as CSV
- Google Slides → exports as plain text
- Images → returns base64-encoded data

**File operations**:
- `delete_file` moves to trash by default; use `permanent=True` to delete forever
- `share_file` supports roles: `reader`, `commenter`, `writer`
- `copy_file` cannot copy folders, only files

### Google Docs

| Tool | Description |
|------|-------------|
| `create_doc` | Create a new Google Doc with optional initial content and folder placement |
| `get_doc` | Get document content as plain text with structure info |
| `append_to_doc` | Append text to the end of a document |
| `insert_text` | Insert text at a specific index position |
| `replace_text` | Find and replace all occurrences of text |
| `delete_doc_content` | Delete a range of content by start/end index |
| `delete_empty_lines` | Remove excessive empty lines/paragraphs (configurable threshold) |
| `format_text` | Apply text formatting by index range (bold, italic, underline, font size, colors) |
| `format_text_by_search` | Find text and apply formatting (easier - no indices needed) |
| `format_paragraph` | Apply paragraph formatting: alignment, line spacing, space above/below, indentation |
| `create_bullets` | Add bullet or numbered list formatting to paragraphs |
| `remove_bullets` | Remove bullet/list formatting from paragraphs |
| `set_heading` | Apply heading styles (Heading 1-6 or normal text) |
| `set_document_margins` | Set page margins (top, bottom, left, right in inches) |
| `get_doc_structure` | Get detailed document structure with index positions for each element |
| `insert_link` | Add a hyperlink to existing text (requires indices) |
| `link_text` | Find text and make it a hyperlink (easier - no indices needed) |
| `insert_image` | Insert an image from a URL |
| `insert_table` | Create a table with specified rows and columns |
| `insert_page_break` | Insert a page break |

**Index positions**: Google Docs uses 1-based indexing. Use `get_doc_structure` to see each paragraph with its start/end indices for precise formatting.

**Bullet presets**: `BULLET_DISC_CIRCLE_SQUARE` (default), `BULLET_CHECKBOX`, `NUMBERED_DECIMAL_ALPHA_ROMAN`, `NUMBERED_DECIMAL_NESTED`, and more.

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