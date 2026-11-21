from pathlib import Path
from typing import List, Optional, Tuple
import typer
import csv

from norm_importer.logger import setup_logger
from norm_importer.grid_mapper import map_raw_grid_to_table_grid
from norm_importer.office_parser import OFFICE_EXTENSIONS, parse_office_file
from norm_importer.header_parser import parse_card_header
from norm_importer.schema import (
    ApplicabilityConditions,
    NormCard,
    NormDocDocument,
    SourceFormat,
    SourceMetadata,
    TableGrid,
)

app = typer.Typer(
    name="norm_importer",
    help="Утилита импорта, OCR и конвертации нормативно-справочных документов ЦБНТ/ОУНВ в JSON.",
    add_completion=False,
)

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".rtf", ".odt", ".txt",
    ".xlsx", ".xls", ".csv", ".ods",
    ".jpeg", ".jpg", ".png", ".bmp", ".webp", ".tiff", ".tif",
}

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".csv", ".ods"}

def _parse_spreadsheet_file(file_path: Path) -> NormDocDocument:
    """Извлекает таблицы из .xlsx / .csv (через spreadsheets.py Разработчика 1 или openpyxl/csv)."""
    ext = file_path.suffix.lower()
    format_map = {
        ".xlsx": SourceFormat.XLSX,
        ".xls": SourceFormat.XLS,
        ".csv": SourceFormat.CSV,
        ".ods": SourceFormat.ODS,
    }
    source_format = format_map.get(ext, SourceFormat.XLSX)
    warnings: List[str] = []
    requires_manual_review = False
    raw_grids: List[Tuple[str, List[List[str]]]] = []
    extraction_method = "openpyxl_grid_mapper"

    try:
        from normdoc2json.spreadsheets import extract_spreadsheet_tables
        extracted = extract_spreadsheet_tables(file_path)
        extraction_method = "normdoc2json.spreadsheets"
        for idx, tbl in enumerate(extracted, start=1):
            grid = getattr(tbl, "grid", None) or getattr(tbl, "rows", None) or tbl
            title = getattr(tbl, "title", f"Лист {idx}")
            if isinstance(grid, list):
                raw_grids.append((str(title), grid))
    except Exception:
        # Надёжный встроенный fallback для .csv и .xlsx
        try:
           if ext == ".csv":
               extraction_method = "csv_grid_mapper"
               text = file_path.read_text(encoding="utf-8-sig")
               dialect = csv.Sniffer().sniff(text[:1024], delimiters=";,|\t")
               rows = list(csv.reader(text.splitlines(), dialect))
               raw_grids.append((file_path.stem, rows))
           elif ext == ".xlsx":
               import openpyxl
               wb = openpyxl.load_workbook(str(file_path), data_only=True)
               for sheet_name in wb.sheetnames:
                   ws = wb[sheet_name]
                   rows = [
                       ["" if cell is None else str(cell) for cell in row]
                       for row in ws.iter_rows(values_only=True)
                   ]
                   raw_grids.append((sheet_name, rows))
        except Exception as exc:
                requires_manual_review = True
                warnings.append(f"Ошибка чтения табличного файла {file_path.name}: {exc}")

    cards: List[NormCard] = []
    for idx, (sheet_title, grid) in enumerate(raw_grids, start=1):
        try:
            table_grid, grid_warnings = map_raw_grid_to_table_grid(grid)
            warnings.extend(grid_warnings)
            cards.append(
                NormCard(
                    card_id=f"{file_path.stem.upper()}_SHEET_{idx:02d}",
                    card_title=f"Карта ({sheet_title})",
                    applicability_conditions=ApplicabilityConditions(operation_type="Механическая обработка"),
                    calculation_formula="Ttbl",
                    table_grid=table_grid,
                )
            )
        except Exception as exc:
            requires_manual_review = True
            warnings.append(f"Лист '{sheet_title}' пропущен: {exc}")

    if not cards:
        requires_manual_review = True
        warnings.append("Не удалось извлечь валидные таблицы из файла; создана карточка-заглушка.")
        cards.append(
            NormCard(
                card_id=f"{file_path.stem.upper()}_EMPTY_01",
                card_title=f"Заготовка из {file_path.name}",
                applicability_conditions=ApplicabilityConditions(operation_type="Не определено"),
                calculation_formula="Ttbl",
                table_grid=TableGrid(
                    row_param_name="unknown",
                    rows_range=["stub"],
                    cols_range=["stub"],
                    values_matrix=[[None]],
                ),
            )
        )

    return NormDocDocument(
        source_metadata=SourceMetadata(
            source_file=file_path.name,
            source_format=source_format,
            page_number=1,
            extraction_method=extraction_method,
            requires_manual_review=requires_manual_review,
            warnings=warnings,
        ),
        cards=cards,
    )

