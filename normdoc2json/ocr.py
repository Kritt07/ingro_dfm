"""Stream image/TIFF/PDF pages through OCR, retaining raw evidence."""
from dataclasses import dataclass, field
from pathlib import Path
import logging
import numpy as np
import pymupdf
from PIL import Image, ImageDraw
from .image_io import ImagePage, iter_image_pages
from .preprocessing import preprocess_page
from .ocr_engine import TesseractEngine, OCRWord
from .ocr_tables import OCRTable, detect_grid, reconstruct_tables

logger = logging.getLogger(__name__)


@dataclass
class OCRPage:
    """Evidence for one page; all rectangles refer to prepared-image pixels."""
    source_file: str
    page_number: int
    tables: list[OCRTable] = field(default_factory=list)
    blocks: list[OCRWord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float | None = None

    @property
    def requires_manual_review(self):
        """Indicate incomplete or uncertain extraction."""
        return bool(self.warnings)


def _pages(path, max_pixels):
    if Path(path).suffix.lower() != '.pdf':
        yield from iter_image_pages(path)
        return
    with pymupdf.open(path) as document:
        if document.needs_pass:
            raise ValueError('Password-protected PDF')
        for index in range(len(document)):
            try:
                page = document[index]
                if page.rect.width*page.rect.height*(300/72)**2 > max_pixels:
                    raise ValueError('PDF page exceeds raster pixel limit')
                pix = page.get_pixmap(dpi=300, colorspace=pymupdf.csRGB, alpha=False)
                pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height,pix.width,3)
                yield ImagePage(str(path),index+1,pixels,(300,300))
            except Exception as exc:
                yield ImagePage(str(path),index+1,None,warnings=[f'PDF rasterization: {exc}'])


def iter_ocr_pages(path, *, lang='rus+eng', engine=None, debug_dir=None,
                   max_pixels=40_000_000):
    """OCR all pages at 300 DPI; isolate failures and release each image in turn.

    Hybrid PDF pages are rendered once, avoiding duplicate text-layer/OCR data.
    A supplied engine must expose recognize(image, psm=11).
    """
    engine = engine or TesseractEngine(lang=lang)
    for page in _pages(path,max_pixels):
        result = OCRPage(str(path),page.page_number)
        try:
            prepared = preprocess_page(page,max_pixels=max_pixels)
            result.warnings.extend(prepared.warnings)
            if prepared.image is not None:
                regions, clean = detect_grid(prepared.image)
                words = engine.recognize(clean)
                result.tables,result.blocks,notes = reconstruct_tables(regions,words,clean)
                result.warnings.extend(notes)
                if words:
                    result.confidence = sum(w.confidence for w in words)/len(words)
                for word in result.blocks:
                    if word.confidence < .8:
                        result.warnings.append(f'Low confidence text at {word.bbox}: {word.text}')
                if debug_dir:
                    destination = Path(debug_dir)
                    destination.mkdir(parents=True,exist_ok=True)
                    canvas = Image.fromarray(prepared.image).convert('RGB')
                    draw = ImageDraw.Draw(canvas)
                    for table in result.tables:
                        for row in table.cell_bboxes:
                            for box in row:
                                if box:
                                    draw.rectangle(box,outline='red',width=2)
                    canvas.save(destination / f'{Path(path).name}.page-{page.page_number:04d}.png')
        except Exception as exc:
            result.warnings.append(f'OCR page failed: {exc}')
        for warning in result.warnings:
            logger.warning('Page %s: %s',page.page_number,warning)
        yield result


def ocr_document(path, **kwargs):
    """Build Appendix A JSON model, carrying uncertain cells into diagnostics."""
    from norm_importer.schema import NormDocDocument, NormCard, SourceMetadata, SourceFormat
    from norm_importer.grid_mapper import map_raw_grid_to_table_grid
    from norm_importer.header_parser import parse_card_header
    cards, warnings, confidences = [], [], []
    for page in iter_ocr_pages(path,**kwargs):
        warnings.extend(f'Page {page.page_number}: {w}' for w in page.warnings)
        if page.confidence is not None:
            confidences.append(page.confidence)
        # Keep text by OCR line rather than passing each word as a header.
        lines = {}
        for word in page.blocks:
            lines.setdefault(word.line,[]).append(word)
        text = [' '.join(w.text for w in sorted(group,key=lambda w:w.bbox[0]))
                for group in lines.values()]
        for index, table in enumerate(page.tables,1):
            try:
                grid, notes = map_raw_grid_to_table_grid(table.values)
                warnings.extend(f'Page {page.page_number} table {index}: {n}' for n in notes)
                header = parse_card_header(text,fallback_stem=Path(path).stem)
                cards.append(NormCard(card_id=f'{header.card_id}_P{page.page_number}_T{index}',
                    card_title=header.card_title,applicability_conditions=header.applicability,
                    calculation_formula=header.calculation_formula,result_unit=header.result_unit,
                    table_grid=grid))
                if text:
                    warnings.append(f'Page {page.page_number} table {index}: surrounding text requires '
                                    'semantic review (notes parser handoff): ' + ' | '.join(text))
            except Exception as exc:
                warnings.append(f'Page {page.page_number} table {index}: semantic conversion failed: {exc}')
    if not cards:
        raise ValueError('No valid cards extracted: ' + '; '.join(warnings))
    suffix=Path(path).suffix.lower()
    kind = SourceFormat.TIFF if suffix in {'.tif','.tiff'} else SourceFormat.IMAGE
    if suffix == '.pdf':
        from .format_router import inspect_file
        detected=inspect_file(path).source_format
        kind=SourceFormat.PDF_VECTOR if detected=='pdf_text' else SourceFormat(detected)
    return NormDocDocument(source_metadata=SourceMetadata(source_file=str(path),source_format=kind,
        extraction_method='tesseract_tsv',ocr_confidence_avg=sum(confidences)/len(confidences) if confidences else None,
        requires_manual_review=bool(warnings),warnings=warnings),cards=cards)
