"""Извлекать сетки электронных таблиц для последующего семантического разбора."""

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .format_router import InspectionError, inspect_file

logger = logging.getLogger(__name__)


@dataclass
class SheetGrid:
    """Хранить лист с координатами от единицы и включительными границами слияний.

    values начинается в A1, включая пустые строки и столбцы до данных.
    merged_ranges содержит (первая строка, первый столбец, последняя строка,
    последний столбец). formulas хранит исходные формулы по (строка, столбец).
    """

    name: str
    values: list[list[object]]
    merged_ranges: list[tuple[int, int, int, int]] = field(default_factory=list)
    formulas: dict[tuple[int, int], str] = field(default_factory=dict)


@dataclass
class SpreadsheetExtraction:
    """Хранить извлечённые листы и диагностику для source_metadata."""

    source_file: str
    source_format: str
    sheets: list[SheetGrid] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def requires_manual_review(self) -> bool:
        """Сообщить о наличии сомнительных или потерянных данных."""
        return bool(self.warnings)

    def warn(self, message: str) -> None:
        """Сохранить предупреждение и передать его в журнал приложения."""
        self.warnings.append(message)
        logger.warning(message)


def _restore_merges(sheet: SheetGrid) -> None:
    """Восстановить значения объединений и прямоугольную форму сетки."""
    height = max([len(sheet.values)] + [m[2] for m in sheet.merged_ranges])
    width = max([len(row) for row in sheet.values] + [m[3] for m in sheet.merged_ranges] + [0])
    sheet.values.extend([] for _ in range(height - len(sheet.values)))
    for row in sheet.values:
        row.extend([None] * (width - len(row)))
    for first_row, first_col, last_row, last_col in sheet.merged_ranges:
        value = sheet.values[first_row - 1][first_col - 1]
        for row in range(first_row - 1, last_row):
            for col in range(first_col - 1, last_col):
                sheet.values[row][col] = value


def extract_spreadsheet(path: str | Path, *, delimiter: str | None = None) -> SpreadsheetExtraction:
    """Извлечь XLSX, XLS или CSV с восстановлением объединённых ячеек.

    Тип и кодировка определяются маршрутизатором. Для неоднозначного CSV
    можно явно передать разделитель. Формулы XLSX читаются из сохранённого
    кэша, отсутствие результата помечается для ручной проверки.
    Ошибка листа сохраняется в warnings, обработка остальных продолжается.
    Ошибка открытия книги или неподдерживаемый формат вызывают InspectionError.
    """
    inspection = inspect_file(path)
    result = SpreadsheetExtraction(str(path), inspection.source_format)
    readers = {"xlsx": _read_xlsx, "xls": _read_xls, "ods": _read_ods}
    try:
        if inspection.source_format == "csv":
            _read_csv(Path(path), inspection.encoding, delimiter, result)
        elif inspection.source_format in readers:
            readers[inspection.source_format](Path(path), result)
        else:
            raise InspectionError(f"Unsupported spreadsheet format: {inspection.source_format}")
    except InspectionError:
        raise
    except Exception as exc:
        raise InspectionError(f"Cannot extract {path}: {exc}") from exc
    if not result.sheets:
        result.warn("Не извлечено ни одного листа с данными")
    return result


def _read_csv(
    path: Path,
    encoding: str | None,
    delimiter: str | None,
    result: SpreadsheetExtraction,
) -> None:
    with path.open(encoding=encoding, newline="") as stream:
        sample = stream.read(65536)
        stream.seek(0)
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
            except csv.Error:
                delimiter = ";"
                result.warn("Разделитель CSV не определён, выбран ';'; проверьте сетку")
        rows: list[list[object]] = [
            [value if value != "" else None for value in row]
            for row in csv.reader(stream, delimiter=delimiter, strict=True)
        ]
    sheet = SheetGrid(path.stem, rows)
    _restore_merges(sheet)
    result.sheets.append(sheet)


