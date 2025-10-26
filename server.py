#!/usr/bin/env python3
"""
Remote MCP Server for Google Sheets and Calendar Management
Full read/write access to Google Sheets with accomplishment tracking and Calendar management
"""

import os
import json
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials as GoogleCredentials

# Initialize MCP server
mcp = FastMCP("google_sheets_mcp")

# Google Sheets setup
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SHEET_NAME = "Accomplishments"

# Initialize Google Sheets client
def get_sheets_client():
    """Initialize Google Sheets client with service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# Initialize Google Calendar client
def get_calendar_service():
    """Initialize Google Calendar service with service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/calendar']
    
    creds = GoogleCredentials.from_service_account_info(creds_dict, scopes=scopes)
    service = build('calendar', 'v3', credentials=creds)
    return service

# Initialize Google Tasks client
def get_tasks_service():
    """Initialize Google Tasks service with service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/tasks']
    
    creds = GoogleCredentials.from_service_account_info(creds_dict, scopes=scopes)
    service = build('tasks', 'v1', credentials=creds)
    return service

# Initialize Google Drive client
def get_drive_service():
    """Initialize Google Drive service with service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    
    creds = GoogleCredentials.from_service_account_info(creds_dict, scopes=scopes)
    service = build('drive', 'v3', credentials=creds)
    return service

# Initialize Google Docs client
def get_docs_service():
    """Initialize Google Docs service with service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/documents.readonly']
    
    creds = GoogleCredentials.from_service_account_info(creds_dict, scopes=scopes)
    service = build('docs', 'v1', credentials=creds)
    return service

# Initialize Google Slides client
def get_slides_service():
    """Initialize Google Slides service with service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/presentations.readonly']
    
    creds = GoogleCredentials.from_service_account_info(creds_dict, scopes=scopes)
    service = build('slides', 'v1', credentials=creds)
    return service

# Initialize Gmail client
def get_gmail_service():
    """Initialize Gmail service with service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/gmail.readonly']
    
    creds = GoogleCredentials.from_service_account_info(creds_dict, scopes=scopes)
    service = build('gmail', 'v1', credentials=creds)
    return service

# Initialize Google Keep client (via Keep API)
def get_keep_service():
    """Initialize Google Keep service with service account credentials."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/keep.readonly']
    
    creds = GoogleCredentials.from_service_account_info(creds_dict, scopes=scopes)
    service = build('keep', 'v1', credentials=creds)
    return service

# ============================================================================
# ACCOMPLISHMENT-SPECIFIC TOOLS
# ============================================================================

class AddAccomplishmentInput(BaseModel):
    """Input for adding an accomplishment."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    description: str = Field(..., min_length=1, max_length=500)
    category: Optional[str] = Field(default=None, max_length=50)
    tags: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=500)
    date_override: Optional[str] = Field(default=None)

class ViewAccomplishmentsInput(BaseModel):
    """Input for viewing accomplishments."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    limit: Optional[int] = Field(default=50, ge=1, le=500)

class GetStatsInput(BaseModel):
    """Input for getting statistics."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    days: Optional[int] = Field(default=7, ge=1, le=365)

class EditAccomplishmentInput(BaseModel):
    """Input for editing an accomplishment."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    accomplishment_id: str = Field(..., min_length=1)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    category: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=500)

