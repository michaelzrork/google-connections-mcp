#!/usr/bin/env python3
"""
Remote MCP Server for Google Sheets Management
Full read/write access to Google Sheets with accomplishment tracking
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
# SERVER STARTUP
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