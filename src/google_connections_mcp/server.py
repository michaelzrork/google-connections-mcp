#!/usr/bin/env python3
"""
Google Connections MCP Server
Generic Google Workspace API access with OAuth
Supports Sheets, Calendar, Gmail, Drive, and Tasks
"""

import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict
import pandas as pd

from google_connections_mcp.auth_manager import get_auth_manager, create_oauth_flow

# Initialize MCP server
mcp = FastMCP("Google Connections MCP")

# Get auth manager
auth = get_auth_manager()

# ============================================================================
# GET TIME TOOL
# ============================================================================

@mcp.tool(
    name="get_time",
    description="Returns the current date, time, and day of week for the specified timezone. Requires IANA timezone format (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo', 'UTC'). If user's timezone is unknown, ask them."
)
async def get_time(timezone: str) -> dict:
    now = datetime.now(ZoneInfo(timezone))
    return {
        "dayOfWeek": now.strftime("%A"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%I:%M:%S %p"),
        "timezone": timezone,
        "isoFormat": now.isoformat()
    }

# ============================================================================
# GOOGLE SHEETS - INTERNAL HELPERS
# ============================================================================

def _col_letter(col_num: int) -> str:
    """Convert 1-indexed column number to letter (1 -> A, 27 -> AA)."""
    result = ""
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _col_number(letter: str) -> int:
    """Convert column letter to 1-indexed number (A -> 1, AA -> 27)."""
    result = 0
    for ch in letter.upper():
        result = result * 26 + (ord(ch) - 64)
    return result


def _header_to_column_letter(worksheet, header_name: str) -> str:
    """Look up a header name in row 1 and return its column letter.
    Raises ValueError if header not found.
    """
    headers = worksheet.row_values(1)
    try:
        idx = headers.index(header_name)
    except ValueError:
        available = ', '.join(headers) if headers else 'none'
        raise ValueError(f"Header '{header_name}' not found. Available: {available}")
    return _col_letter(idx + 1)


def _resolve_column(worksheet, column_ref: str, mode: str) -> str:
    """Resolve a column reference to a letter.
    mode='header': looks up header_name -> letter via row 1.
    mode='letter': passes through as-is (uppercased).
    """
    if mode == 'header':
        return _header_to_column_letter(worksheet, column_ref)
    elif mode == 'letter':
        return column_ref.upper()
    else:
        raise ValueError(f"Invalid mode '{mode}'. Must be 'header' or 'letter'.")


def _get_worksheet(spreadsheet_id: str, worksheet_name: str):
    """Get a gspread worksheet object."""
    sheets_client = auth.get_sheets_client()
    spreadsheet = sheets_client.open_by_key(spreadsheet_id)
    return spreadsheet.worksheet(worksheet_name)


def _find_rows_by_value(worksheet, column_letter: str, value: str) -> List[int]:
    """Find all row numbers where the given column has the given value.
    Returns list of 1-indexed row numbers. Skips row 1 (header).
    """
    col_num = _col_number(column_letter)
    col_values = worksheet.col_values(col_num)
    matches = []
    for i, cell_val in enumerate(col_values):
        if i == 0:
            continue
        if cell_val == value:
            matches.append(i + 1)
    return matches


def _resolve_row_id(worksheet, obj: Dict[str, Any], mode: str) -> int:
    """Resolve a row from an object that has either 'row' or unique_id fields.
    Returns row number. Raises ValueError on failure.
    """
    has_row = 'row' in obj
    has_uid = 'unique_id_column' in obj and 'unique_id_value' in obj

    if has_row and has_uid:
        raise ValueError("Cannot provide both 'row' and 'unique_id_column'/'unique_id_value'.")
    if not has_row and not has_uid:
        raise ValueError("Must provide either 'row' or 'unique_id_column' + 'unique_id_value'.")

    if has_row:
        row = obj['row']
        if not isinstance(row, int) or row < 1:
            raise ValueError(f"Row must be an integer >= 1, got {row}")
        return row

    col_letter = _resolve_column(worksheet, obj['unique_id_column'], mode)
    matches = _find_rows_by_value(worksheet, col_letter, obj['unique_id_value'])

    if len(matches) == 0:
        raise ValueError(f"No match for {obj['unique_id_column']}='{obj['unique_id_value']}'")
    if len(matches) > 1:
        raise ValueError(
            f"Multiple matches for {obj['unique_id_column']}='{obj['unique_id_value']}': "
            f"rows {matches}. Use query_sheet or get_row to identify the correct row, "
            f"then retry with explicit row number."
        )
    return matches[0]


def _row_to_letter_dict(row_data: List) -> Dict[str, str]:
    """Convert a list of cell values to a dict keyed by column letters."""
    return {_col_letter(i + 1): val for i, val in enumerate(row_data)}


def _batch_update_cells(worksheet, updates: Dict[str, Any]) -> None:
    """Batch update cells - single API call for all updates.

    Args:
        worksheet: gspread worksheet object
        updates: dict of {cell_ref: value}, e.g. {'A1': 'hello', 'B2': 42}
    """
    if not updates:
        return
    batch_data = [
        {'range': cell_ref, 'values': [[value]]}
        for cell_ref, value in updates.items()
    ]
    worksheet.batch_update(batch_data, value_input_option='USER_ENTERED')


def parse_datetime(value):
    """Parse a value as datetime, supporting multiple formats."""
    if pd.isna(value) or value == '':
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        formats = [
            '%m/%d/%Y',
            '%Y-%m-%d',
            '%m/%d/%Y %I:%M %p',
            '%Y-%m-%d %H:%M:%S',
            '%m/%d/%Y %H:%M:%S',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


# ============================================================================
# GOOGLE SHEETS - TOOLS
# ============================================================================

# --- query_sheet ---

class QuerySheetInput(BaseModel):
    """Input for querying a sheet with filters."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    mode: str = Field(default="header", description="'header' or 'letter'")
    filters: List[Dict[str, Any]] = Field(default=[])
    return_columns: Optional[List[str]] = Field(default=None)
    limit: Optional[int] = Field(default=None)
    sort_by: Optional[str] = Field(default=None)
    sort_desc: bool = Field(default=False)

@mcp.tool(name="query_sheet")
async def query_sheet(params: QuerySheetInput) -> str:
    """
    Query a Google Sheet with flexible filtering. Returns matching rows with _row_number.

    Results always use column letters as keys (e.g. "A", "B").

    Filters support:
    - {'field': 'Company', 'operator': '==', 'value': 'Acme'}  (mode: header)
    - {'field': 'A', 'operator': '==', 'value': 'Acme'}  (mode: letter)

    Operators: ==, !=, >, <, >=, <=, in, not in, contains, not contains, is_null, not_null
    Date/time operators (==, !=, >, <, >=, <=) automatically parse datetime values.

    IMPORTANT for date filtering:
    - Use == with a FULL date string (e.g. '1/27/2026' or '2026-01-27') for exact date matching.
    - Do NOT use 'contains' for dates — it does substring matching (e.g. '1/27' matches '11/27/2025').
    - Supported date formats: m/d/YYYY, YYYY-MM-DD, m/d/YYYY h:MM AM/PM, YYYY-MM-DD HH:MM:SS.
    - The filter value format must match what's stored in the sheet cells.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)
        all_data = ws.get_all_values()

        if not all_data:
            return json.dumps({"success": True, "data": [], "count": 0}, indent=2)

        headers = all_data[0]
        rows = all_data[1:]

        # Build header-to-letter mapping for header mode
        if params.mode == 'header':
            col_map = {}
            for i, h in enumerate(headers):
                col_map[h] = _col_letter(i + 1)
        else:
            col_map = None

        # DataFrame with column letters as column names
        letter_cols = [_col_letter(i + 1) for i in range(len(headers))]
        df = pd.DataFrame(rows, columns=letter_cols)
        df['_row_number'] = range(2, len(rows) + 2)

        # Apply filters
        for filter_def in params.filters:
            field = filter_def['field']
            operator = filter_def['operator']
            value = filter_def.get('value')

            # Resolve field to column letter
            if params.mode == 'header':
                if field not in col_map:
                    continue
                col = col_map[field]
            else:
                col = field.upper()

            if col not in df.columns:
                continue

            if operator in ['>', '<', '>=', '<=', '==', '!=']:
                filter_dt = parse_datetime(value)
                if filter_dt is not None:
                    df_dts = pd.Series([parse_datetime(val) for val in df[col]], index=df.index)
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

            if operator == '==':
                df = df[df[col] == value]
            elif operator == '!=':
                df = df[df[col] != value]
            elif operator == '>':
                df = df[df[col] > value]
            elif operator == '<':
                df = df[df[col] < value]
            elif operator == '>=':
                df = df[df[col] >= value]
            elif operator == '<=':
                df = df[df[col] <= value]
            elif operator == 'in':
                df = df[df[col].isin(value)]
            elif operator == 'not in':
                df = df[~df[col].isin(value)]
            elif operator == 'contains':
                df = df[df[col].str.contains(value, case=False, na=False)]
            elif operator == 'not contains':
                df = df[~df[col].str.contains(value, case=False, na=False)]
            elif operator == 'is_null':
                df = df[df[col].isna() | (df[col] == '')]
            elif operator == 'not_null':
                df = df[df[col].notna() & (df[col] != '')]

        # return_columns
        if params.return_columns:
            if params.mode == 'header':
                resolved = [col_map[c] for c in params.return_columns if c in col_map]
            else:
                resolved = [c.upper() for c in params.return_columns]
            resolved.append('_row_number')
            available = [c for c in resolved if c in df.columns]
            if available:
                df = df[available]

        if params.sort_by:
            sort_col = col_map[params.sort_by] if params.mode == 'header' and col_map and params.sort_by in col_map else params.sort_by
            if sort_col in df.columns:
                df = df.sort_values(by=sort_col, ascending=not params.sort_desc)

        if params.limit:
            df = df.head(params.limit)

        result = df.to_dict('records')

        return json.dumps({"success": True, "data": result, "count": len(result)}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- find_row_by_unique_id ---

class FindRowByUniqueIdInput(BaseModel):
    """Input for finding rows by unique ID lookups."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    mode: str = Field(default="header", description="'header' or 'letter'")
    lookups: List[Dict[str, str]] = Field(..., min_length=1, description="Array of {column, value}")

@mcp.tool(name="find_row_by_unique_id")
async def find_row_by_unique_id(params: FindRowByUniqueIdInput) -> str:
    """
    Look up row number(s) by searching for a value in a column.
    Intended for unique values but returns all matches.

    Each lookup: {"column": "ID", "value": "abc123"}

    Response per lookup:
    - 1 match: {"success": true, "row_number": 23}
    - Multiple: {"success": false, "error": "multiple_matches", "row_numbers": [6, 8]}
    - None: {"success": false, "error": "no_match"}
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        results = []
        for lookup in params.lookups:
            column = lookup['column']
            value = lookup['value']

            letter = _resolve_column(ws, column, params.mode)
            matches = _find_rows_by_value(ws, letter, value)

            if len(matches) == 1:
                results.append({"column": column, "value": value, "success": True, "row_number": matches[0]})
            elif len(matches) > 1:
                results.append({"column": column, "value": value, "success": False, "error": "multiple_matches", "row_numbers": matches})
            else:
                results.append({"column": column, "value": value, "success": False, "error": "no_match"})

        return json.dumps({"results": results}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- get_row ---

class GetRowInput(BaseModel):
    """Input for getting rows."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    unique_id_mode: Optional[str] = Field(default="header", description="'header' or 'letter' for unique_id lookups")
    rows: List[Dict[str, Any]] = Field(..., min_length=1, description="Array of {row} or {unique_id_column, unique_id_value}")

@mcp.tool(name="get_row")
async def get_row(params: GetRowInput) -> str:
    """
    Get one or more complete rows by row number or unique_id lookup.
    Returns data with column letters as keys.

    Each entry: {"row": 6} or {"unique_id_column": "Company", "unique_id_value": "Acme"}
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)
        all_data = ws.get_all_values()

        fetched = []
        skipped = []

        for obj in params.rows:
            try:
                mode = params.unique_id_mode or 'header'
                row_num = _resolve_row_id(ws, obj, mode)

                idx = row_num - 1
                if idx < 0 or idx >= len(all_data):
                    skipped.append({**obj, "reason": f"Row {row_num} out of range (sheet has {len(all_data)} rows)"})
                    continue

                row_data = _row_to_letter_dict(all_data[idx])
                row_data['_row_number'] = row_num
                fetched.append(row_data)

            except ValueError as ve:
                skipped.append({**obj, "reason": str(ve)})

        return json.dumps({"success": True, "rows": fetched, "skipped": skipped}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- get_cell ---

class GetCellInput(BaseModel):
    """Input for getting cells by A1 notation."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    cells: List[str] = Field(..., min_length=1, description="Array of A1 cell refs, e.g. ['A1', 'B5']")

@mcp.tool(name="get_cell")
async def get_cell(params: GetCellInput) -> str:
    """Get one or more cell values by A1 notation."""
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        result = {}
        for cell_ref in params.cells:
            try:
                val = ws.acell(cell_ref).value
                result[cell_ref] = val if val is not None else ""
            except Exception:
                result[cell_ref] = ""

        return json.dumps({"success": True, "cells": result}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- get_column ---

class GetColumnInput(BaseModel):
    """Input for getting all values in a column."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    column: str = Field(..., min_length=1, description="Column header name or letter")
    mode: str = Field(default="header", description="'header' or 'letter'")
    skip_header: bool = Field(default=True, description="Skip row 1 (header row)")
    skip_empty: bool = Field(default=False, description="Exclude empty cells from results")

@mcp.tool(name="get_column")
async def get_column(params: GetColumnInput) -> str:
    """
    Get all values in a column. Returns column letter and values with row numbers.

    Useful for seeing all values in a column, then using update_cells to modify them.
    Example: get_column returns column "B", then update with {"B2": "new", "B5": "other"}
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        # Resolve column to letter
        col_letter = _resolve_column(ws, params.column, params.mode)
        col_num = _col_number(col_letter)

        # Get all values in the column
        col_values = ws.col_values(col_num)

        # Build result with row numbers
        values = []
        start_row = 2 if params.skip_header else 1

        for i, val in enumerate(col_values):
            row_num = i + 1
            if row_num < start_row:
                continue
            if params.skip_empty and (val is None or val == ""):
                continue
            values.append({"row": row_num, "value": val if val is not None else ""})

        return json.dumps({
            "success": True,
            "column": col_letter,
            "values": values,
            "count": len(values)
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- update_cells ---

class UpdateCellsInput(BaseModel):
    """Input for updating cells by A1 notation."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    updates: Dict[str, Any] = Field(..., description="Object of {cell_ref: value}, e.g. {'A16': 'hello', 'C16': 42}")

@mcp.tool(name="update_cells")
async def update_cells(params: UpdateCellsInput) -> str:
    """
    Update one or more cells by A1 notation. Core write primitive.
    Uses batch update for efficiency - single API call for all cells.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)
        _batch_update_cells(ws, params.updates)
        return json.dumps({"success": True, "updated_cells": list(params.updates.keys())}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- update_row ---

class UpdateRowInput(BaseModel):
    """Input for updating rows."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    mode: str = Field(default="header", description="'header' or 'letter'")
    updates: List[Dict[str, Any]] = Field(..., min_length=1)

@mcp.tool(name="update_row")
async def update_row(params: UpdateRowInput) -> str:
    """
    Update one or more existing rows. Each update object must have either
    'row' (int) or 'unique_id_column' + 'unique_id_value'. Remaining keys
    are column references (header names or letters based on mode) mapped to values.

    Uses batch update for efficiency - all cells updated in a single API call.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        reserved_keys = {'row', 'unique_id_column', 'unique_id_value'}
        updated = []
        skipped = []
        cell_updates = {}  # Collect all updates for single batch call

        for obj in params.updates:
            try:
                row_num = _resolve_row_id(ws, obj, params.mode)

                columns_updated = []
                for key, value in obj.items():
                    if key in reserved_keys:
                        continue
                    letter = _resolve_column(ws, key, params.mode)
                    cell_updates[f"{letter}{row_num}"] = value
                    columns_updated.append(key)

                updated.append({"row": row_num, "columns_updated": columns_updated})

            except ValueError as ve:
                skip_entry = {"reason": str(ve)}
                if 'unique_id_column' in obj:
                    skip_entry['unique_id_column'] = obj['unique_id_column']
                    skip_entry['unique_id_value'] = obj.get('unique_id_value')
                if 'row' in obj:
                    skip_entry['row'] = obj['row']
                skipped.append(skip_entry)

        _batch_update_cells(ws, cell_updates)

        return json.dumps({"success": True, "updated": updated, "skipped": skipped}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- add_row ---

class AddRowInput(BaseModel):
    """Input for adding rows."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    mode: str = Field(default="header", description="'header' or 'letter'")
    rows: List[Dict[str, Any]] = Field(..., min_length=1)

@mcp.tool(name="add_row")
async def add_row(params: AddRowInput) -> str:
    """
    Add one or more new rows to the next empty row(s).
    Each object's keys are column references (header names or letters based on mode).
    Always appends — does not accept row numbers.

    Uses batch update for efficiency - all cells updated in a single API call.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        all_data = ws.get_all_values()
        next_row = len(all_data) + 1

        added = []
        cell_updates = {}  # Collect all updates for single batch call

        for row_obj in params.rows:
            for key, value in row_obj.items():
                letter = _resolve_column(ws, key, params.mode)
                cell_updates[f"{letter}{next_row}"] = value

            added.append({"row": next_row})
            next_row += 1

        _batch_update_cells(ws, cell_updates)

        return json.dumps({"success": True, "added": added}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- delete_row ---

class DeleteRowInput(BaseModel):
    """Input for deleting rows."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    unique_id_mode: Optional[str] = Field(default="header", description="'header' or 'letter' for unique_id lookups")
    deletions: List[Dict[str, Any]] = Field(..., min_length=1, description="Array of {row} or {unique_id_column, unique_id_value}")

@mcp.tool(name="delete_row")
async def delete_row(params: DeleteRowInput) -> str:
    """
    Delete one or more rows by row number or unique_id lookup.
    Deletes highest row numbers first to avoid row-shifting issues.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        resolved = []
        skipped = []
        mode = params.unique_id_mode or 'header'

        for obj in params.deletions:
            try:
                row_num = _resolve_row_id(ws, obj, mode)
                resolved.append(row_num)
            except ValueError as ve:
                skip_entry = {"reason": str(ve)}
                if 'unique_id_column' in obj:
                    skip_entry['unique_id_column'] = obj['unique_id_column']
                    skip_entry['unique_id_value'] = obj.get('unique_id_value')
                if 'row' in obj:
                    skip_entry['row'] = obj['row']
                skipped.append(skip_entry)

        for rn in sorted(resolved, reverse=True):
            ws.delete_rows(rn)

        return json.dumps({"success": True, "deleted": sorted(resolved, reverse=True), "skipped": skipped}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- add_column ---

class AddColumnInput(BaseModel):
    """Input for adding a column."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    header: str = Field(..., min_length=1)
    column: Optional[str] = Field(default=None, description="Column letter (e.g. 'N'). Auto-detects next empty if omitted.")

@mcp.tool(name="add_column")
async def add_column(params: AddColumnInput) -> str:
    """
    Add a new column with a header. Auto-detects next empty column if not specified.
    Writes the header to row 1 of the target column.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        if params.column:
            target = params.column.upper()
        else:
            headers = ws.row_values(1)
            target = _col_letter(len(headers) + 1)

        ws.update(f"{target}1", [[params.header]], value_input_option='USER_ENTERED')

        return json.dumps({"success": True, "column": target, "header": params.header}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- delete_column ---

class DeleteColumnInput(BaseModel):
    """Input for deleting a column."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    mode: str = Field(default="header", description="'header' or 'letter'")
    column: str = Field(..., min_length=1, description="Header name or column letter")

@mcp.tool(name="delete_column")
async def delete_column(params: DeleteColumnInput) -> str:
    """Delete a column by header name or letter."""
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        letter = _resolve_column(ws, params.column, params.mode)
        col_num = _col_number(letter)
        ws.delete_columns(col_num)

        return json.dumps({"success": True, "deleted_column": letter}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- create_spreadsheet ---

class CreateSpreadsheetInput(BaseModel):
    """Input for creating a spreadsheet."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    title: str = Field(..., min_length=1)
    worksheets: Optional[List[str]] = Field(default=None, description="Optional list of worksheet names to create")

@mcp.tool(name="create_spreadsheet")
async def create_spreadsheet(params: CreateSpreadsheetInput) -> str:
    """Create a new Google Sheets document."""
    try:
        sheets_client = auth.get_sheets_client()
        spreadsheet = sheets_client.create(params.title)

        if params.worksheets:
            default_ws = spreadsheet.sheet1
            default_ws.update_title(params.worksheets[0])
            for ws_name in params.worksheets[1:]:
                spreadsheet.add_worksheet(title=ws_name, rows=1000, cols=26)

        return json.dumps({
            "success": True,
            "spreadsheet_id": spreadsheet.id,
            "title": params.title,
            "worksheets": params.worksheets or ["Sheet1"],
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}"
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- add_worksheet ---

@mcp.tool(name="add_worksheet")
async def add_worksheet(spreadsheet_id: str, title: str) -> str:
    """Add a new worksheet (tab) to an existing spreadsheet."""
    try:
        sheets_client = auth.get_sheets_client()
        spreadsheet = sheets_client.open_by_key(spreadsheet_id)
        spreadsheet.add_worksheet(title=title, rows=1000, cols=26)

        return json.dumps({"success": True, "worksheet_name": title}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- delete_worksheet ---

@mcp.tool(name="delete_worksheet")
async def delete_worksheet(spreadsheet_id: str, worksheet_name: str) -> str:
    """Delete a worksheet (tab) from a spreadsheet."""
    try:
        sheets_client = auth.get_sheets_client()
        spreadsheet = sheets_client.open_by_key(spreadsheet_id)
        ws = spreadsheet.worksheet(worksheet_name)
        spreadsheet.del_worksheet(ws)

        return json.dumps({"success": True, "deleted_worksheet": worksheet_name}, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- list_worksheets ---

@mcp.tool(name="list_worksheets")
async def list_worksheets(spreadsheet_id: str) -> str:
    """List all worksheets (tabs) in a spreadsheet with their properties."""
    try:
        sheets_client = auth.get_sheets_client()
        spreadsheet = sheets_client.open_by_key(spreadsheet_id)

        worksheets = []
        for ws in spreadsheet.worksheets():
            worksheets.append({
                "title": ws.title,
                "id": ws.id,
                "index": ws.index,
                "row_count": ws.row_count,
                "col_count": ws.col_count
            })

        return json.dumps({
            "success": True,
            "spreadsheet_id": spreadsheet_id,
            "worksheets": worksheets,
            "count": len(worksheets)
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- rename_worksheet ---

@mcp.tool(name="rename_worksheet")
async def rename_worksheet(spreadsheet_id: str, current_name: str, new_name: str) -> str:
    """Rename a worksheet (tab) in a spreadsheet."""
    try:
        sheets_client = auth.get_sheets_client()
        spreadsheet = sheets_client.open_by_key(spreadsheet_id)
        ws = spreadsheet.worksheet(current_name)
        ws.update_title(new_name)

        return json.dumps({
            "success": True,
            "old_name": current_name,
            "new_name": new_name
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- get_spreadsheet_info ---

@mcp.tool(name="get_spreadsheet_info")
async def get_spreadsheet_info(spreadsheet_id: str) -> str:
    """Get metadata about a spreadsheet including title, URL, and all worksheets."""
    try:
        sheets_client = auth.get_sheets_client()
        spreadsheet = sheets_client.open_by_key(spreadsheet_id)

        worksheets = []
        for ws in spreadsheet.worksheets():
            worksheets.append({
                "title": ws.title,
                "id": ws.id,
                "index": ws.index,
                "row_count": ws.row_count,
                "col_count": ws.col_count
            })

        return json.dumps({
            "success": True,
            "spreadsheet_id": spreadsheet.id,
            "title": spreadsheet.title,
            "url": spreadsheet.url,
            "worksheets": worksheets,
            "worksheet_count": len(worksheets)
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# --- clear_range ---

class ClearRangeInput(BaseModel):
    """Input for clearing a range of cells."""
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

    spreadsheet_id: str = Field(..., min_length=1)
    worksheet_name: str = Field(..., min_length=1)
    range: str = Field(..., min_length=1, description="A1 notation range, e.g. 'A2:D10' or 'B:B' for entire column")

@mcp.tool(name="clear_range")
async def clear_range(params: ClearRangeInput) -> str:
    """
    Clear cell contents in a range without deleting rows/columns.
    Removes values but preserves formatting. Use A1 notation for the range.

    Examples: 'A2:D10', 'B:B' (entire column), '2:5' (entire rows 2-5)
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)
        ws.batch_clear([params.range])

        return json.dumps({
            "success": True,
            "cleared_range": params.range
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


class SortWorksheetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spreadsheet_id: str = Field(description="The spreadsheet ID from the URL")
    worksheet_name: str = Field(description="Name of the worksheet/tab")
    sort_column: str = Field(description="Column to sort by (letter like 'A' or header name)")
    ascending: bool = Field(default=True, description="Sort ascending (True) or descending (False)")
    has_header: bool = Field(default=True, description="If True, first row is preserved as header")
    mode: str = Field(default="header", description="'header' to use column names, 'letter' to use column letters")


@mcp.tool(name="sort_worksheet")
async def sort_worksheet(params: SortWorksheetParams) -> str:
    """
    Sort an entire worksheet by a column.
    The header row (row 1) is preserved if has_header is True.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)

        # Resolve column to letter
        if params.mode == "header":
            headers = ws.row_values(1)
            if params.sort_column in headers:
                col_idx = headers.index(params.sort_column) + 1
                col_letter = _col_letter(col_idx)
            else:
                return json.dumps({"success": False, "error": f"Column '{params.sort_column}' not found in headers"}, indent=2)
        else:
            col_letter = params.sort_column.upper()

        col_num = _col_number(col_letter)

        # Use gspread's sort method
        order = 'asc' if params.ascending else 'des'
        start_row = 2 if params.has_header else 1
        ws.sort((col_num, order), range=f"A{start_row}:{_col_letter(ws.col_count)}{ws.row_count}")

        return json.dumps({
            "success": True,
            "sorted_by": params.sort_column,
            "ascending": params.ascending,
            "header_preserved": params.has_header
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


class CopyWorksheetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_spreadsheet_id: str = Field(description="Source spreadsheet ID")
    source_worksheet_name: str = Field(description="Name of the worksheet to copy")
    destination_spreadsheet_id: str = Field(default=None, description="Destination spreadsheet ID (same spreadsheet if not specified)")
    new_worksheet_name: str = Field(default=None, description="Name for the copied worksheet (auto-generated if not specified)")


@mcp.tool(name="copy_worksheet")
async def copy_worksheet(params: CopyWorksheetParams) -> str:
    """
    Copy a worksheet to the same or a different spreadsheet.
    """
    try:
        sheets_client = auth.get_sheets_client()
        source_spreadsheet = sheets_client.open_by_key(params.source_spreadsheet_id)
        source_ws = source_spreadsheet.worksheet(params.source_worksheet_name)

        dest_spreadsheet_id = params.destination_spreadsheet_id or params.source_spreadsheet_id

        if dest_spreadsheet_id == params.source_spreadsheet_id:
            # Copy within same spreadsheet
            new_ws = source_spreadsheet.duplicate_sheet(
                source_ws.id,
                new_sheet_name=params.new_worksheet_name
            )
            return json.dumps({
                "success": True,
                "new_worksheet_name": new_ws.title,
                "new_worksheet_id": new_ws.id,
                "destination_spreadsheet_id": params.source_spreadsheet_id
            }, indent=2)
        else:
            # Copy to different spreadsheet
            new_ws = source_ws.copy_to(dest_spreadsheet_id)

            # Rename if specified
            if params.new_worksheet_name:
                dest_spreadsheet = sheets_client.open_by_key(dest_spreadsheet_id)
                # The copy_to returns basic info; we need to get the worksheet and rename
                copied_ws = dest_spreadsheet.get_worksheet_by_id(new_ws['sheetId'])
                copied_ws.update_title(params.new_worksheet_name)
                new_ws_name = params.new_worksheet_name
            else:
                new_ws_name = new_ws.get('title', 'Copy of ' + params.source_worksheet_name)

            return json.dumps({
                "success": True,
                "new_worksheet_name": new_ws_name,
                "new_worksheet_id": new_ws['sheetId'],
                "destination_spreadsheet_id": dest_spreadsheet_id
            }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


class MergeCellsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spreadsheet_id: str = Field(description="The spreadsheet ID from the URL")
    worksheet_name: str = Field(description="Name of the worksheet/tab")
    range: str = Field(description="Range to merge in A1 notation (e.g., 'A1:C1', 'B2:B5')")
    merge_type: str = Field(default="MERGE_ALL", description="'MERGE_ALL' (single cell), 'MERGE_COLUMNS' (merge within columns), 'MERGE_ROWS' (merge within rows)")


@mcp.tool(name="merge_cells")
async def merge_cells(params: MergeCellsParams) -> str:
    """
    Merge a range of cells into one.
    The value of the top-left cell is preserved.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)
        ws.merge_cells(params.range, merge_type=params.merge_type)

        return json.dumps({
            "success": True,
            "merged_range": params.range,
            "merge_type": params.merge_type
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


class UnmergeCellsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spreadsheet_id: str = Field(description="The spreadsheet ID from the URL")
    worksheet_name: str = Field(description="Name of the worksheet/tab")
    range: str = Field(description="Range to unmerge in A1 notation (e.g., 'A1:C1')")


@mcp.tool(name="unmerge_cells")
async def unmerge_cells(params: UnmergeCellsParams) -> str:
    """
    Unmerge previously merged cells.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)
        ws.unmerge_cells(params.range)

        return json.dumps({
            "success": True,
            "unmerged_range": params.range
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


class FreezeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spreadsheet_id: str = Field(description="The spreadsheet ID from the URL")
    worksheet_name: str = Field(description="Name of the worksheet/tab")
    rows: int = Field(default=0, description="Number of rows to freeze from the top (0 to unfreeze)")
    cols: int = Field(default=0, description="Number of columns to freeze from the left (0 to unfreeze)")


@mcp.tool(name="freeze_rows_columns")
async def freeze_rows_columns(params: FreezeParams) -> str:
    """
    Freeze rows and/or columns in a worksheet.
    Frozen rows/columns stay visible while scrolling.
    Set to 0 to unfreeze.
    """
    try:
        ws = _get_worksheet(params.spreadsheet_id, params.worksheet_name)
        ws.freeze(rows=params.rows, cols=params.cols)

        return json.dumps({
            "success": True,
            "frozen_rows": params.rows,
            "frozen_cols": params.cols
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
    reminders: dict = None,
    timezone: str = None
) -> str:
    """
    Create a calendar event.

    Args:
        timezone: IANA timezone (e.g., 'America/New_York', 'Europe/London', 'UTC').
                  If not provided, uses the calendar's default timezone.
    """
    try:
        service = auth.get_calendar_service()

        # Build start/end with optional timezone
        start_obj = {'dateTime': start_time}
        end_obj = {'dateTime': end_time}
        if timezone:
            start_obj['timeZone'] = timezone
            end_obj['timeZone'] = timezone

        event_body = {
            'summary': summary,
            'start': start_obj,
            'end': end_obj
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
    location: str = None,
    timezone: str = None
) -> str:
    """
    Update an existing calendar event.

    Args:
        timezone: IANA timezone for start/end times (e.g., 'America/New_York', 'UTC').
                  If not provided when updating times, preserves existing timezone.
    """
    try:
        service = auth.get_calendar_service()
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        if summary:
            event['summary'] = summary
        if start_time:
            start_obj = {'dateTime': start_time}
            if timezone:
                start_obj['timeZone'] = timezone
            elif 'timeZone' in event.get('start', {}):
                start_obj['timeZone'] = event['start']['timeZone']
            event['start'] = start_obj
        if end_time:
            end_obj = {'dateTime': end_time}
            if timezone:
                end_obj['timeZone'] = timezone
            elif 'timeZone' in event.get('end', {}):
                end_obj['timeZone'] = event['end']['timeZone']
            event['end'] = end_obj
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
# GMAIL TOOLS
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
    
    Common labels: INBOX, UNREAD, STARRED, IMPORTANT, SPAM, TRASH
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
    """Modify labels on multiple Gmail messages at once."""
    try:
        service = auth.get_gmail_service()
        
        body = {'ids': message_ids}
        if add_labels:
            body['addLabelIds'] = add_labels
        if remove_labels:
            body['removeLabelIds'] = remove_labels
        
        service.users().messages().batchModify(
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
    """List all Gmail labels"""
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
    """Create a new Gmail label."""
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


# Gmail helper functions
@mcp.tool(name="mark_gmail_read")
async def mark_gmail_read(message_ids: List[str]) -> str:
    """Mark one or more Gmail messages as read"""
    return await batch_modify_gmail(message_ids=message_ids, remove_labels=['UNREAD'])


@mcp.tool(name="mark_gmail_unread")
async def mark_gmail_unread(message_ids: List[str]) -> str:
    """Mark one or more Gmail messages as unread"""
    return await batch_modify_gmail(message_ids=message_ids, add_labels=['UNREAD'])


@mcp.tool(name="star_gmail")
async def star_gmail(message_ids: List[str]) -> str:
    """Star one or more Gmail messages"""
    return await batch_modify_gmail(message_ids=message_ids, add_labels=['STARRED'])


@mcp.tool(name="unstar_gmail")
async def unstar_gmail(message_ids: List[str]) -> str:
    """Remove star from one or more Gmail messages"""
    return await batch_modify_gmail(message_ids=message_ids, remove_labels=['STARRED'])


@mcp.tool(name="archive_gmail")
async def archive_gmail(message_ids: List[str]) -> str:
    """Archive one or more Gmail messages"""
    return await batch_modify_gmail(message_ids=message_ids, remove_labels=['INBOX'])


@mcp.tool(name="move_to_inbox")
async def move_to_inbox(message_ids: List[str]) -> str:
    """Move one or more Gmail messages to inbox"""
    return await batch_modify_gmail(message_ids=message_ids, add_labels=['INBOX'])


@mcp.tool(name="trash_gmail")
async def trash_gmail(message_ids: List[str]) -> str:
    """Move one or more Gmail messages to trash"""
    return await batch_modify_gmail(message_ids=message_ids, add_labels=['TRASH'])


@mcp.tool(name="spam_gmail")
async def spam_gmail(message_ids: List[str]) -> str:
    """Mark one or more Gmail messages as spam"""
    return await batch_modify_gmail(message_ids=message_ids, add_labels=['SPAM'], remove_labels=['INBOX'])


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


@mcp.tool(name="create_task_list")
async def create_task_list(title: str) -> str:
    """Create a new Google Tasks task list"""
    try:
        service = auth.get_tasks_service()
        task_list = service.tasklists().insert(body={"title": title}).execute()
        
        return json.dumps({
            "success": True,
            "task_list": task_list
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="delete_task_list")
async def delete_task_list(task_list_id: str) -> str:
    """Delete a Google Tasks task list"""
    try:
        service = auth.get_tasks_service()
        service.tasklists().delete(tasklist=task_list_id).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Deleted task list {task_list_id}"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="update_task_list")
async def update_task_list(task_list_id: str, title: str) -> str:
    """Rename a Google Tasks task list"""
    try:
        service = auth.get_tasks_service()
        task_list = service.tasklists().get(tasklist=task_list_id).execute()
        task_list["title"] = title
        updated = service.tasklists().update(tasklist=task_list_id, body=task_list).execute()
        
        return json.dumps({
            "success": True,
            "task_list": updated
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
    """List tasks from a Google Tasks list."""
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
        task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        
        return json.dumps({"success": True, "task": task}, indent=2)
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
    """Create a new Google Task."""
    try:
        service = auth.get_tasks_service()
        
        task_body = {'title': title}
        if notes:
            task_body['notes'] = notes
        if due:
            task_body['due'] = due
        if parent:
            task_body['parent'] = parent
        
        task = service.tasks().insert(tasklist=task_list_id, body=task_body).execute()
        
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
    """Update a Google Task."""
    try:
        service = auth.get_tasks_service()
        task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        
        if title:
            task['title'] = title
        if notes is not None:
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
        
        return json.dumps({"success": True, "task": updated_task}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="complete_task")
async def complete_task(task_list_id: str, task_id: str) -> str:
    """Mark a Google Task as completed"""
    try:
        service = auth.get_tasks_service()
        task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        task['status'] = 'completed'
        updated_task = service.tasks().update(tasklist=task_list_id, task=task_id, body=task).execute()
        
        return json.dumps({"success": True, "task": updated_task}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="delete_task")
async def delete_task(task_list_id: str, task_id: str) -> str:
    """Delete a Google Task"""
    try:
        service = auth.get_tasks_service()
        service.tasks().delete(tasklist=task_list_id, task=task_id).execute()
        
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


@mcp.tool(name="move_task_to_list")
async def move_task_to_list(task_id: str, source_list_id: str, destination_list_id: str) -> str:
    """Move a task between lists"""
    try:
        service = auth.get_tasks_service()
        
        task = service.tasks().get(tasklist=source_list_id, task=task_id).execute()
        task_copy = {
            "title": task.get("title"),
            "notes": task.get("notes"),
            "due": task.get("due"),
            "status": task.get("status")
        }
        
        new_task = service.tasks().insert(tasklist=destination_list_id, body=task_copy).execute()
        service.tasks().delete(tasklist=source_list_id, task=task_id).execute()
        
        return json.dumps({
            "success": True,
            "moved_task": new_task,
            "message": f"Task moved to list {destination_list_id}"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="star_task")
async def star_task(task_list_id: str, task_id: str) -> str:
    """Star a Google Task"""
    try:
        service = auth.get_tasks_service()
        updated_task = service.tasks().patch(
            tasklist=task_list_id,
            task=task_id,
            body={"starred": True}
        ).execute()
        
        return json.dumps({"success": True, "task": updated_task}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="unstar_task")
async def unstar_task(task_list_id: str, task_id: str) -> str:
    """Unstar a Google Task"""
    try:
        service = auth.get_tasks_service()
        updated_task = service.tasks().patch(
            tasklist=task_list_id,
            task=task_id,
            body={"starred": False}
        ).execute()
        
        return json.dumps({"success": True, "task": updated_task}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ============================================================================
# GOOGLE DRIVE TOOLS
# ============================================================================

@mcp.tool(name="list_folder")
async def list_folder(folder_id: str = "root", max_results: int = 100, page_token: str = None) -> str:
    """List contents of a Drive folder. Use 'root' for My Drive."""
    try:
        service = auth.get_drive_service()
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, pageSize=max_results, pageToken=page_token,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink)",
            orderBy="folder,name").execute()
        files = results.get('files', [])
        folders = [f for f in files if f.get('mimeType') == 'application/vnd.google-apps.folder']
        documents = [f for f in files if f.get('mimeType') != 'application/vnd.google-apps.folder']
        return json.dumps({"success": True, "folder_id": folder_id, "folders": folders,
            "files": documents, "total_count": len(files),
            "nextPageToken": results.get('nextPageToken')}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="create_folder")
async def create_folder(name: str, parent_folder_id: str = None) -> str:
    """Create a new folder in Google Drive. Creates in root if no parent specified."""
    try:
        service = auth.get_drive_service()
        file_metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_folder_id:
            file_metadata['parents'] = [parent_folder_id]
        folder = service.files().create(body=file_metadata, fields='id, name, webViewLink').execute()
        return json.dumps({"success": True, "folder": folder}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="move_file")
async def move_file(file_id: str, destination_folder_id: str) -> str:
    """Move a file to a different folder. Removes from current parent(s)."""
    try:
        service = auth.get_drive_service()
        file = service.files().get(fileId=file_id, fields='parents').execute()
        previous_parents = ",".join(file.get('parents', []))
        updated_file = service.files().update(fileId=file_id, addParents=destination_folder_id,
            removeParents=previous_parents, fields='id, name, parents, webViewLink').execute()
        return json.dumps({"success": True, "file": updated_file}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="rename_file")
async def rename_file(file_id: str, new_name: str) -> str:
    """Rename a file or folder in Google Drive."""
    try:
        service = auth.get_drive_service()
        updated_file = service.files().update(fileId=file_id, body={'name': new_name},
            fields='id, name, mimeType, webViewLink').execute()
        return json.dumps({"success": True, "file": updated_file}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="delete_file")
async def delete_file(file_id: str, permanent: bool = False) -> str:
    """Delete a file or folder. Default moves to trash; permanent=True deletes forever."""
    try:
        service = auth.get_drive_service()
        if permanent:
            service.files().delete(fileId=file_id).execute()
            return json.dumps({"success": True, "message": f"File {file_id} permanently deleted"}, indent=2)
        else:
            updated_file = service.files().update(fileId=file_id, body={'trashed': True},
                fields='id, name, trashed').execute()
            return json.dumps({"success": True, "file": updated_file, "message": "File moved to trash"}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="share_file")
async def share_file(file_id: str, email: str, role: str = "reader", send_notification: bool = True, message: str = None) -> str:
    """Share a file with a user. Role: reader, commenter, or writer."""
    try:
        service = auth.get_drive_service()
        permission = {'type': 'user', 'role': role, 'emailAddress': email}
        created_permission = service.permissions().create(fileId=file_id, body=permission,
            sendNotificationEmail=send_notification, emailMessage=message,
            fields='id, type, role, emailAddress').execute()
        return json.dumps({"success": True, "permission": created_permission,
            "message": f"File shared with {email} as {role}"}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="copy_file")
async def copy_file(file_id: str, new_name: str = None, destination_folder_id: str = None) -> str:
    """Copy a file. Cannot copy folders. Optionally specify new name and/or destination folder."""
    try:
        service = auth.get_drive_service()
        body = {}
        if new_name:
            body['name'] = new_name
        if destination_folder_id:
            body['parents'] = [destination_folder_id]
        copied_file = service.files().copy(fileId=file_id, body=body if body else None,
            fields='id, name, mimeType, parents, webViewLink').execute()
        return json.dumps({"success": True, "file": copied_file}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


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

@mcp.tool(name="download_drive_file")
async def download_drive_file(file_id: str) -> str:
    """
    Download and return the content of a Drive file.
    
    Supports:
    - Text files (.txt, .csv, .json, etc.) - returns text content
    - PDFs - extracts and returns text content (if PyMuPDF available)
    - Google Docs - exports as plain text
    - Google Sheets - exports as CSV
    - Google Slides - exports as plain text
    - Images - returns base64-encoded data
    - Other binary files - returns base64-encoded data
    
    Note: Large files may be truncated. For very large files, consider
    using the webViewLink from get_drive_file instead.
    """
    try:
        import base64
        
        service = auth.get_drive_service()
        
        # First get file metadata to determine type
        file_meta = service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, size"
        ).execute()
        
        mime_type = file_meta.get('mimeType', '')
        file_name = file_meta.get('name', 'unknown')
        
        # Handle Google Workspace files (need to export)
        if mime_type == 'application/vnd.google-apps.document':
            # Export Google Doc as plain text
            content = service.files().export(
                fileId=file_id,
                mimeType='text/plain'
            ).execute()
            return json.dumps({
                "success": True,
                "file_name": file_name,
                "mime_type": mime_type,
                "content_type": "text",
                "content": content.decode('utf-8') if isinstance(content, bytes) else content
            }, indent=2)
            
        elif mime_type == 'application/vnd.google-apps.spreadsheet':
            # Export Google Sheet as CSV
            content = service.files().export(
                fileId=file_id,
                mimeType='text/csv'
            ).execute()
            return json.dumps({
                "success": True,
                "file_name": file_name,
                "mime_type": mime_type,
                "content_type": "csv",
                "content": content.decode('utf-8') if isinstance(content, bytes) else content
            }, indent=2)
            
        elif mime_type == 'application/vnd.google-apps.presentation':
            # Export Google Slides as plain text
            content = service.files().export(
                fileId=file_id,
                mimeType='text/plain'
            ).execute()
            return json.dumps({
                "success": True,
                "file_name": file_name,
                "mime_type": mime_type,
                "content_type": "text",
                "content": content.decode('utf-8') if isinstance(content, bytes) else content
            }, indent=2)
        
        # For regular files, download the content
        request = service.files().get_media(fileId=file_id)
        content = request.execute()
        
        # Handle based on mime type
        if mime_type.startswith('text/') or mime_type in [
            'application/json',
            'application/xml',
            'application/javascript',
            'application/csv'
        ]:
            # Text content
            text_content = content.decode('utf-8') if isinstance(content, bytes) else content
            return json.dumps({
                "success": True,
                "file_name": file_name,
                "mime_type": mime_type,
                "content_type": "text",
                "content": text_content
            }, indent=2)
            
        elif mime_type == 'application/pdf':
            # Try to extract text from PDF
            try:
                import fitz  # PyMuPDF
                pdf_doc = fitz.open(stream=content, filetype="pdf")
                text_content = ""
                for page in pdf_doc:
                    text_content += page.get_text()
                pdf_doc.close()
                return json.dumps({
                    "success": True,
                    "file_name": file_name,
                    "mime_type": mime_type,
                    "content_type": "text",
                    "content": text_content,
                    "note": "Text extracted from PDF"
                }, indent=2)
            except ImportError:
                # PyMuPDF not available, return base64
                return json.dumps({
                    "success": True,
                    "file_name": file_name,
                    "mime_type": mime_type,
                    "content_type": "base64",
                    "content": base64.b64encode(content).decode('utf-8'),
                    "note": "PDF returned as base64 (install PyMuPDF for text extraction)"
                }, indent=2)
            except Exception as pdf_err:
                # PDF parsing failed, return base64
                return json.dumps({
                    "success": True,
                    "file_name": file_name,
                    "mime_type": mime_type,
                    "content_type": "base64",
                    "content": base64.b64encode(content).decode('utf-8'),
                    "note": f"PDF text extraction failed: {str(pdf_err)}"
                }, indent=2)
        
        elif mime_type.startswith('image/'):
            # Return image as base64
            return json.dumps({
                "success": True,
                "file_name": file_name,
                "mime_type": mime_type,
                "content_type": "base64",
                "content": base64.b64encode(content).decode('utf-8')
            }, indent=2)
        
        else:
            # Other binary files - return as base64
            return json.dumps({
                "success": True,
                "file_name": file_name,
                "mime_type": mime_type,
                "content_type": "base64",
                "content": base64.b64encode(content).decode('utf-8')
            }, indent=2)
            
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ============================================================================
# GOOGLE DOCS TOOLS
# ============================================================================

@mcp.tool(name="create_doc")
async def create_doc(title: str, content: str = None, folder_id: str = None) -> str:
    """
    Create a new Google Doc.

    Args:
        title: Document title
        content: Optional initial text content
        folder_id: Optional folder ID to create the doc in
    """
    try:
        docs_service = auth.get_docs_service()
        drive_service = auth.get_drive_service()

        # Create the document
        doc = docs_service.documents().create(body={'title': title}).execute()
        doc_id = doc.get('documentId')

        # Add initial content if provided
        if content:
            requests = [{'insertText': {'location': {'index': 1}, 'text': content}}]
            docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()

        # Move to folder if specified
        if folder_id:
            file = drive_service.files().get(fileId=doc_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents', []))
            drive_service.files().update(fileId=doc_id, addParents=folder_id,
                removeParents=previous_parents, fields='id, parents').execute()

        return json.dumps({
            "success": True,
            "document_id": doc_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="get_doc")
async def get_doc(document_id: str) -> str:
    """
    Get the content and structure of a Google Doc.

    Returns the document title and full text content.
    """
    try:
        docs_service = auth.get_docs_service()
        doc = docs_service.documents().get(documentId=document_id).execute()

        # Extract text content from the document body
        content = ""
        if 'body' in doc and 'content' in doc['body']:
            for element in doc['body']['content']:
                if 'paragraph' in element:
                    for para_element in element['paragraph'].get('elements', []):
                        if 'textRun' in para_element:
                            content += para_element['textRun'].get('content', '')

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "title": doc.get('title', ''),
            "content": content,
            "url": f"https://docs.google.com/document/d/{document_id}/edit"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="append_to_doc")
async def append_to_doc(document_id: str, text: str) -> str:
    """
    Append text to the end of a Google Doc.

    Args:
        document_id: The document ID
        text: Text to append (can include newlines)
    """
    try:
        docs_service = auth.get_docs_service()

        # Get current document to find the end index
        doc = docs_service.documents().get(documentId=document_id).execute()
        end_index = doc['body']['content'][-1]['endIndex'] - 1

        # Insert text at the end
        requests = [{'insertText': {'location': {'index': end_index}, 'text': text}}]
        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "appended_length": len(text)
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="insert_text")
async def insert_text(document_id: str, text: str, index: int) -> str:
    """
    Insert text at a specific position in a Google Doc.

    Args:
        document_id: The document ID
        text: Text to insert
        index: Position to insert at (1-based, 1 = beginning of doc)
    """
    try:
        docs_service = auth.get_docs_service()

        requests = [{'insertText': {'location': {'index': index}, 'text': text}}]
        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "inserted_at": index,
            "inserted_length": len(text)
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="replace_text")
async def replace_text(document_id: str, find_text: str, replace_with: str, match_case: bool = False) -> str:
    """
    Find and replace all occurrences of text in a Google Doc.

    Args:
        document_id: The document ID
        find_text: Text to find
        replace_with: Replacement text
        match_case: Whether to match case (default: False)
    """
    try:
        docs_service = auth.get_docs_service()

        requests = [{
            'replaceAllText': {
                'containsText': {'text': find_text, 'matchCase': match_case},
                'replaceText': replace_with
            }
        }]
        result = docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        # Get the number of replacements made
        occurrences = 0
        if 'replies' in result:
            for reply in result['replies']:
                if 'replaceAllText' in reply:
                    occurrences = reply['replaceAllText'].get('occurrencesChanged', 0)

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "find_text": find_text,
            "replace_with": replace_with,
            "occurrences_replaced": occurrences
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="delete_doc_content")
async def delete_doc_content(document_id: str, start_index: int, end_index: int) -> str:
    """
    Delete a range of content from a Google Doc.

    Args:
        document_id: The document ID
        start_index: Start position (1-based)
        end_index: End position (exclusive)
    """
    try:
        docs_service = auth.get_docs_service()

        requests = [{'deleteContentRange': {'range': {'startIndex': start_index, 'endIndex': end_index}}}]
        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "deleted_range": {"start": start_index, "end": end_index}
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="delete_empty_lines")
async def delete_empty_lines(document_id: str, max_consecutive: int = 1) -> str:
    """
    Find and delete excessive empty lines/paragraphs from a Google Doc.

    Args:
        document_id: The document ID
        max_consecutive: Maximum consecutive empty lines to keep (default 1, set to 0 to remove all)
    """
    try:
        docs_service = auth.get_docs_service()
        doc = docs_service.documents().get(documentId=document_id).execute()

        # Find empty paragraphs (paragraphs with only whitespace/newlines)
        empty_ranges = []
        consecutive_empty = 0

        for element in doc['body']['content']:
            if 'paragraph' in element:
                para = element['paragraph']
                text = ""
                for para_element in para.get('elements', []):
                    if 'textRun' in para_element:
                        text += para_element['textRun'].get('content', '')

                # Check if paragraph is empty (only whitespace)
                if text.strip() == '' and text:
                    consecutive_empty += 1
                    if consecutive_empty > max_consecutive:
                        empty_ranges.append({
                            'startIndex': element['startIndex'],
                            'endIndex': element['endIndex']
                        })
                else:
                    consecutive_empty = 0

        if not empty_ranges:
            return json.dumps({
                "success": True,
                "document_id": document_id,
                "message": "No excess empty lines found",
                "deleted_count": 0
            }, indent=2)

        # Delete in reverse order to preserve indices
        requests = []
        for range_info in reversed(empty_ranges):
            requests.append({
                'deleteContentRange': {
                    'range': {
                        'startIndex': range_info['startIndex'],
                        'endIndex': range_info['endIndex']
                    }
                }
            })

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "deleted_count": len(empty_ranges)
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="format_text")
async def format_text(
    document_id: str,
    start_index: int,
    end_index: int,
    bold: bool = None,
    italic: bool = None,
    underline: bool = None,
    strikethrough: bool = None,
    font_size: int = None,
    font_family: str = None,
    foreground_color: str = None,
    background_color: str = None
) -> str:
    """
    Apply text formatting to a range in a Google Doc.

    Args:
        document_id: The document ID
        start_index: Start position (1-based)
        end_index: End position (exclusive)
        bold: Set bold (True/False)
        italic: Set italic (True/False)
        underline: Set underline (True/False)
        strikethrough: Set strikethrough (True/False)
        font_size: Font size in points (e.g., 12, 14, 18)
        font_family: Font name (e.g., 'Arial', 'Times New Roman')
        foreground_color: Text color as hex (e.g., '#FF0000' for red)
        background_color: Highlight color as hex
    """
    try:
        docs_service = auth.get_docs_service()

        text_style = {}
        fields = []

        if bold is not None:
            text_style['bold'] = bold
            fields.append('bold')
        if italic is not None:
            text_style['italic'] = italic
            fields.append('italic')
        if underline is not None:
            text_style['underline'] = underline
            fields.append('underline')
        if strikethrough is not None:
            text_style['strikethrough'] = strikethrough
            fields.append('strikethrough')
        if font_size is not None:
            text_style['fontSize'] = {'magnitude': font_size, 'unit': 'PT'}
            fields.append('fontSize')
        if font_family is not None:
            text_style['weightedFontFamily'] = {'fontFamily': font_family}
            fields.append('weightedFontFamily')
        if foreground_color is not None:
            # Parse hex color
            hex_color = foreground_color.lstrip('#')
            r, g, b = tuple(int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))
            text_style['foregroundColor'] = {'color': {'rgbColor': {'red': r, 'green': g, 'blue': b}}}
            fields.append('foregroundColor')
        if background_color is not None:
            hex_color = background_color.lstrip('#')
            r, g, b = tuple(int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))
            text_style['backgroundColor'] = {'color': {'rgbColor': {'red': r, 'green': g, 'blue': b}}}
            fields.append('backgroundColor')

        if not fields:
            return json.dumps({"success": False, "error": "No formatting options specified"}, indent=2)

        requests = [{
            'updateTextStyle': {
                'range': {'startIndex': start_index, 'endIndex': end_index},
                'textStyle': text_style,
                'fields': ','.join(fields)
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "formatted_range": {"start": start_index, "end": end_index},
            "applied_styles": fields
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="format_paragraph")
async def format_paragraph(
    document_id: str,
    start_index: int,
    end_index: int,
    alignment: str = None,
    line_spacing: float = None,
    space_above: float = None,
    space_below: float = None,
    indent_first_line: float = None,
    indent_start: float = None,
    indent_end: float = None
) -> str:
    """
    Apply paragraph formatting to a range in a Google Doc.

    Args:
        document_id: The document ID
        start_index: Start position (1-based)
        end_index: End position (exclusive)
        alignment: Text alignment ('START', 'CENTER', 'END', 'JUSTIFIED')
        line_spacing: Line spacing multiplier (1.0 = single, 1.5, 2.0 = double)
        space_above: Space before paragraph in points
        space_below: Space after paragraph in points
        indent_first_line: First line indent in points
        indent_start: Left indent in points
        indent_end: Right indent in points
    """
    try:
        docs_service = auth.get_docs_service()

        paragraph_style = {}
        fields = []

        if alignment is not None:
            paragraph_style['alignment'] = alignment.upper()
            fields.append('alignment')
        if line_spacing is not None:
            paragraph_style['lineSpacing'] = line_spacing * 100  # API expects percentage
            fields.append('lineSpacing')
        if space_above is not None:
            paragraph_style['spaceAbove'] = {'magnitude': space_above, 'unit': 'PT'}
            fields.append('spaceAbove')
        if space_below is not None:
            paragraph_style['spaceBelow'] = {'magnitude': space_below, 'unit': 'PT'}
            fields.append('spaceBelow')
        if indent_first_line is not None:
            paragraph_style['indentFirstLine'] = {'magnitude': indent_first_line, 'unit': 'PT'}
            fields.append('indentFirstLine')
        if indent_start is not None:
            paragraph_style['indentStart'] = {'magnitude': indent_start, 'unit': 'PT'}
            fields.append('indentStart')
        if indent_end is not None:
            paragraph_style['indentEnd'] = {'magnitude': indent_end, 'unit': 'PT'}
            fields.append('indentEnd')

        if not fields:
            return json.dumps({"success": False, "error": "No formatting options specified"}, indent=2)

        requests = [{
            'updateParagraphStyle': {
                'range': {'startIndex': start_index, 'endIndex': end_index},
                'paragraphStyle': paragraph_style,
                'fields': ','.join(fields)
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "formatted_range": {"start": start_index, "end": end_index},
            "applied_styles": fields
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="create_bullets")
async def create_bullets(
    document_id: str,
    start_index: int,
    end_index: int,
    bullet_preset: str = "BULLET_DISC_CIRCLE_SQUARE"
) -> str:
    """
    Apply bullet or numbered list formatting to paragraphs.

    Args:
        document_id: The document ID
        start_index: Start position (1-based)
        end_index: End position (exclusive)
        bullet_preset: Bullet style preset. Options:
            - 'BULLET_DISC_CIRCLE_SQUARE' (default bullets)
            - 'BULLET_DIAMONDX_ARROW3D_SQUARE'
            - 'BULLET_CHECKBOX'
            - 'NUMBERED_DECIMAL_ALPHA_ROMAN'
            - 'NUMBERED_DECIMAL_NESTED'
            - 'NUMBERED_UPPERALPHA_ALPHA_ROMAN'
            - 'NUMBERED_UPPERROMAN_UPPERALPHA_DECIMAL'
    """
    try:
        docs_service = auth.get_docs_service()

        requests = [{
            'createParagraphBullets': {
                'range': {'startIndex': start_index, 'endIndex': end_index},
                'bulletPreset': bullet_preset
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "bullet_range": {"start": start_index, "end": end_index},
            "bullet_preset": bullet_preset
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="remove_bullets")
async def remove_bullets(document_id: str, start_index: int, end_index: int) -> str:
    """
    Remove bullet or numbered list formatting from paragraphs.

    Args:
        document_id: The document ID
        start_index: Start position (1-based)
        end_index: End position (exclusive)
    """
    try:
        docs_service = auth.get_docs_service()

        requests = [{
            'deleteParagraphBullets': {
                'range': {'startIndex': start_index, 'endIndex': end_index}
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "removed_from_range": {"start": start_index, "end": end_index}
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="set_heading")
async def set_heading(
    document_id: str,
    start_index: int,
    end_index: int,
    heading_level: int
) -> str:
    """
    Apply a heading style to paragraphs.

    Args:
        document_id: The document ID
        start_index: Start position (1-based)
        end_index: End position (exclusive)
        heading_level: 0 for normal text, 1-6 for Heading 1 through Heading 6
    """
    try:
        docs_service = auth.get_docs_service()

        if heading_level == 0:
            named_style = 'NORMAL_TEXT'
        elif 1 <= heading_level <= 6:
            named_style = f'HEADING_{heading_level}'
        else:
            return json.dumps({"success": False, "error": "heading_level must be 0-6"}, indent=2)

        requests = [{
            'updateParagraphStyle': {
                'range': {'startIndex': start_index, 'endIndex': end_index},
                'paragraphStyle': {'namedStyleType': named_style},
                'fields': 'namedStyleType'
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "heading_range": {"start": start_index, "end": end_index},
            "style": named_style
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="set_document_margins")
async def set_document_margins(
    document_id: str,
    top: float = None,
    bottom: float = None,
    left: float = None,
    right: float = None
) -> str:
    """
    Set page margins for the entire document.

    Args:
        document_id: The document ID
        top: Top margin in inches
        bottom: Bottom margin in inches
        left: Left margin in inches
        right: Right margin in inches
    """
    try:
        docs_service = auth.get_docs_service()

        document_style = {}
        fields = []

        if top is not None:
            document_style['marginTop'] = {'magnitude': top * 72, 'unit': 'PT'}  # 72 points per inch
            fields.append('marginTop')
        if bottom is not None:
            document_style['marginBottom'] = {'magnitude': bottom * 72, 'unit': 'PT'}
            fields.append('marginBottom')
        if left is not None:
            document_style['marginLeft'] = {'magnitude': left * 72, 'unit': 'PT'}
            fields.append('marginLeft')
        if right is not None:
            document_style['marginRight'] = {'magnitude': right * 72, 'unit': 'PT'}
            fields.append('marginRight')

        if not fields:
            return json.dumps({"success": False, "error": "No margin values specified"}, indent=2)

        requests = [{
            'updateDocumentStyle': {
                'documentStyle': document_style,
                'fields': ','.join(fields)
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "updated_margins": fields
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="get_doc_structure")
async def get_doc_structure(document_id: str) -> str:
    """
    Get detailed document structure with index positions.

    Returns each paragraph with its start/end indices, making it easy to
    target specific text for formatting operations.
    """
    try:
        docs_service = auth.get_docs_service()
        doc = docs_service.documents().get(documentId=document_id).execute()

        structure = []
        if 'body' in doc and 'content' in doc['body']:
            for element in doc['body']['content']:
                # Skip elements without indices (like the root structural element)
                if 'startIndex' not in element:
                    continue

                if 'paragraph' in element:
                    para = element['paragraph']
                    text = ""
                    for para_element in para.get('elements', []):
                        if 'textRun' in para_element:
                            text += para_element['textRun'].get('content', '')

                    structure.append({
                        'type': 'paragraph',
                        'startIndex': element.get('startIndex'),
                        'endIndex': element.get('endIndex'),
                        'text': text,
                        'style': para.get('paragraphStyle', {}).get('namedStyleType', 'NORMAL_TEXT')
                    })
                elif 'table' in element:
                    structure.append({
                        'type': 'table',
                        'startIndex': element.get('startIndex'),
                        'endIndex': element.get('endIndex'),
                        'rows': element['table'].get('rows', 0),
                        'columns': element['table'].get('columns', 0)
                    })
                elif 'sectionBreak' in element:
                    structure.append({
                        'type': 'section_break',
                        'startIndex': element.get('startIndex'),
                        'endIndex': element.get('endIndex')
                    })

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "title": doc.get('title', ''),
            "structure": structure,
            "url": f"https://docs.google.com/document/d/{document_id}/edit"
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="insert_link")
async def insert_link(
    document_id: str,
    start_index: int,
    end_index: int,
    url: str
) -> str:
    """
    Add a hyperlink to existing text in a Google Doc.

    Args:
        document_id: The document ID
        start_index: Start position of text to make into link
        end_index: End position of text to make into link
        url: The URL the link should point to
    """
    try:
        docs_service = auth.get_docs_service()

        requests = [{
            'updateTextStyle': {
                'range': {'startIndex': start_index, 'endIndex': end_index},
                'textStyle': {'link': {'url': url}},
                'fields': 'link'
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "linked_range": {"start": start_index, "end": end_index},
            "url": url
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="link_text")
async def link_text(
    document_id: str,
    find_text: str,
    url: str,
    match_case: bool = False,
    occurrence: int = 1
) -> str:
    """
    Find text in a Google Doc and make it a hyperlink.

    This is easier to use than insert_link because you don't need to calculate indices.

    Args:
        document_id: The document ID
        find_text: The exact text to find and link
        url: The URL the link should point to
        match_case: Whether to match case exactly (default: False)
        occurrence: Which occurrence to link if text appears multiple times (1 = first, 2 = second, etc.)
    """
    try:
        docs_service = auth.get_docs_service()
        doc = docs_service.documents().get(documentId=document_id).execute()

        # Build the full document text with index tracking
        text_with_indices = []  # List of (char, index) tuples
        if 'body' in doc and 'content' in doc['body']:
            for element in doc['body']['content']:
                if 'paragraph' in element:
                    for para_element in element['paragraph'].get('elements', []):
                        if 'textRun' in para_element:
                            start_idx = para_element.get('startIndex', 0)
                            text = para_element['textRun'].get('content', '')
                            for i, char in enumerate(text):
                                text_with_indices.append((char, start_idx + i))

        # Build full text string for searching
        full_text = ''.join([t[0] for t in text_with_indices])

        # Search for the text
        search_text = find_text if match_case else find_text.lower()
        search_in = full_text if match_case else full_text.lower()

        # Find the nth occurrence
        start_pos = 0
        found_count = 0
        match_start = -1

        while True:
            pos = search_in.find(search_text, start_pos)
            if pos == -1:
                break
            found_count += 1
            if found_count == occurrence:
                match_start = pos
                break
            start_pos = pos + 1

        if match_start == -1:
            return json.dumps({
                "success": False,
                "error": f"Text '{find_text}' not found" + (f" (occurrence {occurrence})" if occurrence > 1 else ""),
                "occurrences_found": found_count
            }, indent=2)

        # Get the actual document indices
        start_index = text_with_indices[match_start][1]
        end_index = text_with_indices[match_start + len(find_text) - 1][1] + 1

        # Apply the link
        requests = [{
            'updateTextStyle': {
                'range': {'startIndex': start_index, 'endIndex': end_index},
                'textStyle': {'link': {'url': url}},
                'fields': 'link'
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "linked_text": find_text,
            "linked_range": {"start": start_index, "end": end_index},
            "url": url,
            "occurrence": occurrence
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="insert_image")
async def insert_image(
    document_id: str,
    image_url: str,
    index: int,
    width: float = None,
    height: float = None
) -> str:
    """
    Insert an image into a Google Doc from a URL.

    Args:
        document_id: The document ID
        image_url: Public URL of the image to insert
        index: Position to insert the image (1-based)
        width: Optional width in points (72 points = 1 inch)
        height: Optional height in points
    """
    try:
        docs_service = auth.get_docs_service()

        inline_object = {
            'uri': image_url
        }

        # Add size if specified
        if width or height:
            size = {}
            if width:
                size['width'] = {'magnitude': width, 'unit': 'PT'}
            if height:
                size['height'] = {'magnitude': height, 'unit': 'PT'}
            inline_object['objectSize'] = size

        requests = [{
            'insertInlineImage': {
                'location': {'index': index},
                'uri': image_url,
                'objectSize': inline_object.get('objectSize', {})
            }
        }]

        # Remove empty objectSize if not specified
        if not inline_object.get('objectSize'):
            requests[0]['insertInlineImage'].pop('objectSize', None)

        result = docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "inserted_at": index,
            "image_url": image_url
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="insert_table")
async def insert_table(
    document_id: str,
    index: int,
    rows: int,
    columns: int
) -> str:
    """
    Insert a table into a Google Doc.

    Args:
        document_id: The document ID
        index: Position to insert the table (1-based)
        rows: Number of rows
        columns: Number of columns
    """
    try:
        docs_service = auth.get_docs_service()

        requests = [{
            'insertTable': {
                'location': {'index': index},
                'rows': rows,
                'columns': columns
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "inserted_at": index,
            "table_size": {"rows": rows, "columns": columns}
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


@mcp.tool(name="insert_page_break")
async def insert_page_break(document_id: str, index: int) -> str:
    """
    Insert a page break into a Google Doc.

    Args:
        document_id: The document ID
        index: Position to insert the page break (1-based)
    """
    try:
        docs_service = auth.get_docs_service()

        requests = [{
            'insertPageBreak': {
                'location': {'index': index}
            }
        }]

        docs_service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()

        return json.dumps({
            "success": True,
            "document_id": document_id,
            "page_break_at": index
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, indent=2)


# ============================================================================
# OAUTH WEB ENDPOINTS
# ============================================================================

from starlette.requests import Request
from starlette.responses import RedirectResponse, JSONResponse


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


async def health_check(request: Request):
    """Health check endpoint"""
    return JSONResponse({
        "status": "ok",
        "service": "Google Connections MCP",
        "authenticated": auth.is_authenticated()
    })


# ============================================================================
# SERVER STARTUP
# ============================================================================

def main():
    """Main entry point for the server."""
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


if __name__ == "__main__":
    main()
