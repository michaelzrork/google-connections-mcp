"""
Dynamic Sheet Column Mapper
Automatically detects and maps sheet columns regardless of position.
Supports cell-level updates to preserve formulas in other columns.
"""

import pandas as pd
from typing import Dict, List, Optional, Any, Tuple


class SheetMapper:
    """Maps sheet columns dynamically based on headers.
    
    Key features:
    - Column names map to positions automatically
    - Updates write only to specified cells (preserves formulas elsewhere)
    - Appends write only to specified columns (preserves formula columns)
    """
    
    def __init__(self, worksheet):
        """Initialize mapper with worksheet data."""
        self.worksheet = worksheet
        self.data = worksheet.get_all_values()
        
        if not self.data:
            raise ValueError("Worksheet is empty")
        
        self.headers = self.data[0]
        self.column_map = {col: idx for idx, col in enumerate(self.headers)}
        self.rows = self.data[1:]
    
    def get_column_index(self, column_name: str) -> Optional[int]:
        """Get 0-based index for a column name."""
        return self.column_map.get(column_name)
    
    def get_column_letter(self, column_name: str) -> Optional[str]:
        """Get column letter (A, B, C, etc.) for a column name."""
        idx = self.get_column_index(column_name)
        if idx is None:
            return None
        return self._col_letter(idx + 1)  # _col_letter is 1-indexed
    
    def has_column(self, column_name: str) -> bool:
        """Check if column exists in sheet."""
        return column_name in self.column_map
    
    def require_column(self, column_name: str) -> int:
        """Get column index or raise error if missing."""
        idx = self.get_column_index(column_name)
        if idx is None:
            available = ', '.join(self.headers) if self.headers else 'none'
            raise ValueError(f"Column '{column_name}' not found. Available columns: {available}")
        return idx
    
    def get_cell_value(self, row_data: List, column_name: str) -> str:
        """Get cell value from row by column name."""
        idx = self.get_column_index(column_name)
        if idx is None or idx >= len(row_data):
            return ""
        return row_data[idx]
    
    def find_row_by_value(self, column_name: str, value: str) -> Optional[Tuple[int, List]]:
        """Find first row matching column value.
        
        Returns:
            Tuple of (row_number, row_data) or None if not found.
            Row number is 1-indexed (row 1 = headers, row 2 = first data row).
        """
        idx = self.require_column(column_name)
        
        for row_num, row in enumerate(self.rows, start=2):  # Start at 2 (skip header)
            if idx < len(row) and row[idx] == value:
                return (row_num, row)
        
        return None
    
    def find_all_rows_by_value(self, column_name: str, value: str) -> List[Tuple[int, List]]:
        """Find all rows matching column value.
        
        Returns:
            List of (row_number, row_data) tuples.
        """
        idx = self.require_column(column_name)
        results = []
        
        for row_num, row in enumerate(self.rows, start=2):
            if idx < len(row) and row[idx] == value:
                results.append((row_num, row))
        
        return results
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert sheet data to pandas DataFrame."""
        return pd.DataFrame(self.rows, columns=self.headers)
    
    def row_to_dict(self, row_data: List) -> Dict[str, str]:
        """Convert row data to dictionary."""
        return {col: (row_data[idx] if idx < len(row_data) else "") 
                for col, idx in self.column_map.items()}
    
    def get_next_empty_row(self) -> int:
        """Get the row number for the next empty row (for appending).
        
        Returns:
            1-indexed row number where new data should go.
        """
        return len(self.data) + 1
    
    def update_cells(self, row_number: int, updates: Dict[str, Any]) -> None:
        """Update specific cells in a row by column name.
        
        Only writes to the cells specified - other cells (including formulas) 
        are left untouched.
        
        Args:
            row_number: 1-indexed row number (row 1 = headers)
            updates: Dict of {column_name: value} to update
            
        Raises:
            ValueError: If column name doesn't exist
        """
        for col_name, value in updates.items():
            col_idx = self.require_column(col_name)
            col_letter = self._col_letter(col_idx + 1)
            cell = f"{col_letter}{row_number}"
            self.worksheet.update(cell, [[value]], value_input_option='USER_ENTERED')
    
    def append_row(self, data_dict: Dict[str, Any]) -> int:
        """Append a new row, writing only to specified columns.
        
        Only writes to columns included in data_dict. Other columns 
        (like formula columns) are left empty/untouched.
        
        Args:
            data_dict: Dict of {column_name: value} to write
            
        Returns:
            Row number where data was written
            
        Raises:
            ValueError: If any column name doesn't exist
        """
        next_row = self.get_next_empty_row()
        self.update_cells(next_row, data_dict)
        return next_row
    
    def _col_letter(self, col_num: int) -> str:
        """Convert 1-indexed column number to letter (1 -> A, 27 -> AA, etc)."""
        result = ""
        while col_num > 0:
            col_num, remainder = divmod(col_num - 1, 26)
            result = chr(65 + remainder) + result
        return result


def get_sheet_mapper(sheets_client, spreadsheet_id: str, worksheet_name: str) -> SheetMapper:
    """Convenience function to get a sheet mapper for a worksheet."""
    spreadsheet = sheets_client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(worksheet_name)
    return SheetMapper(worksheet)
