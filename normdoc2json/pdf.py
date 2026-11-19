"""Извлекать текстовые PDF постранично, сохраняя исходные координаты."""
import logging
from pathlib import Path
import pymupdf
from .format_router import InspectionError, inspect_file
from .pdf_types import PDFExtraction, PDFPage, PDFTable, TextBlock

logger = logging.getLogger(__name__)

def _read_page(page, number, kind):
    return PDFPage(number, kind, [TextBlock(tuple(b[:4]), b[4])
                                 for b in page.get_text('blocks') if b[6] == 0])

def extract_pdf(path: str | Path) -> PDFExtraction:
    """Извлечь PDF; ошибки страниц сохранить, остальные страницы продолжить."""
    inspection = inspect_file(path)
    if not inspection.source_format.startswith('pdf_'):
        raise InspectionError(f'Expected PDF: {path}')
    result = PDFExtraction(str(path), inspection.source_format,
                           warnings=list(inspection.warnings))
    try:
        with pymupdf.open(path) as document:
            for index in range(len(document)):
                try:
                    page = _read_page(document[index], index+1, inspection.page_kinds[index])
                    result.pages.append(page)
                except Exception as exc:
                    result.warnings.append(f'Page {index+1}: {exc}')
    except Exception as exc:
        raise InspectionError(f'Cannot extract {path}: {exc}') from exc
    for warning in result.warnings:
        logger.warning(warning)
    return result
