# Google Connections MCP

A Model Context Protocol (MCP) server that provides AI assistants with access to Google Workspace APIs. Deploy once on Railway (or any hosting platform), connect from Claude or any MCP-compatible client.

## Features

- **Google Sheets** - Full spreadsheet control with flexible row/column addressing (by header name or column letter), cell-level operations, and worksheet management
- **Google Calendar** - List, create, update, and delete events across all your calendars
- **Gmail** - Read, send, search, label, archive, and manage messages
- **Google Tasks** - Full task and task list management
- **Google Drive** - Search, list folders, create/move/rename/delete/share/copy files, download content
- **Google Docs** - Create documents, read/edit content, formatting (bold, italic, fonts, headings, bullets, margins)
- **Search Console** - Search performance (queries, pages, clicks, impressions, position), URL index status, sitemaps (read only)
- **Google Analytics (GA4)** - Reports, realtime activity, property list (read only)
- **Time** - Get current date/time in any IANA timezone

## How It Works

1. You deploy this server to Railway (or similar) with a small volume for its tokens
2. You set up OAuth credentials in Google Cloud Console
3. You add the connector in your AI app with the `/mcp` address
4. The app sends you to Google's sign-in. Sign in as the owner account and approve: that one step grants the Google permissions AND connects the app. Any other Google account is turned away.

The MCP endpoint (`/mcp`, Streamable HTTP) needs a sign-in for every request. Behind it is an OAuth 2.1 authorization server (discovery, dynamic client registration, PKCE, rotating refresh tokens, revocation) whose login is Google, built on the MCP SDK's auth support.

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
   - Google Search Console API
   - Google Analytics Data API
   - Google Analytics Admin API (only for `analytics_list_properties`)

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
     - `https://www.googleapis.com/auth/webmasters.readonly`
     - `https://www.googleapis.com/auth/analytics.readonly`
   - Google may say some scopes need verification. For an app only you use, skip it: you'll see "Google hasn't verified this app" when you authorize; choose **Advanced → Go to (app name)**. Unverified apps are limited to 100 users.
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

7. Add a volume (the service → Settings → Volumes → Add, mount path `/data`). Tokens are kept there; without it every deploy signs your AI app out.

8. Add environment variables in Railway (Settings → Variables):
   ```
   GOOGLE_CREDENTIALS = (paste the entire contents of your downloaded OAuth JSON file)
   OWNER_EMAIL        = you@gmail.com   (the only Google account allowed to sign in)
   DATA_DIR           = /data           (the volume's mount path)
   ```
   The public address is read from Railway's `RAILWAY_PUBLIC_DOMAIN`; set `PUBLIC_URL` if you use a custom domain.

9. Trigger a redeploy after adding the variables

### 3. Connect your AI app

**Claude:** Settings → Connectors → Add custom connector, URL `https://your-railway-url/mcp`. Claude opens Google's sign-in: sign in as `OWNER_EMAIL` and approve. (Unverified app? Choose **Advanced → Go to (app name)**.)

**ChatGPT** (website): Settings → Apps & Connectors → add a custom MCP server with the same URL, Authentication **OAuth**.

To grant new Google permissions later (after a scope is added to `oauth_config.py`), reconnect the connector: the sign-in asks for them.

You're done!

### Moving from the old `/sse` setup

Older installs connected to `/sse` with no sign-in, using a `GOOGLE_TOKEN_JSON` copied from the logs. Both keep working until an AI app first connects through `/mcp`; after that `/sse`, `/messages` and `/oauth/start` answer **410 Gone** for good, because `/sse` lets anyone with the URL use your Google account. Steps: add the volume and `OWNER_EMAIL`/`DATA_DIR`, deploy, then replace the connector's URL with `/mcp` and sign in. `GOOGLE_TOKEN_JSON` can be deleted once that works (the sign-in saves its own token). `LEGACY_SSE=on` or `off` overrides the automatic switch.

## Available Tools

Every tool is named for its service (`gmail_`, `calendar_`, `drive_`, `docs_`, `sheets_`, `tasks_`, `search_console_`, `analytics_`) and carries a title like "Gmail: Send Message". Tools that only read are marked read-only, so MCP clients can list them separately from tools that change things. `get_time` keeps its plain name.

