#!/usr/bin/env python3
"""
Daily Tracking MCP Server
Provides intelligent querying and analysis of Google Sheets data
Returns only processed insights, not raw data
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# Initialize MCP server
mcp = FastMCP("Daily Tracking")

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
# ROW MANIPULATION TOOLS
# ============================================================================

class FindRowByIdInput(BaseModel):
    """Input for finding a row by ID."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    id_column: str = Field(..., min_length=1, description="Column name containing IDs (e.g., 'ID')")
    id_value: str = Field(..., min_length=1, description="The ID value to search for")

@mcp.tool(name="find_row_by_id")
async def find_row_by_id(params: FindRowByIdInput) -> str:
    """Find the row number for a specific ID value."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        all_values = worksheet.get_all_values()
        if not all_values:
            return json.dumps({"success": False, "error": "Worksheet is empty"}, indent=2)
        
        header = all_values[0]
        try:
            id_col_index = header.index(params.id_column)
        except ValueError:
            return json.dumps({"success": False, "error": f"Column '{params.id_column}' not found"}, indent=2)
        
        for row_num, row in enumerate(all_values[1:], start=2):
            if id_col_index < len(row) and row[id_col_index] == params.id_value:
                return json.dumps({
                    "success": True,
                    "row_number": row_num,
                    "row_data": dict(zip(header, row))
                }, indent=2)
        
        return json.dumps({"success": False, "error": f"No row found with {params.id_column}='{params.id_value}'"}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class UpdateRowByIdInput(BaseModel):
    """Input for updating a row by ID."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    id_column: str = Field(..., min_length=1)
    id_value: str = Field(..., min_length=1)
    updates: Dict[str, Any] = Field(..., description="Dictionary of column_name: new_value pairs")

@mcp.tool(name="update_row_by_id")
async def update_row_by_id(params: UpdateRowByIdInput) -> str:
    """Update specific columns in a row by ID. Only updates specified columns."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        all_values = worksheet.get_all_values()
        if not all_values:
            return json.dumps({"success": False, "error": "Worksheet is empty"}, indent=2)
        
        header = all_values[0]
        id_col_index = header.index(params.id_column)
        
        target_row_num = None
        target_row_data = None
        
        for row_num, row in enumerate(all_values[1:], start=2):
            if id_col_index < len(row) and row[id_col_index] == params.id_value:
                target_row_num = row_num
                target_row_data = list(row)
                break
        
        if target_row_num is None:
            return json.dumps({"success": False, "error": f"No row found"}, indent=2)
        
        for col_name, new_value in params.updates.items():
            col_index = header.index(col_name)
            while len(target_row_data) <= col_index:
                target_row_data.append('')
            target_row_data[col_index] = str(new_value)
        
        range_to_update = f"A{target_row_num}:{chr(65 + len(target_row_data) - 1)}{target_row_num}"
        worksheet.update(range_to_update, [target_row_data])
        
        return json.dumps({"success": True, "message": f"Updated row {target_row_num}"}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

class DeleteRowByIdInput(BaseModel):
    """Input for deleting a row by ID."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    id_column: str = Field(..., min_length=1)
    id_value: str = Field(..., min_length=1)

@mcp.tool(name="delete_row_by_id")
async def delete_row_by_id(params: DeleteRowByIdInput) -> str:
    """Delete a row by ID. Completely removes it from the sheet."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        all_values = worksheet.get_all_values()
        if not all_values:
            return json.dumps({"success": False, "error": "Worksheet is empty"}, indent=2)
        
        header = all_values[0]
        id_col_index = header.index(params.id_column)
        
        for row_num, row in enumerate(all_values[1:], start=2):
            if id_col_index < len(row) and row[id_col_index] == params.id_value:
                worksheet.delete_rows(row_num)
                return json.dumps({"success": True, "message": f"Deleted row {row_num}"}, indent=2)
        
        return json.dumps({"success": False, "error": "Row not found"}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# HELPER FUNCTIONS FOR PRIORITY PARSING
# ============================================================================

def parse_priorities_cell(cell_content):
    """
    Parse the priorities cell into structured data.
    
    Input example:
    "1. Apply to 3 jobs | Completed | Applied to Fluency, BETA, OVR
     2. Install Docker Desktop | Partial | Downloaded but ran out of time
     3. Review database scripts | Not Started |"
    
    Returns list of dicts with number, task, status, notes
    """
    if pd.isna(cell_content) or cell_content.strip() == '':
        return []
    
    priorities = []
    lines = cell_content.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Split by | delimiter
        parts = [p.strip() for p in line.split('|')]
        
        if len(parts) < 2:
            continue
            
        # Extract number and task from first part
        first_part = parts[0]
        if '. ' in first_part:
            num_str, task = first_part.split('. ', 1)
            try:
                number = int(num_str)
            except:
                number = None
        else:
            number = None
            task = first_part
        
        # Extract status and notes
        status = parts[1] if len(parts) > 1 else ''
        notes = parts[2] if len(parts) > 2 else ''
        
        priorities.append({
            'number': number,
            'task': task.strip(),
            'status': status.strip(),
            'notes': notes.strip()
        })
    
    return priorities

# ============================================================================
# CORE QUERYING FUNCTION
# ============================================================================

class QuerySheetInput(BaseModel):
    """Input for querying a sheet with filters."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    filters: List[Dict[str, Any]] = Field(default=[])
    return_columns: Optional[List[str]] = Field(default=None)
    limit: Optional[int] = Field(default=None)
    sort_by: Optional[str] = Field(default=None)
    sort_desc: bool = Field(default=False)

