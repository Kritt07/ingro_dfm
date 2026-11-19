"""Извлекать текстовые PDF постранично, сохраняя исходные координаты."""
import logging
from pathlib import Path
import pymupdf
from .format_router import InspectionError, inspect_file
from .pdf_types import PDFExtraction, PDFPage, PDFTable, TextBlock

logger = logging.getLogger(__name__)

def _read_page(page, number, kind):
    return PDFPage(number, kind, [TextBlock(tuple(b[:4]), b[4])
                                 for b in page.get_text('blocks') if b[6] == 0],
                   _extract_tables(page, number))

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

def _extract_tables(page, number):
    """Найти сетки по линиям, затем по выравниванию при отсутствии линий."""
    finder = page.find_tables(strategy='lines_strict')
    method = 'lines'
    if not finder.tables:
        finder = page.find_tables(strategy='text', min_words_vertical=3)
        method = 'text'
    tables = []
    for source in finder.tables:
        values = source.extract()
        boxes = [[tuple(c) if c else None for c in row.cells] for row in source.rows]
        xs = sorted({v for row in boxes for b in row if b for v in (b[0], b[2])})
        ys = sorted({v for row in boxes for b in row if b for v in (b[1], b[3])})
        merged = []
        for r, row in enumerate(boxes):
            for c, box in enumerate(row):
                if box is None:
                    continue
                r1 = min(range(len(ys)), key=lambda i: abs(ys[i]-box[1]))
                r2 = min(range(len(ys)), key=lambda i: abs(ys[i]-box[3]))
                c1 = min(range(len(xs)), key=lambda i: abs(xs[i]-box[0]))
                c2 = min(range(len(xs)), key=lambda i: abs(xs[i]-box[2]))
                if r2-r1 > 1 or c2-c1 > 1:
                    merged.append((r1+1,c1+1,r2,c2))
                    for rr in range(r1,min(r2,len(values))):
                        for cc in range(c1,min(c2,len(values[rr]))):
                            values[rr][cc] = values[r][c]
                            boxes[rr][cc] = box
        tables.append(PDFTable(number, tuple(source.bbox), values, boxes, merged, method))
    return tables