def _read_xlsx(path: Path, result: SpreadsheetExtraction) -> None:
    from openpyxl import load_workbook

    book = load_workbook(path, data_only=False)
    try:
        cached = load_workbook(path, data_only=True)
        try:
            for source in book.worksheets:
                try:
                    sheet = SheetGrid(source.title, [])
                    cached_sheet = cached[source.title]
                    for row_index, row in enumerate(source.iter_rows(), start=1):
                        values: list[object] = []
                        for col_index, cell in enumerate(row, start=1):
                            cached_cell = cached_sheet.cell(row_index, col_index)
                            value = cell.value
                            if cell.data_type == "f":
                                sheet.formulas[(row_index, col_index)] = str(value)
                                value = cached_cell.value
                                if value is None:
                                    result.warn(f"{source.title}!{cell.coordinate}: нет кэша формулы")
                            if cell.data_type == "e" or cached_cell.data_type == "e":
                                result.warn(f"{source.title}!{cell.coordinate}: ошибка Excel {value}")
                                value = None
                            values.append(value)
                        sheet.values.append(values)
                    sheet.merged_ranges = [(m.min_row, m.min_col, m.max_row, m.max_col)
                                           for m in source.merged_cells.ranges]
                    _restore_merges(sheet)
                    result.sheets.append(sheet)
                except Exception as exc:
                    result.warn(f"Лист {source.title}: {exc}")
        finally:
            cached.close()
    finally:
        book.close()


def _read_xls(path: Path, result: SpreadsheetExtraction) -> None:
    import xlrd

    book = xlrd.open_workbook(str(path), formatting_info=True, on_demand=True)
    try:
        for index, name in enumerate(book.sheet_names()):
            try:
                source = book.sheet_by_index(index)
                sheet = SheetGrid(name, [])
                for row in range(source.nrows):
                    values: list[object] = []
                    for col in range(source.ncols):
                        cell = source.cell(row, col)
                        value: object = cell.value
                        if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                            value = None
                        elif cell.ctype == xlrd.XL_CELL_DATE:
                            value = xlrd.xldate_as_datetime(float(cell.value), book.datemode)
                        elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                            value = bool(value)
                        elif cell.ctype == xlrd.XL_CELL_ERROR:
                            result.warn(f"{name}!R{row + 1}C{col + 1}: ошибка Excel {value}")
                            value = None
                        values.append(value)
                    sheet.values.append(values)
                sheet.merged_ranges = [(r1 + 1, c1 + 1, r2, c2)
                                       for r1, r2, c1, c2 in source.merged_cells]
                _restore_merges(sheet)
                result.sheets.append(sheet)
            except Exception as exc:
                result.warn(f"Лист {name}: {exc}")
            finally:
                book.unload_sheet(index)
    finally:
        book.release_resources()


def _read_ods(path: Path, result: SpreadsheetExtraction) -> None:
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    ns = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
          "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
          "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
    def attr(node, prefix, name, default=None):
        return node.get("{" + ns[prefix] + "}" + name, default)
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    for source in root.findall(".//table:table", ns):
        try:
            sheet = SheetGrid(attr(source, "table", "name", "Sheet"), [])
            for row in source.findall(".//table:table-row", ns):
                for _ in range(int(attr(row, "table", "number-rows-repeated", "1"))):
                    values = []
                    for cell in row:
                        if cell.tag not in {"{" + ns["table"] + "}table-cell", "{" + ns["table"] + "}covered-table-cell"}:
                            continue
                        kind = attr(cell, "office", "value-type")
                        value = None
                        if kind in {"float", "currency", "percentage"}:
                            value = float(attr(cell, "office", "value"))
                        elif kind in {"date", "time"}:
                            value = attr(cell, "office", kind + "-value")
                        elif kind == "boolean":
                            value = attr(cell, "office", "boolean-value") == "true"
                        else:
                            value = attr(cell, "office", "string-value") or "\n".join(
                                "".join(p.itertext()) for p in cell.findall("text:p", ns)) or None
                        for _ in range(int(attr(cell, "table", "number-columns-repeated", "1"))):
                            r, c = len(sheet.values) + 1, len(values) + 1
                            formula = attr(cell, "table", "formula")
                            if formula:
                                sheet.formulas[r, c] = formula
                                if value is None:
                                    result.warn(f"{sheet.name}!R{r}C{c}: нет кэша формулы")
                            rs = int(attr(cell, "table", "number-rows-spanned", "1"))
                            cs = int(attr(cell, "table", "number-columns-spanned", "1"))
                            if rs > 1 or cs > 1:
                                sheet.merged_ranges.append((r, c, r + rs - 1, c + cs - 1))
                            values.append(value)
                    sheet.values.append(values)
            _restore_merges(sheet)
            result.sheets.append(sheet)
        except Exception as exc:
            result.warn(f"Лист {attr(source, 'table', 'name')}: {exc}")
