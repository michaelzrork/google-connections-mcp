#!/usr/bin/env python3
"""
Remote MCP Server for Accomplishment Tracking
Connects to Google Sheets via service account authentication
"""

import os
import json
from datetime import datetime, date
from typing import Optional, List
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Initialize MCP server with HTTP transport
mcp = FastMCP("accomplishments_mcp")

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

# Pydantic Models
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

# MCP Tools
@mcp.tool(
    name="add_accomplishment",
    annotations={
        "title": "Add Accomplishment",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def add_accomplishment(params: AddAccomplishmentInput) -> str:
    """Add a new accomplishment to Google Sheets.
    
    Args:
        params: Accomplishment details including description, category, tags, notes
    
    Returns:
        JSON confirmation with accomplishment details
    """
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        # Generate ID and date
        accomplishment_id = str(uuid4())
        accomplishment_date = params.date_override or date.today().isoformat()
        current_time = datetime.now().strftime("%H:%M")
        
        # Append to sheet
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
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)

@mcp.tool(
    name="view_accomplishments",
    annotations={
        "title": "View Accomplishments",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def view_accomplishments(params: ViewAccomplishmentsInput) -> str:
    """View accomplishments with optional filtering.
    
    Args:
        params: Filter criteria including date range, category, limit
    
    Returns:
        Formatted list of accomplishments
    """
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        # Get all records (skip header)
        records = sheet.get_all_records()
        
        # Apply filters
        filtered = records
        
        if params.start_date:
            filtered = [r for r in filtered if r.get('Date', '') >= params.start_date]
        if params.end_date:
            filtered = [r for r in filtered if r.get('Date', '') <= params.end_date]
        if params.category:
            filtered = [r for r in filtered if r.get('Category', '') == params.category]
        
        # Sort by date (newest first) and limit
        filtered = sorted(filtered, key=lambda x: x.get('Date', ''), reverse=True)
        filtered = filtered[:params.limit]
        
        if not filtered:
            return "No accomplishments found matching your criteria."
        
        # Format as markdown
        lines = [f"# Your Accomplishments ({len(filtered)} total)\n"]
        
        for acc in filtered:
            date_str = acc.get('Date', '')
            cat_str = f" [{acc.get('Category', '')}]" if acc.get('Category') else ""
            lines.append(f"**{date_str}** - {acc.get('Accomplishment', '')}{cat_str}")
            if acc.get('Notes'):
                lines.append(f"  *{acc.get('Notes', '')}*")
        
        return "\n".join(lines)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)

@mcp.tool(
    name="get_accomplishment_stats",
    annotations={
        "title": "Get Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def get_accomplishment_stats(params: GetStatsInput) -> str:
    """Get statistics about accomplishments.
    
    Args:
        params: Time period for analysis (days)
    
    Returns:
        Statistical summary
    """
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        records = sheet.get_all_records()
        
        # Calculate date range
        from datetime import timedelta
        end_date = date.today()
        start_date = end_date - timedelta(days=params.days - 1)
        
        # Filter by date range
        filtered = [
            r for r in records
            if start_date.isoformat() <= r.get('Date', '') <= end_date.isoformat()
        ]
        
        total = len(filtered)
        
        # Count by category
        categories = {}
        for r in filtered:
            cat = r.get('Category', 'Uncategorized')
            categories[cat] = categories.get(cat, 0) + 1
        
        # Format output
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
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)

@mcp.tool(
    name="delete_accomplishment",
    annotations={
        "title": "Delete Accomplishment",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def delete_accomplishment(accomplishment_id: str) -> str:
    """Delete an accomplishment by ID.
    
    Args:
        accomplishment_id: The UUID of the accomplishment to delete
    
    Returns:
        JSON confirmation of deletion
    """
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        # Find the row with this ID (column F)
        cell = sheet.find(accomplishment_id)
        if not cell:
            return json.dumps({
                "success": False,
                "error": "Accomplishment not found"
            }, indent=2)
        
        # Delete the row
        sheet.delete_rows(cell.row)
        
        return json.dumps({
            "success": True,
            "message": f"Accomplishment {accomplishment_id} deleted successfully"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)


class EditAccomplishmentInput(BaseModel):
    """Input for editing an accomplishment."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    accomplishment_id: str = Field(..., min_length=1)
    description: Optional[str] = Field(default=None, min_length=1, max_length=500)
    category: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=500)


@mcp.tool(
    name="edit_accomplishment",
    annotations={
        "title": "Edit Accomplishment",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def edit_accomplishment(params: EditAccomplishmentInput) -> str:
    """Edit an existing accomplishment.
    
    Args:
        params: Accomplishment ID and fields to update
    
    Returns:
        JSON confirmation of edit
    """
    try:
        client = get_sheets_client()
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        # Find the row with this ID
        cell = sheet.find(params.accomplishment_id)
        if not cell:
            return json.dumps({
                "success": False,
                "error": "Accomplishment not found"
            }, indent=2)
        
        row_num = cell.row
        
        # Update fields if provided
        if params.category is not None:
            sheet.update_cell(row_num, 3, params.category)
        if params.description is not None:
            sheet.update_cell(row_num, 4, params.description)
        if params.notes is not None:
            sheet.update_cell(row_num, 5, params.notes)
        
        return json.dumps({
            "success": True,
            "message": f"Accomplishment {params.accomplishment_id} updated successfully"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)

# Run server with SSE transport
if __name__ == "__main__":
    import os
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import Response
    
    port = int(os.environ.get("PORT", 8000))
    
    # Create SSE transport
    sse = SseServerTransport("/messages/")
    
    # Define SSE endpoint handler
    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1],
                mcp._mcp_server.create_initialization_options()
            )
        return Response()
    
    async def handle_root(request):
        return Response("MCP Server Running", media_type="text/plain")

    # Create Starlette app
    app = Starlette(
        routes=[
            Route("/", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages", app=sse.handle_post_message),
        ]
    )
    
    # Run with uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)