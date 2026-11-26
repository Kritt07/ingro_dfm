"""B18 semantics: source evidence must survive conversion into final axes."""
from pathlib import Path

import pymupdf
import pytest

from norm_importer.grid_mapper import map_raw_grid_to_table_grid
from norm_importer.schema import AxisCondition
from normdoc2json import extract_pdf


@pytest.mark.parametrize("symbol", ["ØD", "∅D", "⌀D", "D"])
def test_diameter_symbols_are_evidence_not_guessed_from_numbers(symbol):
    grid, warnings = map_raw_grid_to_table_grid([
        [f"{symbol}, мм, до", "L до 10", "L до 20"],
        ["6", "0,2", "0,3"],
    ])
    assert grid.row_param_name == "diameter_d_mm"
    assert grid.col_param_name == "length_l_mm"
    assert grid.cols_range == [10., 20.]
    assert warnings == []


def test_unknown_axes_are_explicitly_reported_without_guessing():
    grid, warnings = map_raw_grid_to_table_grid([["??", "10", ""], ["2", "1", "3"]])
    assert grid.row_param_name == "row_param"
    assert grid.col_param_name == "col_param"
    assert grid.cols_range == [10., "col_2"]
    assert sum("Не определён параметр" in item for item in warnings) == 2
    assert any("Пустой заголовок" in item for item in warnings)


def test_vertical_merge_keeps_numeric_leaf_row_in_header():
    grid, warnings = map_raw_grid_to_table_grid([
        ["D", "L, мм, до", ""],
        ["", "10", "20"],
        ["6", "0,2", "0,3"],
    ], merged_ranges=[(1, 1, 2, 1), (1, 2, 1, 3)])
    assert grid.rows_range == [6.]
    assert grid.cols_range == [10., 20.]
    assert grid.values_matrix == [[.2, .3]]
    assert grid.col_param_name == "length_l_mm"
    assert warnings == []


def test_explicit_spans_do_not_spread_a_group_into_an_unmerged_column():
    grid, warnings = map_raw_grid_to_table_grid([
        ["D", "Group A", "", ""],
        ["D", "L до 10", "L до 20", "L до 30"],
        ["6", "1", "2", "3"],
    ], merged_ranges=[(1, 2, 1, 3)])
    assert grid.cols_range == ["Group A | L до 10", "Group A | L до 20", 30.]
    assert grid.values_matrix == [[1., 2., 3.]]
    assert warnings


@pytest.mark.parametrize("label", ["св. 20 до 40 мм", "от 20 до 40 мм", "20 ≤ L ≤ 40 мм", "40 > L > 20"])
def test_two_bound_conditions_never_collapse_to_last_number(label):
    grid, warnings = map_raw_grid_to_table_grid([["D", label], ["6", "0,2"]])
    assert grid.cols_range == [label]
    assert warnings


@pytest.mark.parametrize("label", ["L < 20", "L ≥ 20", "L >= 20", "L = 20"])
def test_conditions_not_representable_as_up_to_or_over_keep_original(label):
    grid, warnings = map_raw_grid_to_table_grid([["D", label], ["6", "0,2"]])
    assert grid.cols_range == [label]
    assert warnings


def test_mixed_column_conditions_are_not_flattened_to_one_condition():
    grid, warnings = map_raw_grid_to_table_grid([
        ["D", "L до 20", "L свыше 20"], ["6", "1", "2"]])
    assert grid.cols_range == ["L до 20", "L свыше 20"]
    assert any("Разные условия" in item for item in warnings)


def test_conflicting_parameter_evidence_requires_review():
    grid, warnings = map_raw_grid_to_table_grid([["D / L", "L до 20"], ["6", "1"]])
    assert grid.row_param_name == "row_param"
    assert any("Неоднозначный параметр" in item for item in warnings)


def test_explicit_row_conditions_survive_mapping():
    grid, warnings = map_raw_grid_to_table_grid([
        ["D", "L до 20"], ["до 10", "1"], ["свыше 10", "2"]])
    assert grid.rows_range == ["до 10", "свыше 10"]
    assert any("Разные условия строк" in item for item in warnings)
    grid, _ = map_raw_grid_to_table_grid([["D", "L до 20"], ["св. 10", "1"]])
    assert grid.rows_range == [10.]
    assert grid.row_condition == AxisCondition.OVER
    grid, _ = map_raw_grid_to_table_grid([["D не свыше", "L до 20"], ["10", "1"]])
    assert grid.row_condition == AxisCondition.UP_TO
    grid, _ = map_raw_grid_to_table_grid([["Диаметр сверла D", "L до 20"], ["10", "1"]])
    assert grid.row_condition == AxisCondition.UP_TO


@pytest.mark.parametrize("spans", [[(0, 1, 2, 1)], [(1, 1, 3, 1)], [(1, 1, 1, 2)]])
def test_invalid_or_conflicting_spans_are_not_silently_applied(spans):
    with pytest.raises(ValueError):
        map_raw_grid_to_table_grid([["D", "L"], ["6", "1"]], merged_ranges=spans)


@pytest.mark.parametrize("fixture", ["ruled", "borderless"])
def test_real_vector_fixtures_keep_values_and_report_missing_column_parameter(fixture):
    path = Path(__file__).parent / "fixtures" / "pdf_tables" / f"{fixture}.pdf"
    table = extract_pdf(path).pages[0].tables[0]
    grid, warnings = map_raw_grid_to_table_grid(table.values, merged_ranges=table.merged_ranges)
    assert grid.rows_range == [6., 12.]
    assert grid.cols_range == [15., 30.]
    assert grid.row_param_name == "diameter_d_mm"
    # The source has only '15' and '30', with no L/length label. Do not invent L.
    assert grid.col_param_name == "col_param"
    assert any("Не определён параметр оси (столбцы)" in item for item in warnings)
    assert grid.values_matrix == [[.28, None], [0., .88]]


def test_merged_vector_pdf_to_final_axes(tmp_path):
    path = tmp_path / "merged-axis.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        for y in [50, 110, 140, 170]:
            page.draw_line((50, y), (350, y))
        page.draw_line((150, 80), (350, 80))
        for x in [50, 150, 350]:
            page.draw_line((x, 50), (x, 170))
        page.draw_line((250, 80), (250, 170))
        for x, y, value in [(55, 70, "D"), (155, 70, "L"), (155, 100, "15"),
                            (255, 100, "30"), (55, 130, "6"), (155, 130, "0.2"),
                            (255, 130, "0.3"), (55, 160, "12"),
                            (155, 160, "0.4"), (255, 160, "0.5")]:
            page.insert_text((x, y), value)
        doc.save(path)
    table = extract_pdf(path).pages[0].tables[0]
    grid, warnings = map_raw_grid_to_table_grid(table.values, merged_ranges=table.merged_ranges)
    assert grid.row_param_name == "diameter_d_mm"
    assert grid.col_param_name == "length_l_mm"
    assert grid.rows_range == [6., 12.]
    assert grid.cols_range == [15., 30.]
    assert grid.values_matrix == [[.2, .3], [.4, .5]]
    assert warnings == []
