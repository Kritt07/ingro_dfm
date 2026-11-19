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
                    if page.kind in {'pdf_scanned', 'pdf_hybrid', 'pdf_unknown'}:
                        result.warnings.append(f'Page {index+1}: raster/unknown content may require OCR')
                    if not page.tables:
                        result.warnings.append(f'Page {index+1}: no tables extracted')
                    if any(t.method == 'text' for t in page.tables):
                        result.warnings.append(f'Page {index+1}: inferred borderless grid requires review')
                except Exception as exc:
                    result.warnings.append(f'Page {index+1}: {exc}')
    except Exception as exc:
        raise InspectionError(f'Cannot extract {path}: {exc}') from exc
    for warning in result.warnings:
        logger.warning(warning)
    return result

def _extract_tables(page, number):
    """Найти сетки по линиям, затем по выравниванию при отсутствии линий."""
    finder = page.find_tables(strategy='lines_strict', use_layout=False)
    method = 'lines'
    if not finder.tables:
        return _borderless_tables(page, number)
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



def _borderless_tables(page, number):
    """Восстановить простые таблицы по повторяющимся позициям текста."""
    lines = {}
    for word in page.get_text('words'):
        lines.setdefault((word[5], word[6]), []).append(word)
    # PDF может хранить каждую ячейку отдельной строкой: группируем по высоте.
    bands = []
    for word in sorted((w for ws in lines.values() for w in ws), key=lambda w: (w[1], w[0])):
        band = next((b for b in bands if abs(b[0][1]-word[1]) < 3), None)
        if band is None:
            bands.append([word])
        else:
            band.append(word)
    candidates = []
    for band in bands:
        band.sort(key=lambda w: w[0])
        if len(band) >= 2 and all(band[i+1][0]-band[i][2] > 20 for i in range(len(band)-1)):
            candidates.append(band)
    groups = []
    for band in candidates:
        if not groups or band[0][1]-groups[-1][-1][0][1] > 50:
            groups.append([])
        groups[-1].append(band)
    result = []
    for group in groups:
        if len(group) < 3:
            continue
        anchors = []
        for band in group:
            for word in band:
                if not any(abs(word[0]-x) < 3 for x in anchors):
                    anchors.append(word[0])
        anchors.sort()
        if len(anchors) < 2:
            continue
        values, boxes = [], []
        for band in group:
            row, rects = [None]*len(anchors), [None]*len(anchors)
            for word in band:
                col = min(range(len(anchors)), key=lambda i: abs(anchors[i]-word[0]))
                row[col], rects[col] = word[4], tuple(word[:4])
            values.append(row)
            boxes.append(rects)
        words = [w for band in group for w in band]
        bbox = (min(w[0] for w in words), min(w[1] for w in words),
                max(w[2] for w in words), max(w[3] for w in words))
        result.append(PDFTable(number, bbox, values, boxes, method='text'))
    return result
