"""Предоставлять интерфейс определения форматов нормативных документов."""

from .format_router import Inspection, InspectionError, inspect_file

__all__ = ["Inspection", "InspectionError", "inspect_file"]
