"""Регрессионные тесты Дня 6 по исправлениям Программиста 2 (BUGS_DAY1_5.md)."""
from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import patch

import pytest
from docx import Document
from pydantic import ValidationError
from typer.testing import CliRunner

from norm_importer.cli import app, collect_input_files
from norm_importer.grid_mapper import detect_axis_semantics, map_raw_grid_to_table_grid
from norm_importer.header_parser import parse_card_header
from norm_importer.notes_parser import parse_notes_with_diagnostics
from norm_importer.office_parser import parse_office_file
from norm_importer.schema import (
    AxisCondition,
    ModifierOperation,
    NoteCoefficientRule,
    TableGrid,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- B01: Запрет NaN / inf / -inf в схеме JSON ---
@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf")])
def test_b01_rejects_non_finite_values_in_matrix_and_ranges(bad_val: float) -> None:
    with pytest.raises(ValidationError):
        TableGrid(
            row_param_name="diameter_d_mm",
            rows_range=[10.0],
            cols_range=[20.0],
            values_matrix=[[bad_val]],
        )

    with pytest.raises(ValidationError):
        TableGrid(
            row_param_name="diameter_d_mm",
            rows_range=[10.0],
            cols_range=[20.0],
            values_matrix=[[[1.0, bad_val]]],
        )

    with pytest.raises(ValidationError):
        NoteCoefficientRule(
            note_id="NOTE_01",
            raw_text="Тест",
            condition_key="is_blind_hole",
            condition_value=True,
            factor=bad_val,
        )


def test_b01_allows_regular_none() -> None:
    grid = TableGrid(
        row_param_name="diameter_d_mm",
        rows_range=[10.0],
        cols_range=[20.0],
        values_matrix=[[None]],
    )
    assert grid.values_matrix == [[None]]


# --- B02: Локальная привязка нескольких карт в офисном документе ---
def test_b02_office_parser_binds_each_card_locally(tmp_path: Path) -> None:
    docx_path = tmp_path / "two_cards.docx"
    doc = Document()

    doc.add_paragraph("Карта 1. Сверление отверстий")
    doc.add_paragraph("Формула: Т = Ттабл * 1,1")
    doc.add_paragraph("Единица измерения: мин")
    t1 = doc.add_table(rows=2, cols=2)
    t1.cell(0, 0).text = "Диаметр D, мм, до"
    t1.cell(0, 1).text = "10"
    t1.cell(1, 0).text = "5"
    t1.cell(1, 1).text = "0,25"
    doc.add_paragraph("Примечание: Для глухих отверстий коэффициент 1,2")

    doc.add_paragraph("Карта 2. Фрезерование пазов")
    doc.add_paragraph("Формула: Т = Ттабл * 1,5")
    doc.add_paragraph("Единица измерения: ч")
    t2 = doc.add_table(rows=2, cols=2)
    t2.cell(0, 0).text = "Ширина B, мм, до"
    t2.cell(0, 1).text = "20"
    t2.cell(1, 0).text = "6"
    t2.cell(1, 1).text = "0,40"
    doc.add_paragraph("Примечание: При обработке чугуна коэффициент 0,85")

    doc.save(str(docx_path))

    parsed = parse_office_file(docx_path)
    assert len(parsed.cards) == 2

    c1, c2 = parsed.cards
    assert c1.applicability_conditions.operation_type == "Сверление"
    assert c1.calculation_formula == "Ttbl * 1.1"
    assert c1.result_unit == "min"
    assert len(c1.notes_and_coefficients) == 1
    assert c1.notes_and_coefficients[0].condition_key == "is_blind_hole"

    assert c2.applicability_conditions.operation_type == "Фрезерование"
    assert c2.calculation_formula == "Ttbl * 1.5"
    assert c2.result_unit == "hour"
    assert len(c2.notes_and_coefficients) == 1
    assert c2.notes_and_coefficients[0].condition_key == "material_group"
    assert c2.notes_and_coefficients[0].condition_value == "cast_iron"


# --- B04: Очистка временного каталога LibreOffice ---
def test_b04_libreoffice_temp_dir_cleaned_on_success_and_failure(tmp_path: Path) -> None:
    fake_doc = tmp_path / "sample.doc"
    fake_doc.write_bytes(b"dummy")

    created_dirs: list[Path] = []
    real_tempdir = __import__("tempfile").TemporaryDirectory

    class SpyTempDir:
        def __init__(self, *args, **kwargs):
            self._td = real_tempdir(*args, **kwargs)
            created_dirs.append(Path(self._td.name))

        def __enter__(self):
            return self._td.__enter__()

        def __exit__(self, exc_type, exc_val, exc_tb):
            return self._td.__exit__(exc_type, exc_val, exc_tb)

    with patch("norm_importer.office_parser.shutil.which", return_value="/usr/bin/soffice"), \
         patch("norm_importer.office_parser.tempfile.TemporaryDirectory", SpyTempDir), \
         patch("norm_importer.office_parser.subprocess.run", side_effect=RuntimeError("LO crash")):
        res = parse_office_file(fake_doc)
        assert res.source_metadata.requires_manual_review is True

    assert created_dirs and not created_dirs[0].exists()


# --- B05, B06, B07, B08, B09, B18: Сетка и оси ---
def test_b05_preserves_row_with_missing_label_and_warns() -> None:
    raw = [
        ["D, мм", "10", "20"],
        [None, "2", "3.5"],
        ["5", "4", "5.0"],
    ]
    grid, warnings = map_raw_grid_to_table_grid(raw)
    assert len(grid.rows_range) == 2
    assert grid.values_matrix[0] == [2.0, 3.5]
    assert any("метка" in w.lower() for w in warnings)


def test_b06_keeps_non_empty_column_with_blank_header_and_drops_empty_tail() -> None:
    raw = [
        ["D, мм", "10", "", ""],
        ["2", "0.5", "0.9", ""],
    ]
    grid, warnings = map_raw_grid_to_table_grid(raw)
    assert len(grid.cols_range) == 2
    assert grid.values_matrix == [[0.5, 0.9]]
    assert any("пустой заголовок" in w.lower() for w in warnings)


def test_b07_detect_axis_semantics_negation_and_sv() -> None:
    _, cond_not_more = detect_axis_semantics("Диаметр не более 10 мм", "row_param")
    _, cond_sv = detect_axis_semantics("Длина св. 10 мм", "col_param")
    assert cond_not_more == AxisCondition.UP_TO
    assert cond_sv == AxisCondition.OVER


def test_b08_preserves_interval_axis_labels_without_truncation() -> None:
    raw = [
        ["Диаметр D, мм", "5–10", "10–20"],
        ["2–4", "0.15", "0.25"],
    ]
    grid, warnings = map_raw_grid_to_table_grid(raw)
    assert grid.cols_range == ["5–10", "10–20"]
    assert grid.rows_range == ["2–4"]
    assert any("интервал" in w.lower() for w in warnings)


def test_b09_preserves_numeric_zero_in_cells_and_axes() -> None:
    raw = [
        ["Припуск t, мм", 0, 1.5],
        [0, 0, 0.45],
    ]
    grid, _ = map_raw_grid_to_table_grid(raw)
    assert grid.rows_range == [0.0]
    assert grid.cols_range == [0.0, 1.5]
    assert grid.values_matrix == [[0.0, 0.45]]


def test_b18_multilevel_photo_headers_expected_fixture() -> None:
    expected_path = REPO_ROOT / "tests" / "fixtures" / "phone_photos" / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    g1, _ = map_raw_grid_to_table_grid(expected["card01"]["values"])
    assert g1.row_param_name == "diameter_d_mm"
    assert g1.rows_range == [2.0, 3.0, 5.0, 8.0, 10.0, 12.0, 16.0, 20.0]
    assert g1.col_param_name == "length_l_mm"
    assert g1.cols_range == [10.0, 20.0, 30.0, 50.0]

    g2, _ = map_raw_grid_to_table_grid(expected["card02"]["values"])
    assert g2.row_param_name == "width_b_mm"
    assert g2.rows_range == [3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 16.0]
    assert g2.cols_range == [
        "Открытый паз | L ≤ 20 мм",
        "Открытый паз | 20 < L ≤ 40 мм",
        "Закрытый паз | L ≤ 20 мм",
        "Закрытый паз | 20 < L ≤ 40 мм",
    ]


# --- B12, B13: Формулы с кириллицей и единицы измерения ---
def test_b12_b13_cyrillic_formula_and_explicit_units() -> None:
    header = parse_card_header(
        [
            "Карта 1. Точение",
            "Формула: Т = Ттабл * 1,2",
            "Единица измерения: ч",
        ],
        fallback_stem="test",
    )
    assert header.calculation_formula == "Ttbl * 1.2"
    assert header.result_unit == "hour"


# --- B14, B15, B16: Отрицания, составные условия и последовательные действия ---
def test_b14_negated_blind_hole_not_inverted() -> None:
    rules, warnings = parse_notes_with_diagnostics(
        ["Для неглухих отверстий коэффициент 1,2"]
    )
    assert len(rules) == 1
    assert rules[0].condition_key != "is_blind_hole"
    assert any("отрицательное условие" in w.lower() for w in warnings)


def test_b15_compound_condition_preserves_hole_and_material() -> None:
    rules, warnings = parse_notes_with_diagnostics(
        ["Для глухих отверстий в чугуне коэффициент 1,2"]
    )
    assert len(rules) == 1
    assert rules[0].condition_key == "compound_condition"
    assert "is_blind_hole=True" in str(rules[0].condition_value)
    assert "material_group=cast_iron" in str(rules[0].condition_value)
    assert any("составное условие" in w.lower() for w in warnings)


def test_b16_chained_actions_preserve_order() -> None:
    rules, _ = parse_notes_with_diagnostics(
        ["При глубине свыше 3D время умножать на 1,2 и добавлять 2 мин"],
        result_unit="min",
    )
    assert len(rules) == 2
    assert rules[0].modifier_operation == ModifierOperation.MULTIPLY
    assert rules[0].factor == pytest.approx(1.2)
    assert rules[1].modifier_operation == ModifierOperation.ADD
    assert rules[1].factor == pytest.approx(2.0)


# --- B10, B17: Подключение PDF и исключение .debug в CLI ---
def test_b10_cli_vector_pdf_not_stub(tmp_path: Path) -> None:
    ruled_pdf = REPO_ROOT / "tests" / "fixtures" / "pdf_tables" / "ruled.pdf"
    out_json = tmp_path / "ruled.json"
    runner = CliRunner()
    res = runner.invoke(app, ["-i", str(ruled_pdf), "-o", str(out_json)])
    assert res.exit_code in (0, 1)
    assert out_json.exists()

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["source_metadata"]["extraction_method"] == "normdoc2json.pdf"
    assert payload["cards"][0]["table_grid"]["values_matrix"] != [[0.0]]


def test_b17_collect_input_files_ignores_debug_dirs(tmp_path: Path) -> None:
    src_img = tmp_path / "card.png"
    src_img.write_bytes(b"fake")
    dbg_dir = tmp_path / "card.png.debug"
    dbg_dir.mkdir()
    (dbg_dir / "card.png.page-0001.png").write_bytes(b"fake_debug")

    collected = collect_input_files(tmp_path)
    assert collected == [src_img]