### Google Sheets

All Sheets tools support a `mode` parameter: `"header"` (default) uses column header names, `"letter"` uses column letters (A, B, C...).

| Tool | Description |
|------|-------------|
| `sheets_query` | Query with filters, sorting, column selection. Supports date comparisons. |
| `sheets_get_row` | Get complete row(s) by row number or unique ID lookup |
| `sheets_get_cell` | Get cell value(s) by A1 notation (e.g., "A1", "B5") |
| `sheets_get_column` | Get all values in a column with row numbers (for easy update_cells follow-up) |
| `sheets_find_row` | Find row number(s) by searching a column for a value |
| `sheets_update_row` | Update specific cells in existing row(s) by row number or unique ID |
| `sheets_update_cells` | Update cell(s) directly by A1 notation - the core write primitive |
| `sheets_add_row` | Append new row(s) to the end of the sheet |
| `sheets_insert_row` | Insert row at specific position (shifts existing rows down) |
| `sheets_delete_row` | Delete row(s) by row number or unique ID lookup |
| `sheets_insert_column` | Insert column at position (shifts right) or append to first empty if no position given |
| `sheets_delete_column` | Delete a column by header name or letter |
| `sheets_create_spreadsheet` | Create a new Google Sheets document with optional worksheets |
| `sheets_add_worksheet` | Add a new worksheet (tab) to an existing spreadsheet |
| `sheets_delete_worksheet` | Delete a worksheet from a spreadsheet |
| `sheets_list_worksheets` | List all worksheets in a spreadsheet with their properties |
| `sheets_rename_worksheet` | Rename a worksheet |
| `sheets_get_spreadsheet_info` | Get spreadsheet metadata (title, URL, all worksheets) |
| `sheets_clear_range` | Clear cell contents in a range without deleting rows/columns |
| `sheets_sort_worksheet` | Sort entire worksheet by a column |
| `sheets_copy_worksheet` | Copy a worksheet to the same or a different spreadsheet |
| `sheets_merge_cells` | Merge a range of cells into one |
| `sheets_unmerge_cells` | Unmerge previously merged cells |
| `sheets_freeze_rows_columns` | Freeze rows and/or columns (headers stay visible while scrolling) |

**Query Operators**: `==`, `!=`, `>`, `<`, `>=`, `<=`, `in`, `not in`, `contains`, `not contains`, `is_null`, `not_null`

**Date Handling**: Date columns are automatically parsed and compared correctly. Use `==` with full date strings (e.g., `1/27/2026` or `2026-01-27`) for exact matching. Avoid `contains` for dates as it does substring matching.

**Row Identification**: Tools that modify rows accept either `{"row": 6}` for direct row numbers, or `{"unique_id_column": "ID", "unique_id_value": "abc123"}` for lookup-based identification.

### Google Calendar

| Tool | Description |
|------|-------------|
| `calendar_list_calendars` | List all calendars |
| `calendar_list_events` | List events with time range and search |
| `calendar_get_event` | Get specific event details |
| `calendar_create_event` | Create new event with optional attendees/reminders/timezone |
| `calendar_update_event` | Modify existing event |
| `calendar_delete_event` | Remove event |

**Timezone**: `calendar_create_event` and `calendar_update_event` accept an optional `timezone` parameter (IANA format, e.g., `'America/New_York'`, `'Europe/London'`, `'UTC'`). If omitted, uses the calendar's default timezone.

### Gmail

| Tool | Description |
|------|-------------|
| `gmail_list_messages` | Search/list messages with Gmail query syntax |
| `gmail_get_message` | Get full message content |
| `gmail_send_message` | Send email (with CC/BCC support) |
| `gmail_modify_message` | Add/remove labels |
| `gmail_batch_modify` | Bulk label operations |
| `gmail_mark_read` / `gmail_mark_unread` | Mark messages as read/unread |
| `gmail_star` / `gmail_unstar` | Star/unstar messages |
| `gmail_archive` | Archive messages |
| `gmail_move_to_inbox` | Move messages back to inbox |
| `gmail_trash` | Move to trash |
| `gmail_mark_spam` | Mark as spam |
| `gmail_list_labels` | List all labels |
| `gmail_create_label` | Create new label |

