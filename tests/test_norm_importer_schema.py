import pytest
from pydantic import ValidationError

from norm_importer.schema import (
    ApplicabilityConditions,
    NormCard,
    NormDocDocument,
    SourceFormat,
    SourceMetadata,
    TableGrid,
)


def test_appendix_a_reference_document():
    """Проверка эталонного JSON-документа из Приложения А ТЗ."""
    payload = {
        "schema_version": "1.0",
        "source_metadata": {
            "source_file": "OUNV_Part1_Turning.pdf",
            "source_format": "pdf_scanned",
            "page_number": 42,
            "extraction_method": "ocr_paddle_v2",
            "ocr_confidence_avg": 0.94,
            "requires_manual_review": False,
            "warnings": [],
        },
        "cards": [
            {
                "card_id": "OUNV_MPC1_CARD_04",
                "card_title": "Карта 04. Неполное штучное время. Сверление отверстий, Rz80, 14...12 квалитет",
                "applicability_conditions": {
                    "operation_type": "Сверление",
                    "production_type": "Единичное и мелкосерийное",
                    "material_group": "Чугун серый, HB 1.76-2.15 ГПа",
                    "equipment_filter": "Вертикально- и радиально-сверлильные станки",
                    "tool_material": "Р6М5",
                },
                "calculation_formula": "(Ttbl + Tvid) * Ktch * Kkotv * Kgest",
                "result_unit": "min",
                "table_grid": {
                    "row_param_name": "diameter_d_mm",
                    "row_condition": "up_to",
                    "col_param_name": "length_l_mm",
                    "col_condition": "up_to",
                    "rows_range": [2.0, 3.0],
                    "cols_range": [10.0, 15.0, 20.0],
                    "values_matrix": [
                        [0.22, 0.48, None],
                        [0.20, 0.45, 0.48],
                    ],
                },
                "notes_and_coefficients": [
                    {
                        "note_id": "NOTE_01",
                        "raw_text": "При сверлении глухих отверстий табличное время применять с коэффициентом 1,2",
                        "condition_key": "is_blind_hole",
                        "condition_value": True,
                        "modifier_operation": "multiply",
                        "target_variable": "Ttbl",
                        "factor": 1.2,
                    }
                ],
            }
        ],
    }

    doc = NormDocDocument.model_validate(payload)
    assert doc.schema_version == "1.0"
    assert doc.source_metadata.source_format == SourceFormat.PDF_SCANNED
    assert len(doc.cards) == 1
    assert doc.cards[0].table_grid.values_matrix[0][2] is None
    assert doc.cards[0].notes_and_coefficients[0].factor == 1.2


def test_table_grid_normalization_russian_locale_and_ranges():
    """Проверка нормализации десятичных запятых, прочерков и интервалов."""
    grid = TableGrid(
        row_param_name="diameter_d_mm",
        col_param_name="length_l_mm",
        rows_range=[6.0, 12.0],
        cols_range=[15.0, 30.0, 60.0, 120.0],
        values_matrix=[
            ["0,28", "0,45", "-", "0,22–0,28"],
            ["0,32", "—", "0.88", "1,20 - 1,40"],
        ],
    )

    assert grid.values_matrix[0] == [0.28, 0.45, None, [0.22, 0.28]]
    assert grid.values_matrix[1] == [0.32, None, 0.88, [1.2, 1.4]]


def test_table_grid_1d_center_drill():
    """Проверка одноосной таблицы (центрование по диаметру без столбцов)."""
    grid = TableGrid(
        row_param_name="diameter_d_mm",
        col_param_name=None,
        rows_range=[10.0, 25.0, 50.0],
        cols_range=[],
        values_matrix=[
            ["0,14"],
            ["0,22"],
            ["0,34"],
        ],
    )

    assert grid.values_matrix == [[0.14], [0.22], [0.34]]


def test_table_grid_dimension_mismatch_raises_error():
    """Проверка строгой валидации размерности values_matrix."""
    with pytest.raises(ValidationError, match="Несовпадение числа строк"):
        TableGrid(
            row_param_name="diameter_d_mm",
            col_param_name="length_l_mm",
            rows_range=[6.0, 12.0],
            cols_range=[15.0, 30.0],
            values_matrix=[[0.28, 0.45]],
        )

    with pytest.raises(ValidationError, match="Несовпадение числа столбцов в строке 1"):
        TableGrid(
            row_param_name="diameter_d_mm",
            col_param_name="length_l_mm",
            rows_range=[6.0, 12.0],
            cols_range=[15.0, 30.0, 60.0],
            values_matrix=[
                [0.28, 0.45, 0.78],
                [0.32, 0.52],
            ],
        )


def test_json_file_serialization(tmp_path):
    """Проверка выгрузки в UTF-8 JSON без BOM и обратного чтения."""
    doc = NormDocDocument(
        source_metadata=SourceMetadata(
            source_file="test.xlsx",
            source_format=SourceFormat.XLSX,
            extraction_method="openpyxl",
        ),
        cards=[
            NormCard(
                card_id="CARD_TEST",
                card_title="Тестовая карта",
                applicability_conditions=ApplicabilityConditions(operation_type="Фрезерование"),
                calculation_formula="Ttbl",
                table_grid=TableGrid(
                    row_param_name="D",
                    rows_range=[10.0],
                    cols_range=[20.0],
                    values_matrix=[["1,55"]],
                ),
            )
        ],
    )

    out_path = tmp_path / "result.json"
    doc.to_json_file(str(out_path))

    raw_bytes = out_path.read_bytes()
    assert not raw_bytes.startswith(b"\xef\xbb\xbf")

    restored = NormDocDocument.model_validate_json(raw_bytes.decode("utf-8"))
    assert restored.cards[0].table_grid.values_matrix == [[1.55]]
