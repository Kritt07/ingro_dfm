from pathlib import Path
from typing import List, Optional
import typer

from norm_importer.logger import setup_logger
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


def process_single_file(
    file_path: Path,
    output_dir: Path,
    ocr_lang: str,
    debug_images: bool,
    logger,
) -> NormDocDocument:
    """Точка интеграции конвейера: Format Router -> Extractor/OCR -> Semantic Parser -> Pydantic."""
    logger.info(f"Начало обработки файла: {file_path.name} (ocr_lang={ocr_lang}, debug={debug_images})")

    doc = NormDocDocument(
        source_metadata=SourceMetadata(
            source_file=file_path.name,
            source_format=SourceFormat.TXT,
            page_number=1,
            extraction_method="skeleton_stub_day1",
            requires_manual_review=True,
            warnings=["Каркас Дня 1: парсер формата еще не подключен"],
        ),
        cards=[
            NormCard(
                card_id="STUB_CARD_01",
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

    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{file_path.stem}.json"
    doc.to_json_file(str(out_file))
    logger.info(f"Сохранен результат: {out_file}")
    return doc


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
            target_dir = output_path.parent if is_single_target_file else output_path
            doc = process_single_file(file_path, target_dir, ocr_lang, debug_images, logger)
            if is_single_target_file:
                generated = target_dir / f"{file_path.stem}.json"
                if generated != output_path:
                    generated.replace(output_path)
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
