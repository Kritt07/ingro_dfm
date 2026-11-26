"""I01: a page with two cards must not share their correction factors."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from normdoc2json.ocr import OCRPage, ocr_document
from normdoc2json.ocr_engine import OCRWord
from normdoc2json.ocr_tables import OCRTable
from normdoc2json.pdf_types import TextBlock, PDFPage, PDFTable, PDFExtraction
from normdoc2json.table_context import assign_table_context, ocr_text_lines
from norm_importer.cli import _enrich_ocr_document_notes, _parse_vector_pdf_file
from norm_importer.schema import SourceFormat


NOTE_A = 'При обработке чугуна коэффициент 1,2'
NOTE_B = 'При обработке алюминия коэффициент 0,8'
GRID = [['Диаметр D, мм', 'L до 10 мм'], ['5', '0,28']]


def two_cards(layout):
    if layout == 'vertical':
        boxes = [(0, 30, 200, 200), (0, 330, 200, 500)]
        titles = [(0, 0, 200, 20), (0, 270, 200, 290)]
        notes = [(0, 210, 200, 230), (0, 510, 200, 530)]
    else:
        boxes = [(0, 30, 200, 200), (300, 30, 500, 200)]
        titles = [(0, 0, 200, 20), (300, 0, 500, 20)]
        notes = [(0, 210, 200, 230), (300, 210, 500, 230)]
    blocks = [TextBlock(titles[0], 'Карта 01. Сверление'),
              TextBlock(titles[1], 'Карта 02. Фрезерование'),
              TextBlock(notes[0], NOTE_A), TextBlock(notes[1], NOTE_B)]
    return boxes, blocks


@pytest.mark.parametrize('layout', ['vertical', 'columns'])
@pytest.mark.parametrize('route', ['ocr', 'vector'])
def test_each_card_gets_only_local_factor(monkeypatch, layout, route):
    boxes, blocks = two_cards(layout)
    if route == 'ocr':
        # Same OCR line id for parallel columns must not merge card contexts.
        words = [OCRWord(b.text, b.bbox, .99, (1, 1, int(b.bbox[1]))) for b in blocks]
        page = OCRPage('two.png', 1, [OCRTable(b, GRID, [], []) for b in boxes], words)
        monkeypatch.setattr('normdoc2json.ocr.iter_ocr_pages', lambda *a, **k: iter([page]))
        doc = _enrich_ocr_document_notes(ocr_document('two.png'))
    else:
        page = PDFPage(1, 'pdf_text', blocks, [PDFTable(1, b, GRID, []) for b in boxes])
        monkeypatch.setattr('normdoc2json.pdf.extract_pdf',
                            lambda *a: PDFExtraction('two.pdf', 'pdf_text', [page]))
        doc = _parse_vector_pdf_file(Path('two.pdf'), SourceFormat.PDF_VECTOR)
    assert len(doc.cards) == 2
    assert [[rule.factor for rule in card.notes_and_coefficients] for card in doc.cards] == [[1.2], [.8]]
    assert [c.applicability_conditions.operation_type for c in doc.cards] == ['Сверление', 'Фрезерование']


def test_next_title_cuts_off_previous_notes_and_includes_next_preamble():
    boxes, blocks = two_cards('vertical')
    blocks.append(TextBlock((0, 300, 200, 320), 'При глухих отверстиях коэффициент 1,1'))
    contexts, warnings = assign_table_context([SimpleNamespace(bbox=b) for b in boxes], blocks)
    assert warnings == []
    assert contexts[0].note_lines == [NOTE_A]
    assert contexts[1].header_lines == ['Карта 02. Фрезерование', 'При глухих отверстиях коэффициент 1,1']
    assert NOTE_A not in contexts[1].header_lines


@pytest.mark.parametrize('route', ['ocr', 'vector'])
def test_wide_ambiguous_note_is_not_applied_to_either_card(monkeypatch, route):
    boxes, blocks = two_cards('columns')
    blocks = blocks[:2] + [TextBlock((0, 210, 500, 230), NOTE_A)]
    if route == 'ocr':
        page = OCRPage('two.png', 1, [OCRTable(b, GRID, [], []) for b in boxes],
                       [OCRWord(b.text, b.bbox, .99, (i, 1, 1)) for i, b in enumerate(blocks)])
        monkeypatch.setattr('normdoc2json.ocr.iter_ocr_pages', lambda *a, **k: iter([page]))
        doc = _enrich_ocr_document_notes(ocr_document('two.png'))
    else:
        page = PDFPage(1, 'pdf_text', blocks, [PDFTable(1, b, GRID, []) for b in boxes])
        monkeypatch.setattr('normdoc2json.pdf.extract_pdf',
                            lambda *a: PDFExtraction('two.pdf', 'pdf_text', [page]))
        doc = _parse_vector_pdf_file(Path('two.pdf'), SourceFormat.PDF_VECTOR)
    assert len(doc.cards) == 2
    assert all(not card.notes_and_coefficients for card in doc.cards)
    assert doc.source_metadata.requires_manual_review
    assert any('ambiguous table ownership' in w and NOTE_A in w for w in doc.source_metadata.warnings)


def test_unmatched_card_id_does_not_fall_back_to_other_cards_notes(monkeypatch):
    boxes, blocks = two_cards('vertical')
    page = OCRPage('two.png', 1, [OCRTable(b, GRID, [], []) for b in boxes],
                   [OCRWord(b.text, b.bbox, .99, (i, 1, 1)) for i, b in enumerate(blocks)])
    monkeypatch.setattr('normdoc2json.ocr.iter_ocr_pages', lambda *a, **k: iter([page]))
    doc = ocr_document('two.png')
    doc.cards[1].card_id = 'UNKNOWN_CARD'
    _enrich_ocr_document_notes(doc)
    assert [rule.factor for rule in doc.cards[0].notes_and_coefficients] == [1.2]
    assert doc.cards[1].notes_and_coefficients == []


def test_text_without_geometry_is_retained_only_in_diagnostics():
    contexts, warnings = assign_table_context([SimpleNamespace(bbox=(0, 20, 200, 100))],
                                             [SimpleNamespace(text=NOTE_A, bbox=None)])
    assert contexts[0].header_lines == contexts[0].note_lines == []
    assert any('missing coordinates' in w and NOTE_A in w for w in warnings)


def test_gap_without_next_card_title_does_not_guess_note_owner():
    boxes, _ = two_cards('vertical')
    contexts, warnings = assign_table_context([SimpleNamespace(bbox=b) for b in boxes],
                                             [TextBlock((0, 250, 200, 270), NOTE_A)])
    assert all(not c.header_lines and not c.note_lines for c in contexts)
    assert any('no card boundary' in w and NOTE_A in w for w in warnings)


def test_explicit_other_card_reference_is_not_assigned_by_proximity():
    contexts, warnings = assign_table_context([SimpleNamespace(bbox=(0, 20, 200, 100))],
        [TextBlock((0, 110, 200, 130), 'К карте 2: ' + NOTE_A)])
    assert contexts[0].note_lines == []
    assert any('explicit/shared reference' in w for w in warnings)


def test_multiline_ocr_reading_order_and_column_split():
    words = [OCRWord('коэффициент 1,2', (40, 100, 100, 110), .99, (1, 1, 1)),
             OCRWord('Чугун', (0, 100, 35, 110), .99, (1, 1, 1)),
             OCRWord('Алюминий', (300, 100, 350, 110), .99, (1, 1, 1))]
    assert [b.text for b in ocr_text_lines(words)] == ['Чугун коэффициент 1,2', 'Алюминий']