@mcp.tool(name="query_sheet")
async def query_sheet(params: QuerySheetInput) -> str:
    """
    Query a Google Sheet with flexible filtering.
    
    Filters support:
    - {'field': 'Status', 'operator': '==', 'value': 'FALSE'}
    - {'field': 'Do Date', 'operator': '<=', 'value': '2025-10-27'}
    - {'field': 'Category', 'operator': 'in', 'value': ['Work', 'Job Search']}
    
    Operators: ==, !=, >, <, >=, <=, in, not in, contains, not contains, is_null, not_null
    """
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        # Get all data as DataFrame
        data = worksheet.get_all_values()
        if not data:
            return json.dumps({"success": True, "data": [], "count": 0}, indent=2)
        
        df = pd.DataFrame(data[1:], columns=data[0])
        
        # Apply filters
        for filter_def in params.filters:
            field = filter_def['field']
            operator = filter_def['operator']
            value = filter_def['value']
            
            if field not in df.columns:
                continue
            
            if operator == '==':
                df = df[df[field] == value]
            elif operator == '!=':
                df = df[df[field] != value]
            elif operator == '>':
                df = df[df[field] > value]
            elif operator == '<':
                df = df[df[field] < value]
            elif operator == '>=':
                df = df[df[field] >= value]
            elif operator == '<=':
                df = df[df[field] <= value]
            elif operator == 'in':
                df = df[df[field].isin(value)]
            elif operator == 'not in':
                df = df[~df[field].isin(value)]
            elif operator == 'contains':
                df = df[df[field].str.contains(value, case=False, na=False)]
            elif operator == 'not contains':
                df = df[~df[field].str.contains(value, case=False, na=False)]
            elif operator == 'is_null':
                df = df[df[field].isna() | (df[field] == '')]
            elif operator == 'not_null':
                df = df[df[field].notna() & (df[field] != '')]
        
        # Select columns
        if params.return_columns:
            available_cols = [col for col in params.return_columns if col in df.columns]
            if available_cols:
                df = df[available_cols]
        
        # Sort
        if params.sort_by and params.sort_by in df.columns:
            df = df.sort_values(by=params.sort_by, ascending=not params.sort_desc)
        
        # Limit
        if params.limit:
            df = df.head(params.limit)
        
        # Convert to dict
        result = df.to_dict('records')
        
        return json.dumps({
            "success": True,
            "data": result,
            "count": len(result)
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================

class AnalyzeSheetInput(BaseModel):
    """Input for analyzing sheet data."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    analysis_type: str = Field(..., description="Type of analysis: priority_patterns, count_by_pattern, date_summary")
    date_column: Optional[str] = Field(default=None)
    days_back: Optional[int] = Field(default=7)
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    options: Dict[str, Any] = Field(default={})

@mcp.tool(name="analyze_sheet")
async def analyze_sheet(params: AnalyzeSheetInput) -> str:
    """
    Analyze sheet data and return insights (not raw data).
    
    Analysis types:
    - priority_patterns: Detect avoidance, completion rates, streaks
    - count_by_pattern: Count rows matching a pattern
    - date_summary: Summarize data for a specific date range
    """
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(params.spreadsheet_id)
        worksheet = spreadsheet.worksheet(params.worksheet_name)
        
        # Get all data as DataFrame
        data = worksheet.get_all_values()
        if not data:
            return json.dumps({"success": True, "insights": {}, "message": "No data found"}, indent=2)
        
        df = pd.DataFrame(data[1:], columns=data[0])
        
        # Filter by date if specified
        if params.date_column and params.date_column in df.columns:
            df[params.date_column] = pd.to_datetime(df[params.date_column], errors='coerce')
            
            if params.start_date and params.end_date:
                start = pd.to_datetime(params.start_date)
                end = pd.to_datetime(params.end_date)
                df = df[(df[params.date_column] >= start) & (df[params.date_column] <= end)]
            elif params.days_back:
                cutoff = datetime.now() - timedelta(days=params.days_back)
                df = df[df[params.date_column] >= cutoff]
        
        # Run analysis based on type
        if params.analysis_type == 'priority_patterns':
            insights = analyze_priority_patterns(df, params.options)
        elif params.analysis_type == 'count_by_pattern':
            insights = count_by_pattern(df, params.options)
        elif params.analysis_type == 'date_summary':
            insights = date_summary(df, params.options)
        else:
            return json.dumps({"success": False, "error": f"Unknown analysis type: {params.analysis_type}"}, indent=2)
        
        return json.dumps({
            "success": True,
            "insights": insights
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

def analyze_priority_patterns(df: pd.DataFrame, options: dict) -> dict:
    """Analyze daily priorities for patterns."""
    if 'Priorities' not in df.columns:
        return {"error": "No Priorities column found"}
    
    # Parse all priorities
    all_priorities = []
    for idx, row in df.iterrows():
        parsed = parse_priorities_cell(row.get('Priorities', ''))
        for p in parsed:
            p['date'] = row.get('Date')
            all_priorities.append(p)
    
    if not all_priorities:
        return {"message": "No priorities found"}
    
    priorities_df = pd.DataFrame(all_priorities)
    
    results = {
        'avoidance_patterns': [],
        'completion_rates': {},
        'streak_info': []
    }
    
    # 1. Avoidance patterns
    if options.get('detect_avoidance', True):
        for task in priorities_df['task'].unique():
            task_entries = priorities_df[priorities_df['task'] == task]
            incomplete = task_entries['status'].isin(['Not Started', 'Moved', 'Partial'])
            incomplete_count = incomplete.sum()
            
            if len(task_entries) >= 3 and incomplete_count >= 2:
                results['avoidance_patterns'].append({
                    'task': task,
                    'days_appeared': len(task_entries),
                    'days_incomplete': int(incomplete_count),
                    'avg_position': float(task_entries['number'].mean())
                })
    
    # 2. Completion rates by priority position
    if options.get('completion_rates', True):
        for pos in range(1, 6):
            pos_priorities = priorities_df[priorities_df['number'] == pos]
            if len(pos_priorities) > 0:
                completed = (pos_priorities['status'] == 'Completed').sum()
                results['completion_rates'][f'P{pos}'] = {
                    'rate': float(completed / len(pos_priorities)),
                    'completed': int(completed),
                    'total': int(len(pos_priorities))
                }
    
    # 3. Streaks
    if options.get('streaks', True):
        # Get most recent date's tasks
        if 'date' in priorities_df.columns:
            priorities_df['date'] = pd.to_datetime(priorities_df['date'], errors='coerce')
            sorted_priorities = priorities_df.sort_values('date', ascending=False)
            
            if len(sorted_priorities) > 0:
                latest_date = sorted_priorities.iloc[0]['date']
                latest_tasks = sorted_priorities[sorted_priorities['date'] == latest_date]['task'].tolist()
                
                for task in latest_tasks:
                    # Count consecutive days
                    streak = 0
                    current_date = latest_date
                    
                    for _ in range(7):
                        day_priorities = sorted_priorities[sorted_priorities['date'] == current_date]
                        if task in day_priorities['task'].values:
                            streak += 1
                            current_date = current_date - timedelta(days=1)
                        else:
                            break
                    
                    if streak >= 2:
                        results['streak_info'].append({
                            'task': task,
                            'days': int(streak)
                        })
    
    # 4. Yesterday's status (if requested)
    if options.get('yesterday_status', False):
        yesterday = datetime.now() - timedelta(days=1)
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        yesterday_priorities = priorities_df[
            priorities_df['date'] == yesterday_str
        ]
        
        if len(yesterday_priorities) > 0:
            results['yesterday_status'] = yesterday_priorities.to_dict('records')
    
    return results

def count_by_pattern(df: pd.DataFrame, options: dict) -> dict:
    """Count rows matching a pattern."""
    search_column = options.get('search_column')
    pattern = options.get('pattern')
    case_insensitive = options.get('case_insensitive', True)
    
    if not search_column or not pattern:
        return {"error": "Must specify search_column and pattern"}
    
    if search_column not in df.columns:
        return {"error": f"Column {search_column} not found"}
    
    matches = df[df[search_column].str.contains(pattern, case=case_insensitive, na=False)]
    
    return {
        "count": len(matches),
        "matches": matches.to_dict('records') if options.get('return_matches', False) else []
    }

def date_summary(df: pd.DataFrame, options: dict) -> dict:
    """Summarize data for specific dates."""
    date_column = options.get('date_column', 'Date')
    target_date = options.get('target_date')
    
    if date_column not in df.columns:
        return {"error": f"Column {date_column} not found"}
    
    if target_date:
        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
        target = pd.to_datetime(target_date)
        day_data = df[df[date_column] == target]
        
        return {
            "date": target_date,
            "count": len(day_data),
            "data": day_data.to_dict('records')
        }
    
    return {"error": "Must specify target_date"}

# ============================================================================
# DAILY TRACKING HELPER FUNCTIONS
# ============================================================================

# Get default spreadsheet ID from environment
DEFAULT_SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")

@mcp.tool(name="log_accomplishment")
async def log_accomplishment(
    date: str,
    time: str,
    category: str,
    accomplishment: str,
    notes: str = ""
) -> str:
    """Quick log an accomplishment to the Accomplishments sheet."""
    try:
        import uuid
        client = get_sheets_client()
        spreadsheet = client.open_by_key(DEFAULT_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet('Accomplishments')
        
        # Generate unique ID
        accomplishment_id = str(uuid.uuid4())
        
        # Append row
        worksheet.append_row([date, time, category, accomplishment, notes, accomplishment_id])
        
        return json.dumps({
            "success": True,
            "message": "Accomplishment logged"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="get_actionable_tasks")
async def get_actionable_tasks(limit: int = 20) -> str:
    """Get incomplete tasks that are actionable today."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(DEFAULT_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet('Tasks')
        
        # Get all data
        data = worksheet.get_all_values()
        if not data:
            return json.dumps({"success": True, "tasks": []}, indent=2)
        
        df = pd.DataFrame(data[1:], columns=data[0])
        
        # Filter incomplete tasks
        df = df[df['Status'] == 'FALSE']
        
        # Filter by Do Date (today or earlier, or blank)
        today = datetime.now().strftime('%Y-%m-%d')
        df = df[
            (df['Do Date'] <= today) | 
            (df['Do Date'].isna()) | 
            (df['Do Date'] == '')
        ]
        
        # Limit results
        df = df.head(limit)
        
        # Return as list
        tasks = df.to_dict('records')
        
        return json.dumps({
            "success": True,
            "tasks": tasks,
            "count": len(tasks)
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="create_task")
async def create_task(
    task: str,
    category: str = "",
    projects: str = "",
    tags: str = "",
    do_date: str = "",
    due_date: str = "",
    due_time: str = "",
    urgent: str = "FALSE",
    important: str = "FALSE",
    priority: str = "",
    location: str = "",
    notes: str = ""
) -> str:
    """Create a new task in the Tasks sheet."""
    try:
        import uuid
        client = get_sheets_client()
        spreadsheet = client.open_by_key(DEFAULT_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet('Tasks')
        
        created_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Append row with all columns
        worksheet.append_row([
            created_date,  # Created Date
            "",           # Completed Date
            "FALSE",      # Status
            task,         # Task
            tags,         # Tags
            category,     # Category
            projects,     # Projects
            do_date,      # Do Date
            due_date,     # Due Date
            due_time,     # Due Time
            urgent,       # Urgent
            important,    # Important
            priority,     # Priority
            location,     # Location
            notes,        # Notes
            "",           # Recurring
            ""            # Recurring Schedule
        ])
        
        return json.dumps({
            "success": True,
            "message": f"Task created: {task}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="mark_task_complete")
async def mark_task_complete(
    task_name: str,
    completed_date: str = ""
) -> str:
    """Find a task by name and mark it complete."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(DEFAULT_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet('Tasks')
        
        if not completed_date:
            completed_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Get all data
        data = worksheet.get_all_values()
        if not data:
            return json.dumps({"success": False, "error": "No tasks found"}, indent=2)
        
        # Find the task
        for i, row in enumerate(data[1:], start=2):  # Start at row 2 (skip header)
            if row[3] == task_name and row[2] == 'FALSE':  # Task column is index 3, Status is index 2
                # Update Status (column C) and Completed Date (column B)
                worksheet.update_cell(i, 3, 'TRUE')  # Status
                worksheet.update_cell(i, 2, completed_date)  # Completed Date
                
                return json.dumps({
                    "success": True,
                    "message": f"Task marked complete: {task_name}"
                }, indent=2)
        
        return json.dumps({
            "success": False,
            "error": f"Task not found or already complete: {task_name}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="set_daily_priorities")
async def set_daily_priorities(
    date: str,
    priorities: List[Dict[str, str]]
) -> str:
    """
    Set the day's priorities in the Daily Priorities sheet.
    
    priorities format: [
        {'number': 1, 'task': 'Apply to 3 jobs', 'status': '', 'notes': ''},
        {'number': 2, 'task': 'Install Docker', 'status': '', 'notes': ''}
    ]
    """
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(DEFAULT_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet('Daily Priorities')
        
        # Format priorities into cell content
        lines = []
        for p in priorities:
            num = p.get('number', '')
            task = p.get('task', '')
            status = p.get('status', '')
            notes = p.get('notes', '')
            lines.append(f"{num}. {task} | {status} | {notes}")
        
        priorities_text = '\n'.join(lines)
        
        # Append new row with date and priorities
        worksheet.append_row([date, priorities_text])
        
        return json.dumps({
            "success": True,
            "message": f"Set {len(priorities)} priorities for {date}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

@mcp.tool(name="update_priority_status")
async def update_priority_status(
    date: str,
    priority_number: int,
    status: str,
    notes: str = ""
) -> str:
    """Update the status of a specific priority for a given date."""
    try:
        client = get_sheets_client()
        spreadsheet = client.open_by_key(DEFAULT_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet('Daily Priorities')
        
        # Get all data
        data = worksheet.get_all_values()
        if not data:
            return json.dumps({"success": False, "error": "No priorities found"}, indent=2)
        
        # Find the date row
        for i, row in enumerate(data[1:], start=2):  # Start at row 2 (skip header)
            if row[0] == date:  # Date is in column A
                # Parse current priorities
                current_priorities = parse_priorities_cell(row[1])
                
                # Update the specific priority
                for p in current_priorities:
                    if p['number'] == priority_number:
                        p['status'] = status
                        if notes:
                            p['notes'] = notes
                
                # Format back to cell content
                lines = []
                for p in current_priorities:
                    lines.append(f"{p['number']}. {p['task']} | {p['status']} | {p['notes']}")
                
                updated_text = '\n'.join(lines)
                
                # Write back to cell
                worksheet.update_cell(i, 2, updated_text)  # Column B
                
                return json.dumps({
                    "success": True,
                    "message": f"Updated priority {priority_number} for {date}"
                }, indent=2)
        
        return json.dumps({
            "success": False,
            "error": f"No priorities found for date: {date}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# BASIC CRUD OPERATIONS (Keep these for writing)
# ============================================================================

class ReadSheetInput(BaseModel):
    """Input for reading a sheet."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: Optional[str] = Field(default=None)

# @mcp.tool(name="read_sheet")
# async def read_sheet(params: ReadSheetInput) -> str:
#     """Read data from a specific worksheet."""
#     try:
#         client = get_sheets_client()
#         spreadsheet = client.open_by_key(params.spreadsheet_id)
#         worksheet = spreadsheet.worksheet(params.worksheet_name)
        
#         if params.range:
#             values = worksheet.get(params.range)
#         else:
#             values = worksheet.get_all_values()
        
#         return json.dumps({
#             "success": True,
#             "worksheet": params.worksheet_name,
#             "data": values
#         }, indent=2)
        
#     except Exception as e:
#         return json.dumps({"success": False, "error": str(e)}, indent=2)

class WriteSheetInput(BaseModel):
    """Input for writing to a sheet."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: str = Field(..., min_length=1)
    values: List[List[Any]] = Field(..., min_length=1)

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
    values: List[List[Any]] = Field(..., min_length=1)

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