"""Проверить извлечение таблиц и восстановление объединений второго дня."""

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
import xlwt

from normdoc2json import InspectionError, extract_spreadsheet


@pytest.mark.parametrize("extension", ["xlsx", "xls"])
def test_merged_multilevel_headers_and_coordinates(tmp_path, extension):
    path = tmp_path / f"book.{extension}"
    if extension == "xlsx":
        book = Workbook()
        sheet = book.active
        sheet.title = "Нормы"
        sheet.merge_cells("B2:C2")
        sheet["B2"] = "Время"
        sheet.merge_cells("A3:A4")
        sheet["A3"] = "Диаметр"
        sheet["B3"], sheet["C3"] = 10, 20
        sheet["B4"], sheet["C4"] = 0, 0.45
        sheet["A6"] = "Примечание: коэффициент 1,2"
        book.create_sheet("Второй")["A1"] = "Ещё таблица"
    else:
        book = xlwt.Workbook()
        sheet = book.add_sheet("Нормы")
        sheet.write_merge(1, 1, 1, 2, "Время")
        sheet.write_merge(2, 3, 0, 0, "Диаметр")
        for row, col, value in [(2, 1, 10), (2, 2, 20), (3, 1, 0), (3, 2, .45),
                                (5, 0, "Примечание: коэффициент 1,2")]:
            sheet.write(row, col, value)
        book.add_sheet("Второй").write(0, 0, "Ещё таблица")
    book.save(str(path))
    result = extract_spreadsheet(path)
    assert not result.requires_manual_review
    assert len(result.sheets) == 2
    sheet = result.sheets[0]
    assert sheet.values == [[None, None, None], [None, "Время", "Время"],
                            ["Диаметр", 10, 20], ["Диаметр", 0, .45],
                            [None, None, None], ["Примечание: коэффициент 1,2", None, None]]
    assert set(sheet.merged_ranges) == {(2, 2, 2, 3), (3, 1, 4, 1)}


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1251", "utf-16"])
@pytest.mark.parametrize("delimiter", [";", "\t", ","])
def test_csv_encoding_quotes_and_empty_cells(tmp_path, encoding, delimiter):
    import csv

    path = tmp_path / "table.csv"
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerows([["Диаметр", "Время", "Примечание"],
                          ["10", "0,45", "Текст\nна двух строках"], ["20", "", ""]])
    result = extract_spreadsheet(path)
    assert result.sheets[0].values[1] == ["10", "0,45", "Текст\nна двух строках"]
    assert result.sheets[0].values[2] == ["20", None, None]


def test_formula_without_cache_and_error_are_reported(tmp_path, caplog):
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "=1+2"
    sheet["B1"] = "#DIV/0!"
    sheet["C1"] = datetime(2026, 1, 2)
    path = tmp_path / "formulas.xlsx"
    book.save(path)
    result = extract_spreadsheet(path)
    assert result.requires_manual_review
    assert len(result.warnings) == 2
    assert result.sheets[0].formulas == {(1, 1): "=1+2"}
    assert result.sheets[0].values[0] == [None, None, datetime(2026, 1, 2)]
    assert "A1" in caplog.text


def test_csv_override_and_ragged_rows(tmp_path):
    path = tmp_path / "ragged.csv"
    path.write_text("a|b|c\n1\n\n2|3", encoding="utf-8")
    result = extract_spreadsheet(path, delimiter="|")
    assert result.sheets[0].values == [["a", "b", "c"], ["1", None, None],
                                       [None, None, None], ["2", "3", None]]


def test_reject_invalid_input(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"PKbroken")
    with pytest.raises(InspectionError):
        extract_spreadsheet(path)
    with pytest.raises(InspectionError):
        extract_spreadsheet(tmp_path / "absent.csv")


def test_existing_excel_fixture():
    result = extract_spreadsheet(Path(__file__).parent / "fixtures/router/turning.xlsx")
    assert result.sheets
    assert any(value is not None for sheet in result.sheets for row in sheet.values for value in row)


def test_cached_formula(tmp_path):
    from zipfile import ZipFile
    from xml.etree import ElementTree

    path = tmp_path / "cached.xlsx"
    book = Workbook()
    book.active["A1"] = "=1+2"
    book.save(path)
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    xml = ElementTree.fromstring(entries["xl/worksheets/sheet1.xml"])
    xml.find(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v").text = "3"
    entries["xl/worksheets/sheet1.xml"] = ElementTree.tostring(xml)
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    result = extract_spreadsheet(path)
    assert result.sheets[0].values == [[3]]
    assert result.sheets[0].formulas == {(1, 1): "=1+2"}
    assert not result.requires_manual_review


def test_sheet_failure_continues(tmp_path, monkeypatch):
    from openpyxl.worksheet.worksheet import Worksheet

    book = Workbook()
    book.active.title = "Broken"
    book.create_sheet("Good")["A1"] = 42
    path = tmp_path / "partial.xlsx"
    book.save(path)
    original = Worksheet.iter_rows

    def fail_first(self, *args, **kwargs):
        if self.title == "Broken":
            raise ValueError("test sheet error")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Worksheet, "iter_rows", fail_first)
    result = extract_spreadsheet(path)
    assert result.requires_manual_review
    assert [sheet.name for sheet in result.sheets] == ["Good"]
    assert result.sheets[0].values == [[42]]
