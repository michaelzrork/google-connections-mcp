#!/usr/bin/env python3
"""
Daily Tracking MCP Server - Refactored
Generic Google services access with OAuth
No sheet-specific helpers - just generic CRUD
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from datetime import datetime
import pytz
from mcp import tool

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict
import pandas as pd

from auth_manager import get_auth_manager, create_oauth_flow
from sheet_mapper import get_sheet_mapper, SheetMapper

# Initialize MCP server
mcp = FastMCP("Daily Tracking")

# Get auth manager
auth = get_auth_manager()

# ============================================================================
# GET TIME TOOL
# ============================================================================

@tool(name="get_time", description="Returns the current time in ISO format for America/New_York")
async def get_time():
    tz = pytz.timezone("America/New_York")
    now = datetime.now(tz)
    return {"currentTime": now.isoformat()}


# ============================================================================
# GOOGLE SHEETS - GENERIC OPERATIONS
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

def parse_datetime(value):
    """Parse a value as datetime, supporting multiple formats."""
    if pd.isna(value) or value == '':
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Try multiple common formats
        formats = [
            '%m/%d/%Y',           # 11/4/2025
            '%Y-%m-%d',           # 2025-11-04
            '%m/%d/%Y %I:%M %p',  # 11/4/2025 2:30 PM
            '%Y-%m-%d %H:%M:%S',  # 2025-11-04 14:30:00
            '%m/%d/%Y %H:%M:%S',  # 11/4/2025 14:30:00
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None

@mcp.tool(name="query_sheet")
async def query_sheet(params: QuerySheetInput) -> str:
    """
    Query a Google Sheet with flexible filtering.
    
    Filters support:
    - {'field': 'Status', 'operator': '==', 'value': 'FALSE'}
    - {'field': 'Do Date', 'operator': '<=', 'value': '2025-10-27'}
    - {'field': 'Category', 'operator': 'in', 'value': ['Work', 'Job Search']}
    
    Operators: ==, !=, >, <, >=, <=, in, not in, contains, not contains, is_null, not_null
    
    Date/time operators (>, <, >=, <=, ==, !=) automatically parse datetime values.
    """
    try:
        sheets_client = auth.get_sheets_client()
        mapper = get_sheet_mapper(sheets_client, params.spreadsheet_id, params.worksheet_name)
        df = mapper.to_dataframe()
        
        # Apply filters
        for filter_def in params.filters:
            field = filter_def['field']
            operator = filter_def['operator']
            value = filter_def['value']
            
            if field not in df.columns:
                continue
            
            # For date/time comparison operators, try to parse as datetime
            if operator in ['>', '<', '>=', '<=', '==', '!=']:
                filter_dt = parse_datetime(value)
                if filter_dt is not None:
                    # Parse column values as datetime - use reset index to avoid alignment issues
                    df_dts = pd.Series([parse_datetime(val) for val in df[field]], index=df.index)
                    # Only apply filter to rows where datetime parsing succeeded
                    valid_mask = df_dts.notna()
                    
                    if operator == '==':
                        mask = valid_mask & (df_dts == filter_dt)
                    elif operator == '!=':
                        mask = valid_mask & (df_dts != filter_dt)
                    elif operator == '>':
                        mask = valid_mask & (df_dts > filter_dt)
                    elif operator == '<':
                        mask = valid_mask & (df_dts < filter_dt)
                    elif operator == '>=':
                        mask = valid_mask & (df_dts >= filter_dt)
                    elif operator == '<=':
                        mask = valid_mask & (df_dts <= filter_dt)
                    
                    df = df[mask]
                    continue
            
            # Fall back to original string/value comparison
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
        
        result = df.to_dict('records')
        
        return json.dumps({
            "success": True,
            "data": result,
            "count": len(result)
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


class FindRowByIdInput(BaseModel):
    """Input for finding a row by ID."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    id_column: str = Field(..., min_length=1)
    id_value: str = Field(..., min_length=1)

@mcp.tool(name="find_row_by_id")
async def find_row_by_id(params: FindRowByIdInput) -> str:
    """Find the row number for a specific ID value."""
    try:
        sheets_client = auth.get_sheets_client()
        mapper = get_sheet_mapper(sheets_client, params.spreadsheet_id, params.worksheet_name)
        
        result = mapper.find_row_by_value(params.id_column, params.id_value)
        
        if result:
            row_num, row_data = result
            return json.dumps({
                "success": True,
                "row_number": row_num,
                "row_data": mapper.row_to_dict(row_data)
            }, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error": f"No row found with {params.id_column}='{params.id_value}'"
            }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


