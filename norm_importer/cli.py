from pathlib import Path
from typing import List, Optional
import typer

from norm_importer.logger import setup_logger
from norm_importer.office_parser import OFFICE_EXTENSIONS, parse_office_file
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