def collect_input_files(input_path: Path) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(
            p for p in input_path.rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    return []


def build_batch_output_path(file_path: Path, input_root: Path, output_dir: Path) -> Path:
    """Формирует уникальный путь выходного JSON с учётом подпапок и исходного расширения."""
    ext_tag = file_path.suffix.lstrip(".").lower() or "file"
    if input_root.is_dir():
        rel_parent = file_path.relative_to(input_root).parent
        target_subdir = output_dir / rel_parent
    else:
        target_subdir = output_dir
    target_subdir.mkdir(parents=True, exist_ok=True)
    return target_subdir / f"{file_path.stem}_{ext_tag}.json"


def _detect_format_via_router(file_path: Path) -> SourceFormat:
    """Определяет SourceFormat через FormatRouter Разработчика 1 (с fallback по расширению)."""
    try:
        from normdoc2json.format_router import inspect_file
        info = inspect_file(file_path)
        detected = getattr(info, "source_format", None) or getattr(info, "format", None)
        if detected:
            val = detected.value if hasattr(detected, "value") else str(detected)
            return SourceFormat(val)
    except Exception:
        pass

    ext = file_path.suffix.lower()
    mapping = {
        ".pdf": SourceFormat.PDF_VECTOR,
        ".docx": SourceFormat.DOCX,
        ".doc": SourceFormat.DOC,
        ".rtf": SourceFormat.RTF,
        ".odt": SourceFormat.ODT,
        ".txt": SourceFormat.TXT,
        ".xlsx": SourceFormat.XLSX,
        ".xls": SourceFormat.XLS,
        ".csv": SourceFormat.CSV,
        ".ods": SourceFormat.ODS,
        ".tiff": SourceFormat.TIFF,
        ".tif": SourceFormat.TIFF,
    }
    return mapping.get(ext, SourceFormat.IMAGE)


def process_single_file(
    file_path: Path,
    ocr_lang: str,
    debug_images: bool,
    logger,
) -> NormDocDocument:
    """Маршрутизация файла по экстракторам Дней 2–5."""
    logger.info(f"Начало обработки файла: {file_path.name} (ocr_lang={ocr_lang}, debug={debug_images})")
    ext = file_path.suffix.lower()

    if ext in OFFICE_EXTENSIONS:
        return parse_office_file(file_path)
    if ext in OFFICE_EXTENSIONS:
        return parse_office_file(file_path)
    if ext in SPREADSHEET_EXTENSIONS:
        return _parse_spreadsheet_file(file_path)

    detected_format = _detect_format_via_router(file_path)

    return NormDocDocument(
        source_metadata=SourceMetadata(
            source_file=file_path.name,
            source_format=detected_format,
            page_number=1,
            extraction_method="router_integrated_stub",
            requires_manual_review=True,
            warnings=[f"Экстрактор для формата {detected_format.value} ожидает подключения в следующем этапе"],
        ),
        cards=[
            NormCard(
                card_id=f"{file_path.stem.upper()}_STUB_01",
                card_title=f"Заготовка карты из {file_path.name}",
                applicability_conditions=ApplicabilityConditions(operation_type="Не определено"),
                calculation_formula="Ttbl",
                table_grid=TableGrid(
                    row_param_name="diameter_d_mm",
                    rows_range=[10.0],
                    cols_range=[15.0],
                    values_matrix=[[0.0]],
                ),
            )
        ],
    )


@app.command()
def convert(
    input_path: Path = typer.Option(
        ..., "--input", "-i", exists=True, help="Путь к входному файлу или директории."
    ),
    output_path: Path = typer.Option(
        ..., "--output", "-o", help="Путь к выходному JSON-файлу или директории."
    ),
    ocr_lang: str = typer.Option(
        "rus+eng", "--ocr-lang", help="Языковой профиль OCR (по умолчанию rus+eng)."
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Возвращать код 1 при наличии requires_manual_review или ошибок."
    ),
    debug_images: bool = typer.Option(
        False, "--debug-images", help="Сохранять отладочные изображения с рамками ячеек."
    ),
    log_file: Optional[Path] = typer.Option(
        None, "--log-file", help="Путь к файлу журнала конвертации."
    ),
) -> None:
    logger = setup_logger(log_file=log_file)
    files = collect_input_files(input_path)

    if not files:
        logger.error(f"Не найдены поддерживаемые файлы по пути: {input_path}")
        raise typer.Exit(code=1)

    has_issues = False
    is_single_target_file = input_path.is_file() and output_path.suffix.lower() == ".json"

    for file_path in files:
        try:
            doc = process_single_file(file_path, ocr_lang, debug_images, logger)
            if is_single_target_file:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                out_file = output_path
            else:
                out_file = build_batch_output_path(file_path, input_path, output_path)

            doc.to_json_file(str(out_file))
            logger.info(f"Сохранен результат: {out_file}")

            if doc.source_metadata.requires_manual_review or doc.source_metadata.warnings:
                has_issues = True
        except Exception as exc:
            has_issues = True
            logger.error(f"Ошибка при обработке {file_path}: {exc}", exc_info=True)

    if strict and has_issues:
        logger.warning("Завершение в режиме --strict с кодом 1 из-за предупреждений/ошибок.")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
