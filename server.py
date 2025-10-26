#!/usr/bin/env python3
"""
Comprehensive Google Workspace MCP Server
Supports: Accomplishments, Google Sheets, and Google Calendar management
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Initialize FastMCP server
mcp = FastMCP("Google Workspace Manager")

# Google API scopes
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/calendar'
]

# Initialize Google clients
def get_credentials():
    """Get credentials from environment variable"""
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")
    
    creds_dict = json.loads(creds_json)
    return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

def get_sheets_client():
    """Get authenticated gspread client"""
    creds = get_credentials()
    return gspread.authorize(creds)

def get_calendar_service():
    """Get authenticated Google Calendar service"""
    creds = get_credentials()
    return build('calendar', 'v3', credentials=creds)

def get_spreadsheet():
    """Get the accomplishments spreadsheet"""
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    if not spreadsheet_id:
        raise ValueError("SPREADSHEET_ID environment variable not set")
    
    client = get_sheets_client()
    return client.open_by_key(spreadsheet_id)

# Pydantic models for validation
class AddAccomplishmentInput(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    category: Optional[str] = Field(None, max_length=50)
    tags: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=500)
    date_override: Optional[str] = None

class ViewAccomplishmentsInput(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None
    limit: Optional[int] = Field(50, ge=1, le=500)

class GetStatsInput(BaseModel):
    days: Optional[int] = Field(7, ge=1, le=365)

class EditAccomplishmentInput(BaseModel):
    accomplishment_id: str = Field(..., min_length=1)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    category: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None, max_length=500)

# Google Sheets Models
class ReadSheetInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: Optional[str] = None

class WriteSheetInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: str = Field(..., min_length=1)
    values: List[List[Any]] = Field(..., min_items=1)

class AppendRowsInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    values: List[List[Any]] = Field(..., min_items=1)

class CreateWorksheetInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    rows: int = Field(1000, ge=1)
    cols: int = Field(26, ge=1)

class DeleteWorksheetInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)

class ClearRangeInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: str = Field(..., min_length=1)

class CopyWorksheetInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    new_title: str = Field(..., min_length=1)

class FormatCellsInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: str = Field(..., min_length=1)
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    background_color: Optional[Dict[str, float]] = None
    text_color: Optional[Dict[str, float]] = None

class SearchSheetsInput(BaseModel):
    spreadsheet_id: str = Field(..., min_length=1)
    search_term: str = Field(..., min_length=1)
    worksheet_name: Optional[str] = None

# Google Calendar Models
class CreateEventInput(BaseModel):
    calendar_id: str = Field(default="primary")
    summary: str = Field(..., min_length=1, max_length=200)
    start_datetime: str = Field(..., description="ISO format: 2025-10-27T10:00:00-04:00")
    end_datetime: str = Field(..., description="ISO format: 2025-10-27T11:00:00-04:00")
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[List[str]] = None

class UpdateEventInput(BaseModel):
    calendar_id: str = Field(default="primary")
    event_id: str = Field(..., min_length=1)
    summary: Optional[str] = Field(None, max_length=200)
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None

class DeleteEventInput(BaseModel):
    calendar_id: str = Field(default="primary")
    event_id: str = Field(..., min_length=1)

# ============================================================================
# ACCOMPLISHMENT TOOLS
# ============================================================================

@mcp.tool()
def add_accomplishment(params: AddAccomplishmentInput) -> dict:
    """Add a new accomplishment to Google Sheets."""
    try:
        spreadsheet = get_spreadsheet()
        worksheet = spreadsheet.worksheet('Accomplishments')
        
        # Generate unique ID
        accomplishment_id = str(uuid.uuid4())
        
        # Use provided date or today
        date_str = params.date_override or datetime.now().strftime('%Y-%m-%d')
        
        # Prepare row data
        row = [
            accomplishment_id,
            date_str,
            params.description,
            params.category or '',
            params.tags or '',
            params.notes or ''
        ]
        
        # Append to sheet
        worksheet.append_row(row)
        
        return {
            "success": True,
            "message": "Accomplishment added successfully",
            "id": accomplishment_id,
            "date": date_str,
            "description": params.description
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def view_accomplishments(params: ViewAccomplishmentsInput) -> dict:
    """View accomplishments with optional filtering."""
    try:
        spreadsheet = get_spreadsheet()
        worksheet = spreadsheet.worksheet('Accomplishments')
        
        # Get all records
        records = worksheet.get_all_records()
        
        # Apply filters
        filtered = records
        if params.start_date:
            filtered = [r for r in filtered if r['Date'] >= params.start_date]
        if params.end_date:
            filtered = [r for r in filtered if r['Date'] <= params.end_date]
        if params.category:
            filtered = [r for r in filtered if r['Category'] == params.category]
        
        # Apply limit
        filtered = filtered[:params.limit]
        
        return {
            "success": True,
            "count": len(filtered),
            "accomplishments": filtered
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_accomplishment_stats(params: GetStatsInput) -> dict:
    """Get statistics about accomplishments."""
    try:
        spreadsheet = get_spreadsheet()
        worksheet = spreadsheet.worksheet('Accomplishments')
        
        records = worksheet.get_all_records()
        
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=params.days)
        start_str = start_date.strftime('%Y-%m-%d')
        
        # Filter by date range
        recent = [r for r in records if r['Date'] >= start_str]
        
        # Calculate stats
        categories = {}
        for record in recent:
            cat = record['Category'] or 'Uncategorized'
            categories[cat] = categories.get(cat, 0) + 1
        
        return {
            "success": True,
            "period_days": params.days,
            "total_accomplishments": len(recent),
            "by_category": categories,
            "avg_per_day": round(len(recent) / params.days, 2)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def delete_accomplishment(accomplishment_id: str) -> dict:
    """Delete an accomplishment by ID."""
    try:
        spreadsheet = get_spreadsheet()
        worksheet = spreadsheet.worksheet('Accomplishments')
        
        # Find the row
        cell = worksheet.find(accomplishment_id)
        if not cell:
            return {"success": False, "error": "Accomplishment not found"}
        
        worksheet.delete_rows(cell.row)
        
        return {
            "success": True,
            "message": f"Deleted accomplishment {accomplishment_id}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def edit_accomplishment(params: EditAccomplishmentInput) -> dict:
    """Edit an existing accomplishment."""
    try:
        spreadsheet = get_spreadsheet()
        worksheet = spreadsheet.worksheet('Accomplishments')
        
        # Find the row
        cell = worksheet.find(params.accomplishment_id)
        if not cell:
            return {"success": False, "error": "Accomplishment not found"}
        
        row_num = cell.row
        
        # Update fields if provided
        if params.description:
            worksheet.update_cell(row_num, 3, params.description)
        if params.category:
            worksheet.update_cell(row_num, 4, params.category)
        if params.notes:
            worksheet.update_cell(row_num, 6, params.notes)
        
        return {
            "success": True,
            "message": "Accomplishment updated successfully"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# GOOGLE SHEETS TOOLS
# ============================================================================

@mcp.tool()
def list_spreadsheets() -> dict:
    """List all spreadsheets accessible to the service account."""
    try:
        client = get_sheets_client()
        spreadsheets = client.openall()
        
        result = []
        for sheet in spreadsheets:
            result.append({
                "id": sheet.id,
                "title": sheet.title,
                "url": sheet.url
            })
        
        return {
            "success": True,
            "count": len(result),
            "spreadsheets": result
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def list_worksheets(spreadsheet_id: str) -> dict:
    """List all worksheets (tabs) in a spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheets = spreadsheet.worksheets()
        
        result = []
        for ws in worksheets:
            result.append({
                "id": ws.id,
                "title": ws.title,
                "index": ws.index,
                "rows": ws.row_count,
                "cols": ws.col_count
            })
        
        return {
            "success": True,
            "count": len(result),
            "worksheets": result
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def read_sheet(params: ReadSheetInput) -> dict:
    """Read data from a specific worksheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        if params.range:
            data = worksheet.get(params.range)
        else:
            data = worksheet.get_all_values()
        
        return {
            "success": True,
            "worksheet": params.worksheet_name,
            "data": data
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def write_to_sheet(params: WriteSheetInput) -> dict:
    """Write data to specific cells/ranges in a worksheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        worksheet.update(params.range, params.values)
        
        return {
            "success": True,
            "message": f"Successfully wrote {len(params.values)} rows to {params.range}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def append_rows(params: AppendRowsInput) -> dict:
    """Append multiple rows to the end of a worksheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        worksheet.append_rows(params.values)
        
        return {
            "success": True,
            "message": f"Successfully appended {len(params.values)} rows"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def create_spreadsheet(title: str) -> dict:
    """Create a new spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.create(title)
        
        return {
            "success": True,
            "id": spreadsheet.id,
            "title": spreadsheet.title,
            "url": spreadsheet.url
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def create_worksheet(params: CreateWorksheetInput) -> dict:
    """Create a new worksheet (tab) in an existing spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        
        worksheet = spreadsheet.add_worksheet(
            title=params.title,
            rows=params.rows,
            cols=params.cols
        )
        
        return {
            "success": True,
            "message": f"Created worksheet: {params.title}",
            "worksheet_id": worksheet.id
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def delete_worksheet(params: DeleteWorksheetInput) -> dict:
    """Delete a worksheet (tab) from a spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        spreadsheet.del_worksheet(worksheet)
        
        return {
            "success": True,
            "message": f"Deleted worksheet: {params.worksheet_name}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def clear_range(params: ClearRangeInput) -> dict:
    """Clear data from a specific range in a worksheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        worksheet.batch_clear([params.range])
        
        return {
            "success": True,
            "message": f"Cleared range: {params.range}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def copy_worksheet(params: CopyWorksheetInput) -> dict:
    """Duplicate a worksheet within the same spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        new_worksheet = worksheet.duplicate(new_sheet_name=params.new_title)
        
        return {
            "success": True,
            "message": f"Copied worksheet to: {params.new_title}",
            "new_worksheet_id": new_worksheet.id
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def format_cells(params: FormatCellsInput) -> dict:
    """Apply formatting to cells (bold, italic, colors)."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        # Build format object
        fmt = {}
        if params.bold is not None or params.italic is not None:
            fmt['textFormat'] = {}
            if params.bold is not None:
                fmt['textFormat']['bold'] = params.bold
            if params.italic is not None:
                fmt['textFormat']['italic'] = params.italic
        
        if params.background_color:
            fmt['backgroundColor'] = params.background_color
        if params.text_color:
            fmt['textFormat'] = fmt.get('textFormat', {})
            fmt['textFormat']['foregroundColor'] = params.text_color
        
        worksheet.format(params.range, fmt)
        
        return {
            "success": True,
            "message": f"Applied formatting to range: {params.range}"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def search_sheets(params: SearchSheetsInput) -> dict:
    """Search for data across worksheets in a spreadsheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        
        results = []
        worksheets = [spreadsheet.worksheet(params.worksheet_name)] if params.worksheet_name else spreadsheet.worksheets()
        
        for ws in worksheets:
            cells = ws.findall(params.search_term)
            for cell in cells:
                results.append({
                    "worksheet": ws.title,
                    "row": cell.row,
                    "col": cell.col,
                    "value": cell.value
                })
        
        return {
            "success": True,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# GOOGLE CALENDAR TOOLS
# ============================================================================

@mcp.tool()
def create_calendar_event(params: CreateEventInput) -> dict:
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
        if params.attendees:
            event['attendees'] = [{'email': email} for email in params.attendees]
        
        created_event = service.events().insert(
            calendarId=params.calendar_id,
            body=event
        ).execute()
        
        return {
            "success": True,
            "message": "Event created successfully",
            "event_id": created_event['id'],
            "html_link": created_event.get('htmlLink'),
            "summary": created_event['summary']
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def update_calendar_event(params: UpdateEventInput) -> dict:
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
        
        return {
            "success": True,
            "message": "Event updated successfully",
            "event_id": updated_event['id'],
            "summary": updated_event['summary']
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def delete_calendar_event(params: DeleteEventInput) -> dict:
    """Delete a calendar event."""
    try:
        service = get_calendar_service()
        
        service.events().delete(
            calendarId=params.calendar_id,
            eventId=params.event_id
        ).execute()
        
        return {
            "success": True,
            "message": f"Event {params.event_id} deleted successfully"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def list_calendar_events(
    calendar_id: str = "primary",
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 10
) -> dict:
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
        
        formatted_events = []
        for event in events:
            formatted_events.append({
                'id': event['id'],
                'summary': event.get('summary', 'No title'),
                'start': event['start'].get('dateTime', event['start'].get('date')),
                'end': event['end'].get('dateTime', event['end'].get('date')),
                'location': event.get('location'),
                'description': event.get('description')
            })
        
        return {
            "success": True,
            "count": len(formatted_events),
            "events": formatted_events
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    from mcp.server.sse import SseServerTransport
    
    # Get port from environment or default
    port = int(os.environ.get("PORT", 8000))
    
    # Create SSE transport
    sse = SseServerTransport("/")
    
    # Run with uvicorn
    uvicorn.run(
        mcp.get_asgi_app(sse),
        host="0.0.0.0",
        port=port
    )