class UpdateRowByIdInput(BaseModel):
    """Input for updating a row by ID."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    id_column: str = Field(..., min_length=1)
    id_value: str = Field(..., min_length=1)
    updates: Dict[str, Any] = Field(...)

@mcp.tool(name="update_row_by_id")
async def update_row_by_id(params: UpdateRowByIdInput) -> str:
    """Update specific columns in a row by ID."""
    try:
        sheets_client = auth.get_sheets_client()
        mapper = get_sheet_mapper(sheets_client, params.spreadsheet_id, params.worksheet_name)
        
        result = mapper.find_row_by_value(params.id_column, params.id_value)
        
        if not result:
            return json.dumps({
                "success": False,
                "error": f"No row found with {params.id_column}='{params.id_value}'"
            }, indent=2)
        
        row_num, _ = result
        mapper.update_row(row_num, params.updates)
        
        return json.dumps({
            "success": True,
            "message": f"Updated row {row_num}"
        }, indent=2)
        
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
    """Delete a row by ID."""
    try:
        sheets_client = auth.get_sheets_client()
        mapper = get_sheet_mapper(sheets_client, params.spreadsheet_id, params.worksheet_name)
        
        result = mapper.find_row_by_value(params.id_column, params.id_value)
        
        if not result:
            return json.dumps({
                "success": False,
                "error": f"No row found with {params.id_column}='{params.id_value}'"
            }, indent=2)
        
        row_num, _ = result
        mapper.worksheet.delete_rows(row_num)
        
        return json.dumps({
            "success": True,
            "message": f"Deleted row {row_num}"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


class AppendRowsInput(BaseModel):
    """Input for appending rows."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    
    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    values: List[Dict[str, Any]] = Field(..., min_length=1)

