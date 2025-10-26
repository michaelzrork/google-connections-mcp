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

# Run server
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="sse", host="0.0.0.0", port=port)
