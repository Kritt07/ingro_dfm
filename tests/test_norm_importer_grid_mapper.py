from pathlib import Path
from typer.testing import CliRunner

from norm_importer.cli import app
from norm_importer.grid_mapper import detect_axis_semantics, map_raw_grid_to_table_grid
from norm_importer.schema import AxisCondition, NormDocDocument, SourceFormat

runner = CliRunner()


def test_detect_axis_semantics():
    """Проверка распознавания имён осей и условий ('до' / 'свыше')."""
    name1, cond1 = detect_axis_semantics("Диаметр сверла D, мм, до", "row_param")
    assert name1 == "diameter_d_mm"
    assert cond1 == AxisCondition.UP_TO

    name2, cond2 = detect_axis_semantics("Длина обработки L, мм, свыше", "col_param")
    assert name2 == "length_l_mm"
    assert cond2 == AxisCondition.OVER

    name3, cond3 = detect_axis_semantics("Масса детали, кг, до", "row_param")
    assert name3 == "mass_kg"
    assert cond3 == AxisCondition.UP_TO


def test_map_raw_grid_multilevel_header():
    """Проверка маппинга таблицы с 2-уровневой шапкой в TableGrid."""
    raw_grid = [
        ["Диаметр D, мм", "Длина отверстия L, мм, до", "", ""],
        ["Диаметр D, мм", "15", "30", "60"],
        ["6", "0,28", "0,45", "-"],
        ["12", "0,32", "0,52", "0,88"],
    ]

    table_grid, warnings = map_raw_grid_to_table_grid(raw_grid)

    assert warnings == []
    assert table_grid.row_param_name == "diameter_d_mm"
    assert table_grid.col_param_name == "length_l_mm"
    assert table_grid.rows_range == [6.0, 12.0]
    assert table_grid.cols_range == [15.0, 30.0, 60.0]
    assert table_grid.values_matrix == [
        [0.28, 0.45, None],
        [0.32, 0.52, 0.88],
    ]


def test_cli_converts_csv_spreadsheet(tmp_path: Path):
    """Проверка сквозной конвертации CSV-таблицы через CLI и grid_mapper."""
    csv_path = tmp_path / "turning_norm.csv"
    csv_path.write_text(
        "Диаметр D, мм;25;50;100\n"
        "20;0,43;0,47;0,56\n"
        "30;0,49;0,52;0,63\n",
        encoding="utf-8",
    )
    out_json = tmp_path / "turning_norm.json"

    result = runner.invoke(app, ["-i", str(csv_path), "-o", str(out_json)])

    assert result.exit_code == 0
    doc = NormDocDocument.model_validate_json(out_json.read_text(encoding="utf-8"))
    assert doc.source_metadata.source_format == SourceFormat.CSV
    assert doc.cards[0].table_grid.row_param_name == "diameter_d_mm"
    assert doc.cards[0].table_grid.values_matrix == [
        [0.43, 0.47, 0.56],
        [0.49, 0.52, 0.63],
    ]
