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


def iter_ocr_pages(path, **kwargs):
    """Lazily stream OCR evidence for image, TIFF and PDF pages."""
    from .ocr import iter_ocr_pages as extract
    return extract(path, **kwargs)


def ocr_document(path, **kwargs):
    """Lazily build a validated document from OCR evidence."""
    from .ocr import ocr_document as extract
    return extract(path, **kwargs)


__all__ += ['iter_ocr_pages', 'ocr_document']