@mcp.tool(name="append_rows")
async def append_rows(params: AppendRowsInput) -> str:
    """Append multiple rows to sheet. Each row is a dict of column_name: value."""
    try:
        sheets_client = auth.get_sheets_client()
        mapper = get_sheet_mapper(sheets_client, params.spreadsheet_id, params.worksheet_name)
        
        for row_dict in params.values:
            mapper.append_row(row_dict)
        
        return json.dumps({
            "success": True,
            "message": f"Appended {len(params.values)} rows"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ============================================================================
# GOOGLE CALENDAR TOOLS
# ============================================================================

@mcp.tool(name="list_calendars")
async def list_calendars(page_token: str = None) -> str:
    """List all available calendars"""
    try:
        service = auth.get_calendar_service()
        calendars_result = service.calendarList().list(pageToken=page_token).execute()
        
        return json.dumps({
            "success": True,
            "calendars": calendars_result.get('items', []),
            "nextPageToken": calendars_result.get('nextPageToken')
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="list_calendar_events")
async def list_calendar_events(
    calendar_id: str = "primary",
    time_min: str = None,
    time_max: str = None,
    max_results: int = 25,
    query: str = None,
    page_token: str = None
) -> str:
    """List events from a calendar"""
    try:
        service = auth.get_calendar_service()
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime',
            q=query,
            pageToken=page_token
        ).execute()
        
        return json.dumps({
            "success": True,
            "events": events_result.get('items', []),
            "nextPageToken": events_result.get('nextPageToken')
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="get_calendar_event")
async def get_calendar_event(calendar_id: str, event_id: str) -> str:
    """Get a specific calendar event"""
    try:
        service = auth.get_calendar_service()
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        
        return json.dumps({"success": True, "event": event}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="create_calendar_event")
async def create_calendar_event(
    calendar_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: str = None,
    location: str = None,
    attendees: list = None,
    reminders: dict = None
) -> str:
    """Create a calendar event"""
    try:
        service = auth.get_calendar_service()
        
        event_body = {
            'summary': summary,
            'start': {'dateTime': start_time, 'timeZone': 'America/New_York'},
            'end': {'dateTime': end_time, 'timeZone': 'America/New_York'}
        }
        
        if description:
            event_body['description'] = description
        if location:
            event_body['location'] = location
        if attendees:
            event_body['attendees'] = [{'email': email} for email in attendees]
        if reminders:
            event_body['reminders'] = reminders
        
        event = service.events().insert(calendarId=calendar_id, body=event_body).execute()
        
        return json.dumps({
            "success": True,
            "event": event,
            "event_link": event.get('htmlLink')
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="update_calendar_event")
async def update_calendar_event(
    calendar_id: str,
    event_id: str,
    summary: str = None,
    start_time: str = None,
    end_time: str = None,
    description: str = None,
    location: str = None
) -> str:
    """Update an existing calendar event"""
    try:
        service = auth.get_calendar_service()
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        
        if summary:
            event['summary'] = summary
        if start_time:
            event['start'] = {'dateTime': start_time, 'timeZone': 'America/New_York'}
        if end_time:
            event['end'] = {'dateTime': end_time, 'timeZone': 'America/New_York'}
        if description:
            event['description'] = description
        if location:
            event['location'] = location
        
        updated_event = service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=event
        ).execute()
        
        return json.dumps({"success": True, "event": updated_event}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="delete_calendar_event")
async def delete_calendar_event(calendar_id: str, event_id: str) -> str:
    """Delete a calendar event"""
    try:
        service = auth.get_calendar_service()
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Event {event_id} deleted"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ============================================================================
# GMAIL TOOLS (NEW)
# ============================================================================

@mcp.tool(name="list_gmail_messages")
async def list_gmail_messages(
    query: str = None,
    max_results: int = 10,
    page_token: str = None
) -> str:
    """
    List Gmail messages with optional search query.
    
    Query examples:
    - "from:example@gmail.com"
    - "subject:meeting"
    - "is:unread"
    - "after:2025/10/01"
    """
    try:
        service = auth.get_gmail_service()
        
        result = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results,
            pageToken=page_token
        ).execute()
        
        messages = result.get('messages', [])
        
        # Get basic details for each message
        detailed_messages = []
        for msg in messages[:max_results]:
            msg_detail = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['From', 'To', 'Subject', 'Date']
            ).execute()
            
            headers = {h['name']: h['value'] for h in msg_detail.get('payload', {}).get('headers', [])}
            
            detailed_messages.append({
                'id': msg_detail['id'],
                'threadId': msg_detail['threadId'],
                'from': headers.get('From', ''),
                'to': headers.get('To', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
                'snippet': msg_detail.get('snippet', '')
            })
        
        return json.dumps({
            "success": True,
            "messages": detailed_messages,
            "nextPageToken": result.get('nextPageToken')
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="get_gmail_message")
async def get_gmail_message(message_id: str) -> str:
    """Get full content of a Gmail message"""
    try:
        service = auth.get_gmail_service()
        
        msg = service.users().messages().get(
            userId='me',
            id=message_id,
            format='full'
        ).execute()
        
        return json.dumps({"success": True, "message": msg}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="send_gmail_message")
async def send_gmail_message(
    to: str,
    subject: str,
    body: str,
    cc: str = None,
    bcc: str = None
) -> str:
    """Send an email via Gmail"""
    try:
        import base64
        from email.mime.text import MIMEText
        
        service = auth.get_gmail_service()
        
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        if cc:
            message['cc'] = cc
        if bcc:
            message['bcc'] = bcc
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        sent_message = service.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()
        
        return json.dumps({
            "success": True,
            "message_id": sent_message['id']
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ============================================================================
# GMAIL MANAGEMENT TOOLS
# ============================================================================

@mcp.tool(name="modify_gmail_message")
async def modify_gmail_message(
    message_id: str,
    add_labels: List[str] = None,
    remove_labels: List[str] = None
) -> str:
    """
    Modify labels on a Gmail message.
    
    Common labels:
    - 'INBOX' - In inbox
    - 'UNREAD' - Unread
    - 'STARRED' - Starred
    - 'IMPORTANT' - Important
    - 'SPAM' - Spam
    - 'TRASH' - Trash
    - 'CATEGORY_PERSONAL' - Primary category
    - 'CATEGORY_SOCIAL' - Social category
    - 'CATEGORY_PROMOTIONS' - Promotions category
    - 'CATEGORY_UPDATES' - Updates category
    - 'CATEGORY_FORUMS' - Forums category
    
    Custom labels use their label ID (use list_gmail_labels to get IDs)
    """
    try:
        service = auth.get_gmail_service()
        
        body = {}
        if add_labels:
            body['addLabelIds'] = add_labels
        if remove_labels:
            body['removeLabelIds'] = remove_labels
        
        result = service.users().messages().modify(
            userId='me',
            id=message_id,
            body=body
        ).execute()
        
        return json.dumps({
            "success": True,
            "message_id": result['id'],
            "labels": result.get('labelIds', [])
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="batch_modify_gmail")
async def batch_modify_gmail(
    message_ids: List[str],
    add_labels: List[str] = None,
    remove_labels: List[str] = None
) -> str:
    """
    Modify labels on multiple Gmail messages at once.
    Useful for bulk operations like marking many messages as read or archiving.
    """
    try:
        service = auth.get_gmail_service()
        
        body = {'ids': message_ids}
        if add_labels:
            body['addLabelIds'] = add_labels
        if remove_labels:
            body['removeLabelIds'] = remove_labels
        
        result = service.users().messages().batchModify(
            userId='me',
            body=body
        ).execute()
        
        return json.dumps({
            "success": True,
            "modified_count": len(message_ids),
            "message": f"Modified {len(message_ids)} messages"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="list_gmail_labels")
async def list_gmail_labels() -> str:
    """List all Gmail labels (both system and custom)"""
    try:
        service = auth.get_gmail_service()
        
        results = service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        
        return json.dumps({
            "success": True,
            "labels": labels
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="create_gmail_label")
async def create_gmail_label(
    name: str,
    label_list_visibility: str = "labelShow",
    message_list_visibility: str = "show"
) -> str:
    """
    Create a new Gmail label.
    
    label_list_visibility: 'labelShow' or 'labelHide'
    message_list_visibility: 'show' or 'hide'
    """
    try:
        service = auth.get_gmail_service()
        
        label_object = {
            'name': name,
            'labelListVisibility': label_list_visibility,
            'messageListVisibility': message_list_visibility
        }
        
        result = service.users().labels().create(
            userId='me',
            body=label_object
        ).execute()
        
        return json.dumps({
            "success": True,
            "label": result
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# Helper functions for common operations
@mcp.tool(name="mark_gmail_read")
async def mark_gmail_read(message_ids: List[str]) -> str:
    """Mark one or more Gmail messages as read"""
    return await batch_modify_gmail(
        message_ids=message_ids,
        remove_labels=['UNREAD']
    )


@mcp.tool(name="mark_gmail_unread")
async def mark_gmail_unread(message_ids: List[str]) -> str:
    """Mark one or more Gmail messages as unread"""
    return await batch_modify_gmail(
        message_ids=message_ids,
        add_labels=['UNREAD']
    )


@mcp.tool(name="star_gmail")
async def star_gmail(message_ids: List[str]) -> str:
    """Star one or more Gmail messages"""
    return await batch_modify_gmail(
        message_ids=message_ids,
        add_labels=['STARRED']
    )


@mcp.tool(name="unstar_gmail")
async def unstar_gmail(message_ids: List[str]) -> str:
    """Remove star from one or more Gmail messages"""
    return await batch_modify_gmail(
        message_ids=message_ids,
        remove_labels=['STARRED']
    )


@mcp.tool(name="archive_gmail")
async def archive_gmail(message_ids: List[str]) -> str:
    """Archive one or more Gmail messages (remove from inbox)"""
    return await batch_modify_gmail(
        message_ids=message_ids,
        remove_labels=['INBOX']
    )


@mcp.tool(name="move_to_inbox")
async def move_to_inbox(message_ids: List[str]) -> str:
    """Move one or more Gmail messages to inbox"""
    return await batch_modify_gmail(
        message_ids=message_ids,
        add_labels=['INBOX']
    )


@mcp.tool(name="trash_gmail")
async def trash_gmail(message_ids: List[str]) -> str:
    """Move one or more Gmail messages to trash"""
    return await batch_modify_gmail(
        message_ids=message_ids,
        add_labels=['TRASH']
    )


@mcp.tool(name="spam_gmail")
async def spam_gmail(message_ids: List[str]) -> str:
    """Mark one or more Gmail messages as spam"""
    return await batch_modify_gmail(
        message_ids=message_ids,
        add_labels=['SPAM'],
        remove_labels=['INBOX']
    )

# ============================================================================
# GOOGLE TASKS TOOLS
# ============================================================================

# ============================================================================
# GOOGLE TASKS TOOLS
# ============================================================================

@mcp.tool(name="list_task_lists")
async def list_task_lists() -> str:
    """List all Google Tasks task lists"""
    try:
        service = auth.get_tasks_service()
        
        results = service.tasklists().list().execute()
        task_lists = results.get('items', [])
        
        return json.dumps({
            "success": True,
            "task_lists": task_lists
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="list_tasks")
async def list_tasks(
    task_list_id: str = "@default",
    show_completed: bool = False,
    show_hidden: bool = False,
    due_min: str = None,
    due_max: str = None,
    max_results: int = 100
) -> str:
    """
    List tasks from a Google Tasks list.
    
    Args:
        task_list_id: ID of task list (use '@default' for default list)
        show_completed: Include completed tasks
        show_hidden: Include hidden (deleted) tasks
        due_min: Lower bound for task's due date (RFC 3339 timestamp)
        due_max: Upper bound for task's due date (RFC 3339 timestamp)
        max_results: Maximum number of tasks to return
    """
    try:
        service = auth.get_tasks_service()
        
        results = service.tasks().list(
            tasklist=task_list_id,
            showCompleted=show_completed,
            showHidden=show_hidden,
            dueMin=due_min,
            dueMax=due_max,
            maxResults=max_results
        ).execute()
        
        tasks = results.get('items', [])
        
        return json.dumps({
            "success": True,
            "tasks": tasks,
            "count": len(tasks)
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="get_task")
async def get_task(task_list_id: str, task_id: str) -> str:
    """Get a specific Google Task"""
    try:
        service = auth.get_tasks_service()
        
        task = service.tasks().get(
            tasklist=task_list_id,
            task=task_id
        ).execute()
        
        return json.dumps({
            "success": True,
            "task": task
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="create_task")
async def create_task(
    title: str,
    task_list_id: str = "@default",
    notes: str = None,
    due: str = None,
    parent: str = None
) -> str:
    """
    Create a new Google Task.
    
    Args:
        title: Task title
        task_list_id: ID of task list (use '@default' for default list)
        notes: Task notes/description
        due: Due date (RFC 3339 timestamp, e.g., '2025-11-07T00:00:00Z')
        parent: Parent task ID (for subtasks)
    """
    try:
        service = auth.get_tasks_service()
        
        task_body = {'title': title}
        if notes:
            task_body['notes'] = notes
        if due:
            task_body['due'] = due
        if parent:
            task_body['parent'] = parent
        
        task = service.tasks().insert(
            tasklist=task_list_id,
            body=task_body
        ).execute()
        
        return json.dumps({
            "success": True,
            "task": task
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="update_task")
async def update_task(
    task_list_id: str,
    task_id: str,
    title: str = None,
    notes: str = None,
    due: str = None,
    status: str = None
) -> str:
    """
    Update a Google Task.
    
    Args:
        task_list_id: ID of task list
        task_id: ID of task to update
        title: New title
        notes: New notes
        due: New due date (RFC 3339 timestamp)
        status: 'needsAction' or 'completed'
    """
    try:
        service = auth.get_tasks_service()
        
        # Get current task
        task = service.tasks().get(
            tasklist=task_list_id,
            task=task_id
        ).execute()
        
        # Update fields
        if title:
            task['title'] = title
        if notes is not None:  # Allow empty string to clear notes
            task['notes'] = notes
        if due:
            task['due'] = due
        if status:
            task['status'] = status
        
        updated_task = service.tasks().update(
            tasklist=task_list_id,
            task=task_id,
            body=task
        ).execute()
        
        return json.dumps({
            "success": True,
            "task": updated_task
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="complete_task")
async def complete_task(task_list_id: str, task_id: str) -> str:
    """Mark a Google Task as completed"""
    try:
        service = auth.get_tasks_service()
        
        task = service.tasks().get(
            tasklist=task_list_id,
            task=task_id
        ).execute()
        
        task['status'] = 'completed'
        
        updated_task = service.tasks().update(
            tasklist=task_list_id,
            task=task_id,
            body=task
        ).execute()
        
        return json.dumps({
            "success": True,
            "task": updated_task
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="delete_task")
async def delete_task(task_list_id: str, task_id: str) -> str:
    """Delete a Google Task"""
    try:
        service = auth.get_tasks_service()
        
        service.tasks().delete(
            tasklist=task_list_id,
            task=task_id
        ).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Task {task_id} deleted"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="clear_completed_tasks")
async def clear_completed_tasks(task_list_id: str = "@default") -> str:
    """Clear all completed tasks from a task list"""
    try:
        service = auth.get_tasks_service()
        
        service.tasks().clear(tasklist=task_list_id).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Cleared completed tasks from list {task_list_id}"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GOOGLE KEEP TOOLS
# ============================================================================

# @mcp.tool(name="list_keep_notes")
# async def list_keep_notes(
#     page_size: int = 50,
#     page_token: str = None,
#     filter_query: str = None
# ) -> str:
#     """
#     List Google Keep notes.
    
#     Args:
#         page_size: Number of notes to return (max 100)
#         page_token: Token for pagination
#         filter_query: Optional filter (e.g., "trashed=true", "title:groceries")
#     """
#     try:
#         service = auth.get_keep_service()
        
#         params = {
#             'pageSize': min(page_size, 100)
#         }
#         if page_token:
#             params['pageToken'] = page_token
#         if filter_query:
#             params['filter'] = filter_query
        
#         results = service.notes().list(**params).execute()
        
#         return json.dumps({
#             "success": True,
#             "notes": results.get('notes', []),
#             "nextPageToken": results.get('nextPageToken')
#         }, indent=2)
#     except Exception as e:
#         return json.dumps({"success": False, "error": str(e)}, indent=2)


# @mcp.tool(name="get_keep_note")
# async def get_keep_note(note_id: str) -> str:
#     """Get a specific Google Keep note by ID"""
#     try:
#         service = auth.get_keep_service()
        
#         note = service.notes().get(name=f"notes/{note_id}").execute()
        
#         return json.dumps({
#             "success": True,
#             "note": note
#         }, indent=2)
#     except Exception as e:
#         return json.dumps({"success": False, "error": str(e)}, indent=2)


# @mcp.tool(name="create_keep_note")
# async def create_keep_note(
#     title: str = "",
#     body: str = "",
# ) -> str:
#     """
#     Create a new Google Keep note.
    
#     Args:
#         title: Note title
#         body: Note body text
#     """
#     try:
#         service = auth.get_keep_service()
        
#         note_body = {}
        
#         if title:
#             note_body['title'] = title
        
#         if body:
#             note_body['body'] = {'text': {'text': body}}
        
#         note = service.notes().create(body=note_body).execute()
        
#         return json.dumps({
#             "success": True,
#             "note": note
#         }, indent=2)
#     except Exception as e:
#         return json.dumps({"success": False, "error": str(e)}, indent=2)


# @mcp.tool(name="create_keep_list")
# async def create_keep_list(
#     title: str,
#     items: List[Dict[str, Any]]
# ) -> str:
#     """
#     Create a Google Keep list note.
    
#     Args:
#         title: List title
#         items: List of items, each with 'text' and optionally 'checked' (bool)
        
#     Example items:
#     [
#         {"text": "Milk", "checked": False},
#         {"text": "Eggs", "checked": True},
#         {"text": "Bread", "checked": False}
#     ]
#     """
#     try:
#         service = auth.get_keep_service()
        
#         list_items = []
#         for item in items:
#             list_item = {
#                 'text': {'text': item['text']},
#                 'checked': item.get('checked', False)
#             }
#             list_items.append(list_item)
        
#         note_body = {
#             'title': title,
#             'body': {
#                 'list': {
#                     'listItems': list_items
#                 }
#             }
#         }
        
#         note = service.notes().create(body=note_body).execute()
        
#         return json.dumps({
#             "success": True,
#             "note": note
#         }, indent=2)
#     except Exception as e:
#         return json.dumps({"success": False, "error": str(e)}, indent=2)


# @mcp.tool(name="update_keep_list_item")
# async def update_keep_list_item(
#     note_id: str,
#     item_id: str,
#     checked: bool
# ) -> str:
#     """
#     Check or uncheck an item in a Keep list.
    
#     Args:
#         note_id: ID of the note containing the list
#         item_id: ID of the list item to update
#         checked: True to check, False to uncheck
#     """
#     try:
#         service = auth.get_keep_service()
        
#         # Get current note
#         note = service.notes().get(name=f"notes/{note_id}").execute()
        
#         # Find and update the item
#         if 'body' in note and 'list' in note['body']:
#             for item in note['body']['list'].get('listItems', []):
#                 if item.get('id') == item_id:
#                     item['checked'] = checked
#                     break
        
#         # Update the note
#         updated_note = service.notes().patch(
#             name=f"notes/{note_id}",
#             body=note
#         ).execute()
        
#         return json.dumps({
#             "success": True,
#             "note": updated_note
#         }, indent=2)
#     except Exception as e:
#         return json.dumps({"success": False, "error": str(e)}, indent=2)


# @mcp.tool(name="delete_keep_note")
# async def delete_keep_note(note_id: str) -> str:
#     """Delete a Google Keep note (moves to trash)"""
#     try:
#         service = auth.get_keep_service()
        
#         service.notes().delete(name=f"notes/{note_id}").execute()
        
#         return json.dumps({
#             "success": True,
#             "message": f"Note {note_id} deleted"
#         }, indent=2)
#     except Exception as e:
#         return json.dumps({"success": False, "error": str(e)}, indent=2)

# ============================================================================
# GOOGLE DRIVE TOOLS (NEW - Basic)
# ============================================================================

@mcp.tool(name="search_drive")
async def search_drive(
    query: str,
    max_results: int = 10,
    page_token: str = None
) -> str:
    """
    Search Google Drive files.
    
    Query examples:
    - "name contains 'budget'"
    - "mimeType='application/vnd.google-apps.spreadsheet'"
    - "modifiedTime > '2025-10-01T00:00:00'"
    """
    try:
        service = auth.get_drive_service()
        
        results = service.files().list(
            q=query,
            pageSize=max_results,
            pageToken=page_token,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, webViewLink)"
        ).execute()
        
        return json.dumps({
            "success": True,
            "files": results.get('files', []),
            "nextPageToken": results.get('nextPageToken')
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="get_drive_file")
async def get_drive_file(file_id: str) -> str:
    """Get metadata for a Drive file"""
    try:
        service = auth.get_drive_service()
        
        file = service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, modifiedTime, webViewLink, parents"
        ).execute()
        
        return json.dumps({"success": True, "file": file}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ============================================================================
# OAUTH WEB ENDPOINTS
# ============================================================================

from fastapi import Request
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware
from fastapi import FastAPI

fastapi_app = FastAPI()

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@fastapi_app.get("/oauth/start")
async def start_oauth(request: Request):
    """Start OAuth flow"""
    try:
        base_url = str(request.base_url).rstrip('/')
        if base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://', 1)
        redirect_uri = f"{base_url}/oauth/callback"
        
        flow = create_oauth_flow(redirect_uri)
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            prompt='consent',
            include_granted_scopes='true'
        )
        
        return RedirectResponse(auth_url)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@fastapi_app.get("/oauth/callback")
async def oauth_callback(request: Request):
    """Handle OAuth callback"""
    try:
        code = request.query_params.get('code')
        if not code:
            return JSONResponse({"error": "No code provided"}, status_code=400)
        
        base_url = str(request.base_url).rstrip('/')
        if base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://', 1)
        redirect_uri = f"{base_url}/oauth/callback"
        
        flow = create_oauth_flow(redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        token_json = creds.to_json()
        print("\n" + "="*60)
        print("✅ AUTHORIZATION SUCCESSFUL!")
        print("="*60)
        print("\nVariable name: GOOGLE_TOKEN_JSON")
        print("\nToken JSON:")
        print(token_json)
        print("\n" + "="*60)
        
        return JSONResponse({
            "success": True,
            "message": "Authorization successful! Check logs for GOOGLE_TOKEN_JSON",
            "instructions": "Copy token from logs and add to Railway environment variables"
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@fastapi_app.get("/health")
async def health_check():
    """Health check endpoint"""
    return JSONResponse({
        "status": "ok",
        "service": "Daily Tracking MCP",
        "authenticated": auth.is_authenticated()
    })


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
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages", app=sse.handle_post_message),
            Route("/oauth/start", endpoint=start_oauth, methods=["GET"]),
            Route("/oauth/callback", endpoint=oauth_callback, methods=["GET"]),
            Route("/health", endpoint=health_check, methods=["GET"]),
        ]
    )
    
    print(f"Starting server on port {port}")
    print(f"OAuth available at: /oauth/start")
    print(f"Authenticated: {auth.is_authenticated()}")
    
    uvicorn.run(app, host="0.0.0.0", port=port)
