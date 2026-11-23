from pathlib import Path
import openpyxl
from docx import Document

from norm_importer.cli import _parse_spreadsheet_file
from norm_importer.notes_parser import (
    clean_ocr_numeric_token,
    clean_ocr_text_block,
    parse_notes_to_rules,
    parse_notes_with_diagnostics,
)
from norm_importer.office_parser import parse_office_file
from norm_importer.schema import ModifierOperation, NormDocDocument, TableGrid


def test_schema_range_list_and_json_roundtrip():
    """Пункт 1 ревью: валидация списка [min, max] и полный цикл строка -> JSON -> повторная валидация."""
    grid_from_list = TableGrid(
        row_param_name="d",
        rows_range=[1],
        values_matrix=[[[0.1, 0.2]]],
    )
    assert grid_from_list.values_matrix == [[[0.1, 0.2]]]

    grid_from_str = TableGrid(
        row_param_name="d",
        rows_range=[1],
        values_matrix=[["0,1–0,2"]],
    )
    dumped = grid_from_str.model_dump_json()
    restored = TableGrid.model_validate_json(dumped)
    assert restored.values_matrix == [[[0.1, 0.2]]]


def test_office_txt_and_docx_end_to_end_notes(tmp_path: Path):
    """Пункт 2 ревью: сквозные тесты TXT и DOCX с примечаниями на add, subtract и multiply."""
    txt_path = tmp_path / "notes_test.txt"
    txt_path.write_text(
        "Карта 10. Сверление\n"
        "| D | 10 |\n"
        "| 5 | 0,5 |\n"
        "Примечания:\n"
        "1. При работе с поджатием центром к времени установки добавлять 0,10 мин\n"
        "2. При работе с местным подъёмником время уменьшать на 0,2 мин\n",
        encoding="utf-8",
    )
    doc_txt = parse_office_file(txt_path)
    rules_txt = doc_txt.cards[0].notes_and_coefficients
    assert len(rules_txt) == 2
    assert rules_txt[0].modifier_operation == ModifierOperation.ADD
    assert rules_txt[0].target_variable == "Tvu"
    assert rules_txt[0].factor == 0.1
    assert rules_txt[0].condition_key == "with_tailstock_center"
    assert rules_txt[1].modifier_operation == ModifierOperation.SUBTRACT
    assert rules_txt[1].factor == 0.2

    docx_path = tmp_path / "notes_test.docx"
    wdoc = Document()
    wdoc.add_paragraph("Карта 11. Точение")
    tbl = wdoc.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "D"
    tbl.cell(0, 1).text = "10"
    tbl.cell(1, 0).text = "5"
    tbl.cell(1, 1).text = "0,8"
    wdoc.add_paragraph("Примечания:")
    wdoc.add_paragraph("1. При сверлении глухих отверстий коэффициент 1,2")
    wdoc.save(str(docx_path))

    doc_docx = parse_office_file(docx_path)
    assert len(doc_docx.cards[0].notes_and_coefficients) == 1
    assert doc_docx.cards[0].notes_and_coefficients[0].factor == 1.2


def test_xlsx_footer_notes_extraction(tmp_path: Path):
    """Пункт 3 ревью: отделение примечаний под таблицей Excel от матрицы значений."""
    xlsx_path = tmp_path / "footer_notes.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Карта 04"
    ws.append(["Диаметр", 10])
    ws.append([5, "0,5"])
    ws.append(["Примечания: При сверлении глухих отверстий коэффициент 1,2", None])
    wb.save(str(xlsx_path))

    doc = _parse_spreadsheet_file(xlsx_path)
    card = doc.cards[0]
    assert card.table_grid.rows_range == [5.0]
    assert card.table_grid.values_matrix == [[0.5]]
    assert len(card.notes_and_coefficients) == 1
    assert card.notes_and_coefficients[0].condition_key == "is_blind_hole"
    assert card.notes_and_coefficients[0].factor == 1.2


def test_ocr_damaged_coefficient_and_ld_priority():
    """Пункты 4 и 5 ревью: OCR '1,З5', невосстановимое число и приоритет L/D > 5 над L/D > 3."""
    rules_ok, warns_ok = parse_notes_with_diagnostics(["При обработке чугуна коэффициент 1,З5"])
    assert len(rules_ok) == 1
    assert rules_ok[0].factor == 1.35

    rules_bad, warns_bad = parse_notes_with_diagnostics(["При обработке чугуна коэффициент 1,??"])
    assert rules_bad == []
    assert len(warns_bad) == 1

    r_gt5 = parse_notes_to_rules(["При глубоких отверстиях L/D > 5 коэффициент 1,2"])
    assert r_gt5[0].condition_key == "l_to_d_ratio_gt_5"

    r_gt3 = parse_notes_to_rules(["При глубоких отверстиях L/D > 3 коэффициент 1,1"])
    assert r_gt3[0].condition_key == "l_to_d_ratio_gt_3"


def test_time_units_conversion_and_unknown_unit():
    """Пункт 6 ревью: перевод секунд/часов в единицу карты и диагностика неизвестных единиц."""
    rules_sec, warns_sec = parse_notes_with_diagnostics(
        ["При обработке чугуна добавлять 30 секунд"],
        result_unit="min",
    )
    assert warns_sec == []
    assert len(rules_sec) == 1
    assert rules_sec[0].modifier_operation == ModifierOperation.ADD
    assert rules_sec[0].factor == 0.5

    rules_hr, warns_hr = parse_notes_with_diagnostics(
        ["При обработке чугуна уменьшать на 0,5 часа"],
        result_unit="min",
    )
    assert warns_hr == []
    assert rules_hr[0].modifier_operation == ModifierOperation.SUBTRACT
    assert rules_hr[0].factor == 30.0

    rules_unk, warns_unk = parse_notes_with_diagnostics(
        ["При обработке чугуна добавлять 30 единиц"],
        result_unit="min",
    )
    assert rules_unk == []
    assert len(warns_unk) == 1