### Google Tasks

| Tool | Description |
|------|-------------|
| `tasks_list_task_lists` | List all task lists |
| `tasks_create_task_list` / `tasks_delete_task_list` / `tasks_update_task_list` | Manage task lists |
| `tasks_list_tasks` | List tasks (with completed/hidden options) |
| `tasks_get_task` | Get task details |
| `tasks_create_task` | Create task with notes, due date, parent task |
| `tasks_update_task` | Modify task |
| `tasks_complete_task` | Mark complete |
| `tasks_delete_task` | Remove task |
| `tasks_move_task_to_list` | Move between lists |
| `tasks_star_task` / `tasks_unstar_task` | Star/unstar tasks |
| `tasks_clear_completed` | Clear completed from list |

### Google Drive

| Tool | Description |
|------|-------------|
| `drive_search` | Search files by query (name, type, etc.) |
| `drive_get_file` | Get file metadata |
| `drive_download_file` | Download and return file content |
| `drive_list_folder` | List contents of a folder (simpler than search) |
| `drive_create_folder` | Create a new folder |
| `drive_move_file` | Move a file to a different folder |
| `drive_rename_file` | Rename a file or folder |
| `drive_delete_file` | Delete/trash a file or folder |
| `drive_share_file` | Share a file with another user |
| `drive_copy_file` | Create a copy of a file |

**Download supports**:
- Text files → returns text content
- PDFs → extracts and returns text (requires PyMuPDF)
- Google Docs → exports as plain text
- Google Sheets → exports as CSV
- Google Slides → exports as plain text
- Images → returns base64-encoded data

**File operations**:
- `drive_delete_file` moves to trash by default; use `permanent=True` to delete forever
- `drive_share_file` supports roles: `reader`, `commenter`, `writer`
- `drive_copy_file` cannot copy folders, only files

### Google Docs

| Tool | Description |
|------|-------------|
| `docs_create` | Create a new Google Doc with optional initial content and folder placement |
| `docs_get` | Get document content as plain text with structure info |
| `docs_append` | Append text to the end of a document |
| `docs_insert_text` | Insert text at a specific index position |
| `docs_replace_text` | Find and replace all occurrences of text |
| `docs_delete_content` | Delete a range of content by start/end index |
| `docs_delete_empty_lines` | Remove excessive empty lines/paragraphs (configurable threshold) |
| `docs_format_text` | Apply text formatting by index range (bold, italic, underline, font size, colors) |
| `docs_format_text_by_search` | Find text and apply formatting (easier - no indices needed) |
| `docs_format_paragraph` | Apply paragraph formatting: alignment, line spacing, space above/below, indentation |
| `docs_create_bullets` | Add bullet or numbered list formatting to paragraphs |
| `docs_remove_bullets` | Remove bullet/list formatting from paragraphs |
| `docs_set_heading` | Apply heading styles (Heading 1-6 or normal text) |
| `docs_set_margins` | Set page margins (top, bottom, left, right in inches) |
| `docs_get_structure` | Get detailed document structure with index positions for each element |
| `docs_insert_link` | Add a hyperlink to existing text (requires indices) |
| `docs_link_text` | Find text and make it a hyperlink (easier - no indices needed) |
| `docs_insert_image` | Insert an image from a URL |
| `docs_insert_table` | Create a table with specified rows and columns |
| `docs_insert_page_break` | Insert a page break |

**Index positions**: Google Docs uses 1-based indexing. Use `docs_get_structure` to see each paragraph with its start/end indices for precise formatting.

**Bullet presets**: `BULLET_DISC_CIRCLE_SQUARE` (default), `BULLET_CHECKBOX`, `NUMBERED_DECIMAL_ALPHA_ROMAN`, `NUMBERED_DECIMAL_NESTED`, and more.

### Search Console (read only)