@mcp.tool(name="add_accomplishment")
async def add_accomplishment(params: AddAccomplishmentInput) -> str:
    """Add a new accomplishment to Google Sheets."""
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        accomplishment_id = str(uuid4())
        accomplishment_date = params.date_override or date.today().isoformat()
        current_time = datetime.now().strftime("%H:%M")
        
        sheet.append_row([
            accomplishment_date,
            current_time,
            params.category or "",
            params.description,
            params.notes or "",
            accomplishment_id
        ])
        
        return json.dumps({
            "success": True,
            "message": "Accomplishment added successfully",
            "id": accomplishment_id,
            "date": accomplishment_date,
            "description": params.description
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="view_accomplishments")
async def view_accomplishments(params: ViewAccomplishmentsInput) -> str:
    """View accomplishments with optional filtering."""
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        records = sheet.get_all_records()
        
        filtered = records
        if params.start_date:
            filtered = [r for r in filtered if r.get('Date', '') >= params.start_date]
        if params.end_date:
            filtered = [r for r in filtered if r.get('Date', '') <= params.end_date]
        if params.category:
            filtered = [r for r in filtered if r.get('Category', '') == params.category]
        
        filtered = sorted(filtered, key=lambda x: x.get('Date', ''), reverse=True)
        filtered = filtered[:params.limit]
        
        if not filtered:
            return "No accomplishments found matching your criteria."
        
        lines = [f"# Your Accomplishments ({len(filtered)} total)\n"]
        for acc in filtered:
            date_str = acc.get('Date', '')
            cat_str = f" [{acc.get('Category', '')}]" if acc.get('Category') else ""
            lines.append(f"**{date_str}** - {acc.get('Accomplishment', '')}{cat_str}")
            if acc.get('Notes'):
                lines.append(f"  *{acc.get('Notes', '')}*")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="get_accomplishment_stats")
async def get_accomplishment_stats(params: GetStatsInput) -> str:
    """Get statistics about accomplishments."""
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        records = sheet.get_all_records()
        
        end_date = date.today()
        start_date = end_date - timedelta(days=params.days - 1)
        
        filtered = [
            r for r in records
            if start_date.isoformat() <= r.get('Date', '') <= end_date.isoformat()
        ]
        
        total = len(filtered)
        categories = {}
        for r in filtered:
            cat = r.get('Category', 'Uncategorized')
            categories[cat] = categories.get(cat, 0) + 1
        
        lines = [
            f"# Accomplishment Statistics",
            f"\n**Period:** Last {params.days} days",
            f"**Total accomplishments:** {total}",
            f"\n## By Category:"
        ]
        
        for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total * 100) if total > 0 else 0
            lines.append(f"- **{cat}:** {count} ({pct:.1f}%)")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="delete_accomplishment")
