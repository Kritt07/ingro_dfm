"""Предоставлять интерфейс определения форматов нормативных документов."""

from .format_router import Inspection, InspectionError, inspect_file
from .spreadsheets import SheetGrid, SpreadsheetExtraction, extract_spreadsheet

__all__ = ["Inspection", "InspectionError", "inspect_file",
           "SheetGrid", "SpreadsheetExtraction", "extract_spreadsheet"]

from .pdf import extract_pdf
from .pdf_types import PDFExtraction, PDFPage, PDFTable, TextBlock
__all__ += ["extract_pdf", "PDFExtraction", "PDFPage", "PDFTable", "TextBlock"]

from .image_io import ImagePage, iter_image_pages


def iter_preprocessed_images(path, *, target_dpi=300, max_pixels=40_000_000):
    """Лениво подключить OpenCV только при запросе предобработки."""
    from .preprocessing import iter_preprocessed_images as preprocess
    return preprocess(path, target_dpi=target_dpi, max_pixels=max_pixels)


__all__ += ['ImagePage', 'iter_image_pages', 'iter_preprocessed_images']