| Tool | Description |
|------|-------------|
| `search_console_list_sites` | Properties this account can see, with permission level |
| `search_console_query` | Clicks, impressions, CTR and position by query, page, country, device or date, with filters |
| `search_console_inspect_url` | Google's index status for one URL: indexed or not, last crawl, chosen canonical |
| `search_console_list_sitemaps` | Submitted sitemaps with last download, warnings and errors |

### Google Analytics (GA4, read only)

| Tool | Description |
|------|-------------|
| `analytics_list_properties` | Accounts and properties with their numeric property IDs |
| `analytics_report` | Any metrics over a date range, split by dimensions (pages, sources, countries, events), with a filter and sort |
| `analytics_realtime` | Activity in the last 30 minutes |

**IDs**: a Search Console property is written as Search Console shows it: `sc-domain:example.com` (domain property) or `https://www.example.com/` (URL property). A GA4 property ID is the number in Admin → Property details, not the `G-XXXX` measurement ID.

**Adding these to an existing install**: enable the APIs and add the two scopes (step 1), deploy, then visit `/oauth/start` again and replace `GOOGLE_TOKEN_JSON` with the new token from the logs. Until then these tools say so, and every other tool keeps working on the old token.

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
| `OWNER_EMAIL` | Yes | The Google account allowed to sign in; everyone else is refused |
| `DATA_DIR` | Yes* | Where tokens are kept: a mounted volume, e.g. `/data` |
| `PUBLIC_URL` | No | This server's public address; defaults to `https://$RAILWAY_PUBLIC_DOMAIN` |
| `GOOGLE_TOKEN_JSON` | No | Old setup only: a token copied from the logs. Used when the sign-in hasn't saved one |
| `LEGACY_SSE` | No | `on` / `off` to force the old `/sse` endpoint; by default it closes after the first `/mcp` connection |
| `SEARCH_CONSOLE_SITE` | No | Default Search Console property for the Search Console tools |
| `GA4_PROPERTY_ID` | No | Default numeric GA4 property ID for the Analytics tools |
| `PORT` | No | Server port (default: 8000) |

*Without a volume the server still runs, but tokens are lost on every deploy and the AI app has to sign in again.

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `/mcp` | MCP endpoint (Streamable HTTP, sign-in required): what your AI app connects to |
| `/.well-known/oauth-protected-resource/mcp`, `/.well-known/oauth-authorization-server` | OAuth discovery |
| `/register`, `/authorize`, `/token`, `/revoke` | OAuth 2.1: client registration, sign-in, tokens, revocation |
| `/oauth/callback` | Google's redirect back after sign-in |
| `/health` | Status: Google signed in, the `/mcp` address, whether the old endpoints are open, whether storage is persistent |
| `/sse`, `/messages/`, `/oauth/start` | Old setup, open until the first `/mcp` connection, then 410 |

## Troubleshooting

### "Token expired" or constant reauthorization
Make sure you've published your OAuth app to Production in Google Cloud Console. Testing mode tokens expire every 7 days.

### Can't connect from Claude
- Check that your Railway deployment is running (`/health` endpoint should return `{"status": "ok"}`)
- Verify the URL ends in `/mcp`
- "This server belongs to someone else": you signed in with a Google account other than `OWNER_EMAIL`
- Signed out after every deploy: the volume isn't mounted, or `DATA_DIR` doesn't point at it (`/health` shows `storage_persistent`)
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
- [Starlette](https://www.starlette.io/) for HTTP transport
- The MCP SDK's OAuth support (`mcp.server.auth`) with Google as the login: `mcp_oauth.py`, tokens in `token_store.py`
- [uv](https://github.com/astral-sh/uv) for fast dependency management

## Known Limitations

- **Images from Drive**: Returned as base64. AI assistants need to decode and save locally to view.
- **Large files**: Very large files may timeout. Consider using `drive_get_file` for metadata and accessing via `webViewLink` instead.
- **Google Workspace files**: Docs/Sheets/Slides are exported to text/CSV, not native format.

## License

MIT

## Contributing

Issues and pull requests welcome!

## Author

[Michael Z Rork](https://github.com/michaelzrork)