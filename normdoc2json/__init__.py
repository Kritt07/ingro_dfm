"""Предоставлять интерфейс определения форматов нормативных документов."""

from .format_router import Inspection, InspectionError, inspect_file
from .spreadsheets import SheetGrid, SpreadsheetExtraction, extract_spreadsheet

__all__ = ["Inspection", "InspectionError", "inspect_file",
           "SheetGrid", "SpreadsheetExtraction", "extract_spreadsheet"]
