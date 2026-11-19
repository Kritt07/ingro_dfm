from pathlib import Path
from docx import Document

from norm_importer.office_parser import parse_office_file
from norm_importer.schema import SourceFormat


def test_parse_docx_with_merged_headers_and_notes(tmp_path: Path):
    """Проверка парсинга .docx с объединённой шапкой, формулой и примечаниями."""
    docx_path = tmp_path / "karta_04_drilling.docx"
    doc = Document()

    doc.add_paragraph("Карта 04. Сверление отверстий в деталях из стали")
    doc.add_paragraph("Формула расчета: T = (Ttbl + Tvid) * Ktch")

    table = doc.add_table(rows=4, cols=4)
    table.cell(0, 0).text = "Диаметр D, мм"
    table.cell(0, 1).text = "Длина отверстия L, мм, до"
    table.cell(0, 1).merge(table.cell(0, 3))

    table.cell(1, 0).merge(table.cell(0, 0))
    table.cell(1, 1).text = "15"
    table.cell(1, 2).text = "30"
    table.cell(1, 3).text = "60"

    table.cell(2, 0).text = "6"
    table.cell(2, 1).text = "0,28"
    table.cell(2, 2).text = "0,45"
    table.cell(2, 3).text = "-"

    table.cell(3, 0).text = "12"
    table.cell(3, 1).text = "0,32"
    table.cell(3, 2).text = "0,52"
    table.cell(3, 3).text = "0,88"

    doc.add_paragraph("Примечания:")
    doc.add_paragraph("1. При сверлении глухих отверстий табличное время умножать на 1,2.")

    doc.save(str(docx_path))

    result = parse_office_file(docx_path)

    assert result.source_metadata.source_format == SourceFormat.DOCX
    assert result.source_metadata.requires_manual_review is False
    assert len(result.cards) == 1

    card = result.cards[0]
    assert "Сверление" in card.applicability_conditions.operation_type
    assert card.calculation_formula == "(Ttbl + Tvid) * Ktch"
    assert card.table_grid.rows_range == [6.0, 12.0]
    assert card.table_grid.cols_range == [15.0, 30.0, 60.0]
    assert card.table_grid.values_matrix == [
        [0.28, 0.45, None],
        [0.32, 0.52, 0.88],
    ]
    assert len(card.notes_and_coefficients) == 1
    assert card.notes_and_coefficients[0].condition_key == "is_blind_hole"
    assert card.notes_and_coefficients[0].factor == 1.2


def test_parse_txt_pipe_table(tmp_path: Path):
    """Проверка парсинга текстового файла с таблицей с разделителями '|'."""
    txt_path = tmp_path / "karta_turn.txt"
    content = (
        "Карта 36. Точение наружных цилиндрических поверхностей\n"
        "| D_max | 25 | 50 | 100 |\n"
        "| 20    | 0,43 | 0,47 | 0,56 |\n"
        "| 30    | 0,49 | 0,52 | 0,63 |\n"
        "Примечание: для глубоких расточек применять коэффициент 1,3\n"
    )
    txt_path.write_text(content, encoding="utf-8")

    result = parse_office_file(txt_path)

    assert result.source_metadata.source_format == SourceFormat.TXT
    assert result.source_metadata.requires_manual_review is False
    card = result.cards[0]
    assert card.table_grid.rows_range == [20.0, 30.0]
    assert card.table_grid.cols_range == [25.0, 50.0, 100.0]
    assert card.table_grid.values_matrix == [
        [0.43, 0.47, 0.56],
        [0.49, 0.52, 0.63],
    ]
    assert card.notes_and_coefficients[0].factor == 1.3