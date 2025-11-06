"""
Dynamic Sheet Column Mapper
Automatically detects and maps sheet columns regardless of position
"""

import pandas as pd
from typing import Dict, List, Optional, Any


class SheetMapper:
    """Maps sheet columns dynamically based on headers"""
    
    def __init__(self, worksheet):
        """Initialize mapper with worksheet data"""
        self.worksheet = worksheet
        self.data = worksheet.get_all_values()
        
        if not self.data:
            raise ValueError("Worksheet is empty")
        
        self.headers = self.data[0]
        self.column_map = {col: idx for idx, col in enumerate(self.headers)}
        self.rows = self.data[1:]
    
    def get_column_index(self, column_name: str) -> Optional[int]:
        """Get index for a column name"""
        return self.column_map.get(column_name)
    
    def has_column(self, column_name: str) -> bool:
        """Check if column exists"""
        return column_name in self.column_map
    
    def require_column(self, column_name: str) -> int:
        """Get column index or raise error if missing"""
        idx = self.get_column_index(column_name)
        if idx is None:
            raise ValueError(f"Required column '{column_name}' not found in sheet")
        return idx
    
    def get_cell_value(self, row_data: List, column_name: str) -> str:
        """Get cell value from row by column name"""
        idx = self.get_column_index(column_name)
        if idx is None or idx >= len(row_data):
            return ""
        return row_data[idx]
    
    def set_cell_value(self, row_data: List, column_name: str, value: Any) -> List:
        """Set cell value in row by column name"""
        idx = self.require_column(column_name)
        
        # Extend row if needed
        while len(row_data) <= idx:
            row_data.append('')
        
        row_data[idx] = str(value)
        return row_data
    
    def find_row_by_value(self, column_name: str, value: str) -> Optional[tuple]:
        """Find row by column value. Returns (row_number, row_data) or None"""
        idx = self.require_column(column_name)
        
        for row_num, row in enumerate(self.rows, start=2):  # Start at 2 (skip header)
            if idx < len(row) and row[idx] == value:
                return (row_num, row)
        
        return None
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert sheet data to pandas DataFrame"""
        return pd.DataFrame(self.rows, columns=self.headers)
    
    def row_to_dict(self, row_data: List) -> Dict[str, str]:
        """Convert row data to dictionary"""
        return {col: (row_data[idx] if idx < len(row_data) else "") 
                for col, idx in self.column_map.items()}
    
    def dict_to_row(self, data_dict: Dict[str, Any]) -> List[str]:
        """Convert dictionary to row data"""
        row = [''] * len(self.headers)
        for col_name, value in data_dict.items():
            if col_name in self.column_map:
                row[self.column_map[col_name]] = str(value)
        return row
    
    def update_row(self, row_number: int, updates: Dict[str, Any]):
        """Update specific columns in a row"""
        # Get current row data
        if row_number < 2 or row_number > len(self.data):
            raise ValueError(f"Invalid row number: {row_number}")
        
        current_row = list(self.data[row_number - 1])
        
        # Apply updates
        for col_name, value in updates.items():
            current_row = self.set_cell_value(current_row, col_name, value)
        
        # Write back to sheet
        range_name = f"A{row_number}:{self._col_letter(len(current_row))}{row_number}"
        self.worksheet.update(range_name, [current_row])
    
    def append_row(self, data_dict: Dict[str, Any]):
        """Append a new row to the sheet"""
        row_data = self.dict_to_row(data_dict)
        self.worksheet.append_row(row_data, value_input_option='USER_ENTERED')
    
    def _col_letter(self, col_num: int) -> str:
        """Convert column number to letter (1 -> A, 27 -> AA, etc)"""
        result = ""
        while col_num > 0:
            col_num, remainder = divmod(col_num - 1, 26)
            result = chr(65 + remainder) + result
        return result


def get_sheet_mapper(sheets_client, spreadsheet_id: str, worksheet_name: str) -> SheetMapper:
    """Convenience function to get a sheet mapper"""
    spreadsheet = sheets_client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(worksheet_name)
    return SheetMapper(worksheet)


# Standard column sets for different sheets
TASK_COLUMNS = {
    'required': ['Task', 'Status'],
    'standard': ['Created Date', 'Completed Date', 'Status', 'Task', 'Tags', 
                'Category', 'Projects', 'Do Date', 'Due Date', 'Due Time',
                'Urgent', 'Important', 'Priority', 'Location', 'Notes'],
    'optional': ['Recurring', 'Recurring Schedule', 'Task ID']
}

ACCOMPLISHMENT_COLUMNS = {
    'required': ['Date', 'Accomplishment'],
    'standard': ['Date', 'Time', 'Category', 'Accomplishment', 'Notes'],
    'optional': ['ID']
}

PRIORITY_COLUMNS = {
    'required': ['Date', 'Priorities'],
    'standard': ['Date', 'Priorities']
}


def validate_sheet_structure(mapper: SheetMapper, required_columns: List[str]) -> bool:
    """Validate that sheet has all required columns"""
    missing = [col for col in required_columns if not mapper.has_column(col)]
    if missing:
        raise ValueError(f"Sheet is missing required columns: {', '.join(missing)}")
    return True
