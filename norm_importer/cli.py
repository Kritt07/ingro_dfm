from pathlib import Path
from typing import Any, List, Optional, Tuple
import csv
import re
import tempfile
import typer

from norm_importer.logger import setup_logger
from norm_importer.grid_mapper import map_raw_grid_to_table_grid
from norm_importer.office_parser import OFFICE_EXTENSIONS, parse_office_file
from norm_importer.header_parser import parse_card_header
from norm_importer.notes_parser import parse_notes_with_diagnostics
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


def _split_sheet_preamble_and_table(rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """
    Отделяет верхние строки метаданных листа Excel (заголовок карты, формула, материал)
    от собственно таблицы нормативов (начиная со строки, где >= 2 непустых ячеек).
    """
    preamble: List[str] = []
    table_start = 0

    for idx, row in enumerate(rows):
        non_empty = [c.strip() for c in row if c and c.strip()]
        if not non_empty:
            continue
        if len(non_empty) == 1:
            preamble.append(non_empty[0])
            table_start = idx + 1
        else:
            table_start = idx
            break

    return preamble, rows[table_start:]


def _parse_spreadsheet_file(file_path: Path) -> NormDocDocument:
    """Извлекает таблицы из .xlsx / .xls / .csv / .ods через normdoc2json.spreadsheets или fallback."""
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
        from normdoc2json.spreadsheets import extract_spreadsheet
        extracted = extract_spreadsheet(file_path)
        extraction_method = "normdoc2json.spreadsheets"
        warnings.extend(getattr(extracted, "warnings", []))
        for idx, sheet in enumerate(getattr(extracted, "sheets", []), start=1):
            title = getattr(sheet, "name", f"Лист {idx}")
            values = getattr(sheet, "values", [])
            if isinstance(values, list) and values:
                str_values = [["" if cell is None else str(cell) for cell in row] for row in values]
                raw_grids.append((str(title), str_values))
    except Exception:
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
            preamble_lines, table_rows, footer_notes = _split_sheet_sections(grid)
            header_context = [sheet_title, *preamble_lines, file_path.stem]
            parsed_header = parse_card_header(header_context, fallback_stem=file_path.stem, card_index=idx)
            warnings.extend(parsed_header.warnings)
            if parsed_header.warnings:
                requires_manual_review = True

            rules, note_warnings = parse_notes_with_diagnostics(
                [*preamble_lines, *footer_notes],
                result_unit=parsed_header.result_unit,
            )
            warnings.extend(note_warnings)
            if note_warnings:
                requires_manual_review = True

            table_grid, grid_warnings = map_raw_grid_to_table_grid(table_rows)
            warnings.extend(grid_warnings)
            cards.append(
                NormCard(
                    card_id=parsed_header.card_id,
                    card_title=parsed_header.card_title if sheet_title else f"Карта {idx:02d}",
                    applicability_conditions=parsed_header.applicability,
                    calculation_formula=parsed_header.calculation_formula,
                    result_unit=parsed_header.result_unit,
                    table_grid=table_grid,
                    notes_and_coefficients=rules,
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


def _is_numeric_axis_cell(text: str) -> bool:
    """Проверяет, является ли ячейка значением числовой оси (число, интервал или 'св. 2500')."""
    return bool(re.match(r"^(?:св\.?\s*|до\s*)?[+-]?\d+(?:[.,]\d+)?", text.strip(), flags=re.IGNORECASE))


def _split_sheet_sections(rows: List[List[str]]) -> Tuple[List[str], List[List[str]], List[str]]:
    """
    Разделяет лист Excel на три секции:
    1) верхнюю преамбулу (заголовок карты, формула, материал);
    2) собственно нормативную таблицу (включая строки с заполненной осью и пустыми нормативами);
    3) нижний блок примечаний под таблицей.
    """
    preamble: List[str] = []
    table_rows: List[List[str]] = []
    footer_notes: List[str] = []

    in_table = False
    in_footer = False

    for row in rows:
        non_empty = [str(c).strip() for c in row if c is not None and str(c).strip()]
        if not non_empty:
            continue
        first_cell = non_empty[0]
        is_note_marker = bool(re.match(r"^(?:Примечани[ея]|\d+[\.\)]\s+)", first_cell, flags=re.IGNORECASE))

        if not in_table and not in_footer:
            if len(non_empty) == 1 and not is_note_marker:
                preamble.append(first_cell)
            elif len(non_empty) >= 2 and not is_note_marker:
                in_table = True
                table_rows.append(row)
            else:
                in_footer = True
                footer_notes.append(" ".join(non_empty))
        elif in_table and not in_footer:
            if is_note_marker or (len(non_empty) == 1 and not _is_numeric_axis_cell(first_cell)):
                in_table = False
                in_footer = True
                footer_notes.append(" ".join(non_empty))
            else:
                table_rows.append(row)
        else:
            footer_notes.append(" ".join(non_empty))

    return preamble, table_rows, footer_notes


def _is_ignored_debug_path(path: Path, root: Path) -> bool:
    """Проверяет, находится ли файл внутри служебного каталога *.debug или скрытой директории (B17)."""
    try:
        rel_parts = path.relative_to(root).parts[:-1]
    except ValueError:
        rel_parts = path.parts[:-1]
    return any(part.endswith(".debug") or part.startswith(".") for part in rel_parts)


def collect_input_files(input_path: Path) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(
            p for p in input_path.rglob("*")
            if p.is_file()
            and p.suffix.lower() in SUPPORTED_EXTENSIONS
                        and not _is_ignored_debug_path(p, input_path)
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


def _extract_grid_from_pdf_table(table_obj: Any) -> List[List[str]]:
    """Извлекает двумерную матрицу строк из объекта таблицы extract_pdf."""
    if isinstance(table_obj, list):
        return [["" if c is None else str(c) for c in row] for row in table_obj]
    for attr in ("rows", "values", "cells", "data", "grid"):
        raw = getattr(table_obj, attr, None)
        if isinstance(raw, list) and raw:
            return [["" if c is None else str(c) for c in row] for row in raw]
    return []

def _parse_vector_pdf_file(file_path: Path, detected_format: SourceFormat) -> NormDocDocument:
    """Подключение экстрактора векторных PDF (normdoc2json.pdf.extract_pdf) к разбору карт (B10)."""
    warnings: List[str] = []
    requires_manual_review = False
    cards: List[NormCard] = []

    try:
        from normdoc2json.pdf import extract_pdf
        pdf_res = extract_pdf(file_path)
        warnings.extend(getattr(pdf_res, "warnings", []))

        pages = getattr(pdf_res, "pages", []) or []
        card_counter = 0

        for p_idx, page in enumerate(pages, start=1):
            page_num = getattr(page, "page_number", p_idx)
            blocks = sorted(
                getattr(page, "blocks", []) or [],
                key=lambda b: (getattr(b, "bbox", (0, 0, 0, 0))[1], getattr(b, "bbox", (0, 0, 0, 0))[0]),
            )
            tables = sorted(
                getattr(page, "tables", []) or [],
                key=lambda t: getattr(t, "bbox", (0, 0, 0, 0))[1],
            )

            for t_idx, tbl in enumerate(tables):
                card_counter += 1
                grid = _extract_grid_from_pdf_table(tbl)
                if not grid:
                    continue

                t_bbox = getattr(tbl, "bbox", None)
                prev_bottom = getattr(tables[t_idx - 1], "bbox", (0, 0, 0, 0))[3] if t_idx > 0 else 0.0
                next_top = getattr(tables[t_idx + 1], "bbox", (0, float("inf"), 0, 0))[1] if t_idx + 1 < len(tables) else float("inf")

                header_lines: List[str] = []
                note_lines: List[str] = []
                if t_bbox is not None:
                    t_top, t_bottom = t_bbox[1], t_bbox[3]
                    for blk in blocks:
                        b_bbox = getattr(blk, "bbox", None)
                        b_text = (getattr(blk, "text", "") or "").strip()
                        if not b_text or b_bbox is None:
                            continue
                        if prev_bottom <= b_bbox[1] and b_bbox[3] <= t_top:
                            header_lines.append(b_text)
                        elif t_bottom <= b_bbox[1] and b_bbox[3] <= next_top:
                            note_lines.append(b_text)
                else:
                    header_lines = [(getattr(b, "text", "") or "").strip() for b in blocks if (getattr(b, "text", "") or "").strip()]
                    note_lines = list(header_lines)

                try:
                    parsed_header = parse_card_header(
                        [*header_lines, file_path.stem],
                        fallback_stem=file_path.stem,
                        card_index=card_counter,
                    )
                    warnings.extend(parsed_header.warnings)
                    if parsed_header.warnings:
                        requires_manual_review = True

                    rules, note_warnings = parse_notes_with_diagnostics(
                        [*header_lines, *note_lines],
                        result_unit=parsed_header.result_unit,
                    )
                    warnings.extend(note_warnings)
                    if note_warnings:
                        requires_manual_review = True

                    table_grid, grid_warnings = map_raw_grid_to_table_grid(grid)
                    warnings.extend(grid_warnings)
                    if grid_warnings:
                        requires_manual_review = True

                    card_id = parsed_header.card_id
                    if any(c.card_id == card_id for c in cards):
                        card_id = f"{card_id}_{card_counter:02d}"

                    cards.append(
                        NormCard(
                            card_id=card_id,
                            card_title=parsed_header.card_title,
                            applicability_conditions=parsed_header.applicability,
                            calculation_formula=parsed_header.calculation_formula,
                            result_unit=parsed_header.result_unit,
                            table_grid=table_grid,
                            notes_and_coefficients=rules,
                        )
                    )
                except Exception as exc:
                    requires_manual_review = True
                    warnings.append(f"Таблица {card_counter} (стр. {page_num}) в PDF пропущена: {exc}")
    except Exception as exc:
        requires_manual_review = True
        warnings.append(f"Ошибка извлечения PDF {file_path.name}: {exc}")

    if not cards:
        requires_manual_review = True
        warnings.append(f"В PDF {file_path.name} не удалось извлечь таблицы; создана карточка-заглушка.")
        cards.append(
            NormCard(
                card_id=f"{file_path.stem.upper()}_EMPTY_01",
                card_title=f"Заготовка карты из {file_path.name}",
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
            source_format=detected_format,
            page_number=1,
            extraction_method="normdoc2json.pdf",
            requires_manual_review=requires_manual_review,
            warnings=warnings,
        ),
        cards=cards,
    )


def _enrich_ocr_document_notes(doc: NormDocDocument) -> NormDocDocument:
    """Подключает парсер коэффициентов и примечаний к окружающему тексту OCR (I01)."""
    handoff_re = re.compile(
        r"^Page\s+(\d+)\s+table\s+(\d+):\s+surrounding text requires semantic review \(notes parser handoff\):\s*(.+)$",
        flags=re.IGNORECASE,
    )
    per_table_lines: dict[str, List[str]] = {}
    fallback_lines: List[str] = []

    for w in doc.source_metadata.warnings:
        match = handoff_re.match(w.strip())
        if match:
            page_num, tbl_idx, raw_blob = match.groups()
            key = f"_P{page_num}_T{tbl_idx}"
            segments = [seg.strip() for seg in raw_blob.split(" | ") if seg.strip()]
            per_table_lines.setdefault(key, []).extend(segments)
            fallback_lines.extend(segments)

    if not fallback_lines:
        return doc

    for card in doc.cards:
        if card.notes_and_coefficients:
            continue
        matched_lines = next(
            (lines for suffix, lines in per_table_lines.items() if card.card_id.endswith(suffix)),
            fallback_lines,
        )
        rules, note_warnings = parse_notes_with_diagnostics(
            matched_lines,
            result_unit=card.result_unit,
        )
        if rules:
            card.notes_and_coefficients.extend(rules)
        if note_warnings:
            doc.source_metadata.warnings.extend(note_warnings)
            doc.source_metadata.requires_manual_review = True

    return doc


def process_single_file(
    file_path: Path,
    ocr_lang: str,
    debug_images: bool,
    logger,
) -> NormDocDocument:
    """Маршрутизация файла по экстракторам Дней 2–6."""
    logger.info(f"Начало обработки файла: {file_path.name} (ocr_lang={ocr_lang}, debug={debug_images})")
    ext = file_path.suffix.lower()

    if ext in OFFICE_EXTENSIONS:
        return parse_office_file(file_path)
    if ext in SPREADSHEET_EXTENSIONS:
        return _parse_spreadsheet_file(file_path)

    detected_format = _detect_format_via_router(file_path)

    if detected_format in {
        SourceFormat.PDF_SCANNED,
        SourceFormat.PDF_HYBRID,
        SourceFormat.IMAGE,
        SourceFormat.TIFF,
    }:
        from normdoc2json import ocr_document
        debug_dir = (
            Path(tempfile.gettempdir()) / "norm_importer_debug" / f"{file_path.name}.debug"
            if debug_images
            else None
        )
        doc = ocr_document(file_path, lang=ocr_lang, debug_dir=debug_dir)
        return _enrich_ocr_document_notes(doc)

    if detected_format == SourceFormat.PDF_VECTOR or ext == ".pdf":
        return _parse_vector_pdf_file(file_path, detected_format)

    return NormDocDocument(
        source_metadata=SourceMetadata(
            source_file=file_path.name,
            source_format=detected_format,
            page_number=1,
            extraction_method="router_integrated_stub",
            requires_manual_review=True,
            warnings=[f"Экстрактор для формата {detected_format.value} не подключён"],
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