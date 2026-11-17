# Проверка и преобразование документов с нормативными картами.

from .format_router import Inspection, InspectionError, inspect_file

__all__ = ["Inspection", "InspectionError", "inspect_file"]
