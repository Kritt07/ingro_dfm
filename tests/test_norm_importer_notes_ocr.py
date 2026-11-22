from norm_importer.notes_parser import (
    clean_ocr_numeric_token,
    clean_ocr_text_block,
    parse_notes_to_rules,
)
from norm_importer.schema import ModifierOperation, TableGrid


def test_clean_ocr_numeric_artifacts():
    """Проверка исправления типичных OCR-ошибок в числах (О->0, З->3, Б->6, пробелы)."""
    assert clean_ocr_numeric_token("О,45") == "0.45"
    assert clean_ocr_numeric_token("0, 45") == "0.45"
    assert clean_ocr_numeric_token("1,З5") == "1.35"
    assert clean_ocr_numeric_token("0;Б8") == "0.68"
    assert clean_ocr_numeric_token("l,25") == "1.25"
    assert clean_ocr_numeric_token("—") == "—"


def test_table_grid_auto_cleans_ocr_cells():
    """Интеграционный тест: TableGrid автоматически чистит OCR-артефакты в ячейках."""
    grid = TableGrid(
        row_param_name="diameter_d_mm",
        col_param_name="length_l_mm",
        rows_range=[6.0, 12.0],
        cols_range=[15.0, 30.0],
        values_matrix=[
            ["О,28", "0, 45"],
            ["1,З5", "0;Б8"],
        ],
    )
    assert grid.values_matrix == [
        [0.28, 0.45],
        [1.35, 0.68],
    ]


def test_parse_notes_multiply_add_subtract():
    """Проверка разбора примечаний с умножением, сложением и вычитанием времени."""
    notes = [
        "1. При сверлении глухих отверстий табличное время применять с коэффициентом 1,2",
        "2. При работе с поджатием центром задней бабки к времени установки добавлять 0,10 мин",
        "3. Работа с местным подъёмником: время уменьшать на 1,5 мин",
        "4. Установка тонкостенных деталей или сварных конструкций — K = О,85",
    ]

    rules = parse_notes_to_rules(notes)
    assert len(rules) == 4

    r0, r1, r2, r3 = rules

    assert r0.condition_key == "is_blind_hole"
    assert r0.modifier_operation == ModifierOperation.MULTIPLY
    assert r0.target_variable == "Ttbl"
    assert r0.factor == 1.2

    assert r1.condition_key == "with_tailstock_center"
    assert r1.modifier_operation == ModifierOperation.ADD
    assert r1.target_variable == "Tvu"
    assert r1.factor == 0.10

    assert r2.condition_key == "local_hoist"
    assert r2.modifier_operation == ModifierOperation.SUBTRACT
    assert r2.factor == 1.5

    assert r3.condition_key == "is_thin_walled"
    assert r3.modifier_operation == ModifierOperation.MULTIPLY
    assert r3.factor == 0.85

def test_clean_ocr_text_block():
    """Проверка очистки OCR-ошибок в текстовых примечаниях."""
    raw = "При обработке чугуна применять K = О,85 или коэффициент 1,З"
    cleaned = clean_ocr_text_block(raw)
    assert "0.85" in cleaned or "0,85" in cleaned
    assert "1.3" in cleaned