async def delete_accomplishment(accomplishment_id: str) -> str:
    """Delete an accomplishment by ID."""
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        cell = sheet.find(accomplishment_id)
        if not cell:
            return json.dumps({"success": False, "error": "Accomplishment not found"}, indent=2)
        
        sheet.delete_rows(cell.row)
        
        return json.dumps({
            "success": True,
            "message": f"Accomplishment deleted successfully"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="edit_accomplishment")
async def edit_accomplishment(params: EditAccomplishmentInput) -> str:
    """Edit an existing accomplishment."""
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        cell = sheet.find(params.accomplishment_id)
        if not cell:
            return json.dumps({"success": False, "error": "Accomplishment not found"}, indent=2)
        
        row_num = cell.row
        
        if params.category is not None:
            sheet.update_cell(row_num, 3, params.category)
        if params.description is not None:
            sheet.update_cell(row_num, 4, params.description)
        if params.notes is not None:
            sheet.update_cell(row_num, 5, params.notes)
        
        return json.dumps({
            "success": True,
            "message": "Accomplishment updated successfully"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GENERAL GOOGLE SHEETS TOOLS
# ============================================================================

@mcp.tool(name="list_spreadsheets")
async def list_spreadsheets() -> str:
    """List all spreadsheets accessible to the service account."""
    try:
        client = get_sheets_client()
        spreadsheets = client.openall()
        
        if not spreadsheets:
            return "No spreadsheets found."
        
        lines = [f"# Your Spreadsheets ({len(spreadsheets)} total)\n"]
        for sheet in spreadsheets:
            lines.append(f"**{sheet.title}**")
            lines.append(f"  ID: `{sheet.id}`")
            lines.append(f"  URL: {sheet.url}\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="list_worksheets")
async def list_worksheets(spreadsheet_id: str) -> str:
    """List all worksheets (tabs) in a spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheets = spreadsheet.worksheets()
        
        if not worksheets:
            return "No worksheets found."
        
        lines = [f"# Worksheets in {spreadsheet.title} ({len(worksheets)} total)\n"]
        for ws in worksheets:
            lines.append(f"**{ws.title}**")
            lines.append(f"  Index: {ws.index}")
            lines.append(f"  Rows: {ws.row_count}, Columns: {ws.col_count}\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class ReadSheetInput(BaseModel):
    """Input for reading a sheet."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: Optional[str] = Field(default=None)

@mcp.tool(name="read_sheet")
async def read_sheet(params: ReadSheetInput) -> str:
    """Read data from a specific worksheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        if params.range:
            values = worksheet.get(params.range)
        else:
            values = worksheet.get_all_values()
        
        return json.dumps({
            "success": True,
            "worksheet": params.worksheet_name,
            "data": values
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class WriteSheetInput(BaseModel):
    """Input for writing to a sheet."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: str = Field(..., min_length=1)
    values: List[List[Any]] = Field(..., min_items=1)

@mcp.tool(name="write_to_sheet")
async def write_to_sheet(params: WriteSheetInput) -> str:
    """Write data to specific cells/ranges in a worksheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        worksheet.update(params.range, params.values)
        
        return json.dumps({
            "success": True,
            "message": f"Successfully wrote {len(params.values)} rows to {params.range}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class AppendRowsInput(BaseModel):
    """Input for appending rows."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    values: List[List[Any]] = Field(..., min_items=1)

@mcp.tool(name="append_rows")
async def append_rows(params: AppendRowsInput) -> str:
    """Append multiple rows to the end of a worksheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        for row in params.values:
            worksheet.append_row(row)
        
        return json.dumps({
            "success": True,
            "message": f"Successfully appended {len(params.values)} rows"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="create_spreadsheet")
async def create_spreadsheet(title: str) -> str:
    """Create a new spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.create(title)
        
        return json.dumps({
            "success": True,
            "message": f"Created spreadsheet: {title}",
            "id": spreadsheet.id,
            "url": spreadsheet.url
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class CreateWorksheetInput(BaseModel):
    """Input for creating a worksheet."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    rows: int = Field(default=1000, ge=1)
    cols: int = Field(default=26, ge=1)

@mcp.tool(name="create_worksheet")
async def create_worksheet(params: CreateWorksheetInput) -> str:
    """Create a new worksheet (tab) in an existing spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        
        worksheet = spreadsheet.add_worksheet(
            title=params.title,
            rows=params.rows,
            cols=params.cols
        )
        
        return json.dumps({
            "success": True,
            "message": f"Created worksheet: {params.title}",
            "worksheet_id": worksheet.id
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class DeleteWorksheetInput(BaseModel):
    """Input for deleting a worksheet."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)

@mcp.tool(name="delete_worksheet")
async def delete_worksheet(params: DeleteWorksheetInput) -> str:
    """Delete a worksheet (tab) from a spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        spreadsheet.del_worksheet(worksheet)
        
        return json.dumps({
            "success": True,
            "message": f"Deleted worksheet: {params.worksheet_name}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class ClearRangeInput(BaseModel):
    """Input for clearing a range."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: str = Field(..., min_length=1)

@mcp.tool(name="clear_range")
async def clear_range(params: ClearRangeInput) -> str:
    """Clear data from a specific range in a worksheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        worksheet.batch_clear([params.range])
        
        return json.dumps({
            "success": True,
            "message": f"Cleared range: {params.range}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class CopyWorksheetInput(BaseModel):
    """Input for copying a worksheet."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    new_title: str = Field(..., min_length=1)

@mcp.tool(name="copy_worksheet")
async def copy_worksheet(params: CopyWorksheetInput) -> str:
    """Duplicate a worksheet within the same spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        new_worksheet = worksheet.duplicate(new_sheet_name=params.new_title)
        
        return json.dumps({
            "success": True,
            "message": f"Copied worksheet to: {params.new_title}",
            "worksheet_id": new_worksheet.id
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class FormatCellsInput(BaseModel):
    """Input for formatting cells."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: str = Field(..., min_length=1)
    bold: Optional[bool] = Field(default=None)
    italic: Optional[bool] = Field(default=None)
    background_color: Optional[Dict[str, float]] = Field(default=None)
    text_color: Optional[Dict[str, float]] = Field(default=None)

@mcp.tool(name="format_cells")
async def format_cells(params: FormatCellsInput) -> str:
    """Apply formatting to cells (bold, italic, colors)."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        format_dict = {}
        
        if params.bold is not None or params.italic is not None:
            text_format = {}
            if params.bold is not None:
                text_format['bold'] = params.bold
            if params.italic is not None:
                text_format['italic'] = params.italic
            format_dict['textFormat'] = text_format
        
        if params.background_color:
            format_dict['backgroundColor'] = params.background_color
        
        if params.text_color:
            if 'textFormat' not in format_dict:
                format_dict['textFormat'] = {}
            format_dict['textFormat']['foregroundColor'] = params.text_color
        
        worksheet.format(params.range, format_dict)
        
        return json.dumps({
            "success": True,
            "message": f"Applied formatting to range: {params.range}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class SearchSheetsInput(BaseModel):
    """Input for searching sheets."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    search_term: str = Field(..., min_length=1)
    worksheet_name: Optional[str] = Field(default=None)

@mcp.tool(name="search_sheets")
async def search_sheets(params: SearchSheetsInput) -> str:
    """Search for data across worksheets in a spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        
        if params.worksheet_name:
            worksheets = [spreadsheet.worksheet(params.worksheet_name)]
        else:
            worksheets = spreadsheet.worksheets()
        
        results = []
        for worksheet in worksheets:
            try:
                cells = worksheet.findall(params.search_term)
                for cell in cells:
                    results.append({
                        "worksheet": worksheet.title,
                        "cell": cell.address,
                        "value": cell.value,
                        "row": cell.row,
                        "col": cell.col
                    })
            except:
                continue
        
        if not results:
            return f"No matches found for '{params.search_term}'"
        
        lines = [f"# Search Results for '{params.search_term}' ({len(results)} matches)\n"]
        for result in results:
            lines.append(f"**{result['worksheet']}** - Cell {result['cell']}")
            lines.append(f"  Value: {result['value']}\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GOOGLE CALENDAR TOOLS
# ============================================================================

class CreateEventInput(BaseModel):
    """Input for creating a calendar event."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    calendar_id: str = Field(default="primary")
    summary: str = Field(..., min_length=1, max_length=200)
    start_datetime: str = Field(..., description="ISO format: 2025-10-27T10:00:00-04:00")
    end_datetime: str = Field(..., description="ISO format: 2025-10-27T11:00:00-04:00")
    description: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None)

@mcp.tool(name="create_calendar_event")
async def create_calendar_event(params: CreateEventInput) -> str:
    """Create a new calendar event."""
    try:
        service = get_calendar_service()
        
        event = {
            'summary': params.summary,
            'start': {
                'dateTime': params.start_datetime,
                'timeZone': 'America/New_York',
            },
            'end': {
                'dateTime': params.end_datetime,
                'timeZone': 'America/New_York',
            }
        }
        
        if params.description:
            event['description'] = params.description
        if params.location:
            event['location'] = params.location
        
        created_event = service.events().insert(
            calendarId=params.calendar_id,
            body=event
        ).execute()
        
        return json.dumps({
            "success": True,
            "message": "Event created successfully",
            "event_id": created_event['id'],
            "html_link": created_event.get('htmlLink'),
            "summary": created_event['summary']
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class UpdateEventInput(BaseModel):
    """Input for updating a calendar event."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    calendar_id: str = Field(default="primary")
    event_id: str = Field(..., min_length=1)
    summary: Optional[str] = Field(default=None, max_length=200)
    start_datetime: Optional[str] = Field(default=None)
    end_datetime: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None)

@mcp.tool(name="update_calendar_event")
async def update_calendar_event(params: UpdateEventInput) -> str:
    """Update an existing calendar event."""
    try:
        service = get_calendar_service()
        
        # Get existing event
        event = service.events().get(
            calendarId=params.calendar_id,
            eventId=params.event_id
        ).execute()
        
        # Update fields if provided
        if params.summary:
            event['summary'] = params.summary
        if params.description:
            event['description'] = params.description
        if params.location:
            event['location'] = params.location
        if params.start_datetime:
            event['start'] = {
                'dateTime': params.start_datetime,
                'timeZone': 'America/New_York'
            }
        if params.end_datetime:
            event['end'] = {
                'dateTime': params.end_datetime,
                'timeZone': 'America/New_York'
            }
        
        updated_event = service.events().update(
            calendarId=params.calendar_id,
            eventId=params.event_id,
            body=event
        ).execute()
        
        return json.dumps({
            "success": True,
            "message": "Event updated successfully",
            "event_id": updated_event['id'],
            "summary": updated_event['summary']
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class DeleteEventInput(BaseModel):
    """Input for deleting a calendar event."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    calendar_id: str = Field(default="primary")
    event_id: str = Field(..., min_length=1)

@mcp.tool(name="delete_calendar_event")
async def delete_calendar_event(params: DeleteEventInput) -> str:
    """Delete a calendar event."""
    try:
        service = get_calendar_service()
        
        service.events().delete(
            calendarId=params.calendar_id,
            eventId=params.event_id
        ).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Event deleted successfully"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="list_calendar_events")
async def list_calendar_events(
    calendar_id: str = "primary",
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 10
) -> str:
    """List calendar events within a time range."""
    try:
        service = get_calendar_service()
        
        # Default to today if no time range specified
        if not time_min:
            time_min = datetime.now().replace(hour=0, minute=0, second=0).isoformat() + '-04:00'
        if not time_max:
            time_max = (datetime.now() + timedelta(days=7)).isoformat() + '-04:00'
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return "No upcoming events found."
        
        lines = [f"# Upcoming Events ({len(events)} total)\n"]
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No title')
            lines.append(f"**{start}** - {summary}")
            if event.get('location'):
                lines.append(f"  📍 {event['location']}")
            if event.get('description'):
                lines.append(f"  ℹ️ {event['description'][:100]}...")
            lines.append(f"  🆔 Event ID: `{event['id']}`\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GOOGLE TASKS TOOLS
# ============================================================================

@mcp.tool(name="list_google_tasks")
async def list_google_tasks(tasklist: str = "@default") -> str:
    """List tasks from Google Tasks. Use this to find reminders the user set via Google Assistant."""
    try:
        service = get_tasks_service()
        
        # Get task lists
        results = service.tasklists().list().execute()
        lists = results.get('items', [])
        
        if not lists:
            return "No task lists found."
        
        # Find the specified list or use default
        target_list = None
        if tasklist == "@default":
            target_list = lists[0]['id']
        else:
            for tl in lists:
                if tl['title'].lower() == tasklist.lower():
                    target_list = tl['id']
                    break
            if not target_list:
                target_list = lists[0]['id']
        
        # Get tasks from the list
        tasks_result = service.tasks().list(tasklist=target_list).execute()
        tasks = tasks_result.get('items', [])
        
        if not tasks:
            return "No tasks found in this list."
        
        lines = [f"# Google Tasks ({len(tasks)} total)\n"]
        for task in tasks:
            status = "✅" if task.get('status') == 'completed' else "⬜"
            title = task.get('title', 'Untitled')
            lines.append(f"{status} **{title}**")
            if task.get('notes'):
                lines.append(f"  📝 {task['notes']}")
            if task.get('due'):
                lines.append(f"  📅 Due: {task['due']}")
            lines.append(f"  🆔 Task ID: `{task['id']}`\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="mark_google_task_complete")
async def mark_google_task_complete(task_id: str, tasklist: str = "@default") -> str:
    """Mark a Google Task as complete. Use after migrating to our Tasks sheet."""
    try:
        service = get_tasks_service()
        
        # Get task lists to find the right one
        results = service.tasklists().list().execute()
        lists = results.get('items', [])
        
        target_list = lists[0]['id'] if lists else None
        
        if not target_list:
            return json.dumps({"success": False, "error": "No task lists found"}, indent=2)
        
        # Update task status
        task = service.tasks().get(tasklist=target_list, task=task_id).execute()
        task['status'] = 'completed'
        
        service.tasks().update(
            tasklist=target_list,
            task=task_id,
            body=task
        ).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Task marked complete in Google Tasks"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GOOGLE DRIVE TOOLS
# ============================================================================

@mcp.tool(name="search_google_drive")
async def search_google_drive(query: str, max_results: int = 10) -> str:
    """Search for files in Google Drive. Use when user mentions 'that doc' or 'my file about X'."""
    try:
        service = get_drive_service()
        
        results = service.files().list(
            q=f"fullText contains '{query}' or name contains '{query}'",
            pageSize=max_results,
            fields="files(id, name, mimeType, webViewLink, modifiedTime)"
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            return f"No files found matching '{query}'"
        
        lines = [f"# Drive Search Results for '{query}' ({len(files)} files)\n"]
        for file in files:
            name = file['name']
            file_type = file['mimeType'].split('.')[-1]
            link = file.get('webViewLink', 'No link')
            modified = file.get('modifiedTime', '')
            
            lines.append(f"**{name}** ({file_type})")
            lines.append(f"  🔗 {link}")
            lines.append(f"  📅 Modified: {modified}")
            lines.append(f"  🆔 File ID: `{file['id']}`\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GOOGLE DOCS TOOLS
# ============================================================================

@mcp.tool(name="read_google_doc")
async def read_google_doc(document_id: str) -> str:
    """Read the contents of a Google Doc. Use the document ID from Drive search."""
    try:
        service = get_docs_service()
        
        doc = service.documents().get(documentId=document_id).execute()
        
        title = doc.get('title', 'Untitled')
        content = doc.get('body', {}).get('content', [])
        
        # Extract text from doc structure
        text_parts = []
        for element in content:
            if 'paragraph' in element:
                para_elements = element['paragraph'].get('elements', [])
                for pe in para_elements:
                    if 'textRun' in pe:
                        text_parts.append(pe['textRun'].get('content', ''))
        
        full_text = ''.join(text_parts)
        
        lines = [
            f"# {title}\n",
            full_text[:3000]  # Limit to first 3000 chars
        ]
        
        if len(full_text) > 3000:
            lines.append(f"\n\n... (truncated, {len(full_text)} total characters)")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GOOGLE SLIDES TOOLS
# ============================================================================

@mcp.tool(name="list_google_slides")
async def list_google_slides(max_results: int = 10) -> str:
    """List recent Google Slides presentations."""
    try:
        drive_service = get_drive_service()
        
        results = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.presentation'",
            pageSize=max_results,
            orderBy="modifiedTime desc",
            fields="files(id, name, webViewLink, modifiedTime)"
        ).execute()
        
        files = results.get('files', [])
        
        if not files:
            return "No presentations found."
        
        lines = [f"# Your Presentations ({len(files)} total)\n"]
        for file in files:
            lines.append(f"**{file['name']}**")
            lines.append(f"  🔗 {file.get('webViewLink', 'No link')}")
            lines.append(f"  📅 Modified: {file.get('modifiedTime', '')}")
            lines.append(f"  🆔 Presentation ID: `{file['id']}`\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="read_google_slides")
async def read_google_slides(presentation_id: str) -> str:
    """Read the contents of a Google Slides presentation."""
    try:
        service = get_slides_service()
        
        presentation = service.presentations().get(
            presentationId=presentation_id
        ).execute()
        
        title = presentation.get('title', 'Untitled')
        slides = presentation.get('slides', [])
        
        lines = [f"# {title}\n", f"**{len(slides)} slides total**\n"]
        
        for i, slide in enumerate(slides, 1):
            lines.append(f"## Slide {i}")
            
            # Extract text from slide elements
            page_elements = slide.get('pageElements', [])
            for element in page_elements:
                if 'shape' in element:
                    shape = element['shape']
                    if 'text' in shape:
                        text_content = shape['text'].get('textElements', [])
                        for text_el in text_content:
                            if 'textRun' in text_el:
                                content = text_el['textRun'].get('content', '').strip()
                                if content:
                                    lines.append(f"  {content}")
            lines.append("")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GMAIL TOOLS
# ============================================================================

@mcp.tool(name="search_gmail")
async def search_gmail(query: str, max_results: int = 10) -> str:
    """Search Gmail for specific emails. Use when user asks about emails."""
    try:
        service = get_gmail_service()
        
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()
        
        messages = results.get('messages', [])
        
        if not messages:
            return f"No emails found matching '{query}'"
        
        lines = [f"# Gmail Search Results for '{query}' ({len(messages)} emails)\n"]
        
        for msg in messages:
            # Get full message details
            message = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()
            
            headers = message.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No subject')
            from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
            
            # Check if unread
            labels = message.get('labelIds', [])
            unread = '🔴 UNREAD' if 'UNREAD' in labels else ''
            
            lines.append(f"**{subject}** {unread}")
            lines.append(f"  📧 From: {from_email}")
            lines.append(f"  📅 {date}")
            lines.append(f"  🆔 Message ID: `{msg['id']}`\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="get_unread_emails")
async def get_unread_emails(max_results: int = 20) -> str:
    """Get unread emails for quick triage. Perfect for morning inbox review."""
    try:
        service = get_gmail_service()
        
        results = service.users().messages().list(
            userId='me',
            q='is:unread',
            maxResults=max_results
        ).execute()
        
        messages = results.get('messages', [])
        
        if not messages:
            return "🎉 Inbox Zero! No unread emails."
        
        lines = [f"# 📬 Unread Emails ({len(messages)} total)\n"]
        
        urgent_keywords = ['urgent', 'asap', 'important', 'interview', 'offer', 'deadline', 'today']
        urgent_emails = []
        normal_emails = []
        
        for msg in messages:
            message = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()
            
            headers = message.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No subject')
            from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
            
            # Check for urgency
            is_urgent = any(keyword in subject.lower() for keyword in urgent_keywords)
            
            email_info = {
                'subject': subject,
                'from': from_email,
                'date': date,
                'id': msg['id']
            }
            
            if is_urgent:
                urgent_emails.append(email_info)
            else:
                normal_emails.append(email_info)
        
        # Show urgent first
        if urgent_emails:
            lines.append("## 🚨 URGENT - Need Attention\n")
            for email in urgent_emails:
                lines.append(f"**{email['subject']}**")
                lines.append(f"  📧 From: {email['from']}")
                lines.append(f"  📅 {email['date']}")
                lines.append(f"  🆔 `{email['id']}`\n")
        
        if normal_emails:
            lines.append(f"## 📮 Other Unread ({len(normal_emails)})\n")
            for email in normal_emails[:10]:  # Limit to first 10
                lines.append(f"**{email['subject']}**")
                lines.append(f"  📧 From: {email['from']}")
                lines.append(f"  🆔 `{email['id']}`\n")
            
            if len(normal_emails) > 10:
                lines.append(f"... and {len(normal_emails) - 10} more")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="read_gmail_message")
async def read_gmail_message(message_id: str) -> str:
    """Read the full contents of a Gmail message."""
    try:
        import base64
        service = get_gmail_service()
        
        message = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()
        
        headers = message.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No subject')
        from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
        date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
        
        # Get body
        parts = message.get('payload', {}).get('parts', [])
        body = ""
        
        if parts:
            for part in parts:
                if part.get('mimeType') == 'text/plain':
                    body_data = part.get('body', {}).get('data', '')
                    if body_data:
                        body = base64.urlsafe_b64decode(body_data).decode('utf-8')
                        break
        else:
            body_data = message.get('payload', {}).get('body', {}).get('data', '')
            if body_data:
                body = base64.urlsafe_b64decode(body_data).decode('utf-8')
        
        lines = [
            f"# {subject}\n",
            f"**From:** {from_email}",
            f"**Date:** {date}\n",
            "---\n",
            body[:2000]  # Limit to first 2000 chars
        ]
        
        if len(body) > 2000:
            lines.append(f"\n\n... (truncated, {len(body)} total characters)")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GOOGLE KEEP TOOLS
# ============================================================================

@mcp.tool(name="list_google_keep_notes")
async def list_google_keep_notes(max_results: int = 20) -> str:
    """List notes from Google Keep. Use to find quick notes, grocery lists, and ideas."""
    try:
        service = get_keep_service()
        
        notes = service.notes().list(pageSize=max_results).execute()
        items = notes.get('notes', [])
        
        if not items:
            return "No Keep notes found."
        
        lines = [f"# Your Keep Notes ({len(items)} total)\n"]
        
        for note in items:
            title = note.get('title', 'Untitled')
            text = note.get('textContent', '')[:100]  # First 100 chars
            is_list = 'listContent' in note
            
            list_emoji = "📝" if is_list else "💭"
            
            lines.append(f"{list_emoji} **{title}**")
            if text:
                lines.append(f"  {text}...")
            
            # Show list items if it's a list
            if is_list:
                list_items = note.get('listContent', {}).get('listItems', [])
                checked = sum(1 for item in list_items if item.get('checked'))
                total = len(list_items)
                lines.append(f"  ✅ {checked}/{total} items checked")
            
            lines.append(f"  🆔 Note ID: `{note['name']}`\n")
        
        return "\n".join(lines)
        
    except Exception as e:
        # Google Keep API might not be available for service accounts
        return json.dumps({
            "success": False, 
            "error": "Keep API not available for service accounts. You may need to use the Claude-native Google integrations instead."
        }, indent=2)

@mcp.tool(name="read_keep_note")
async def read_keep_note(note_id: str) -> str:
    """Read the full contents of a Keep note, including list items."""
    try:
        service = get_keep_service()
        
        note = service.notes().get(name=note_id).execute()
        
        title = note.get('title', 'Untitled')
        is_list = 'listContent' in note
        
        lines = [f"# {title}\n"]
        
        if is_list:
            lines.append("## List Items:\n")
            list_items = note.get('listContent', {}).get('listItems', [])
            
            unchecked = [item for item in list_items if not item.get('checked')]
            checked = [item for item in list_items if item.get('checked')]
            
            if unchecked:
                lines.append("### 📌 To Get:")
                for item in unchecked:
                    text = item.get('text', {}).get('text', 'No text')
                    lines.append(f"- [ ] {text}")
                lines.append("")
            
            if checked:
                lines.append("### ✅ Already Have:")
                for item in checked:
                    text = item.get('text', {}).get('text', 'No text')
                    lines.append(f"- [x] {text}")
        else:
            text = note.get('textContent', '')
            lines.append(text)
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": "Keep API not available for service accounts. You may need to use the Claude-native Google integrations instead."
        }, indent=2)

# ============================================================================
# SERVER STARTUP (DO NOT MODIFY - THIS IS THE WORKING VERSION)
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import Response
    
    port = int(os.environ.get("PORT", 8000))
    
    sse = SseServerTransport("/messages/")
    
    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1],
                mcp._mcp_server.create_initialization_options()
            )
        return Response()
    
    app = Starlette(
        routes=[
            Route("/", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages", app=sse.handle_post_message),
        ]
    )
    
    uvicorn.run(app, host="0.0.0.0", port=port)