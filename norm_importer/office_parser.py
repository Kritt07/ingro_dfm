from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, Tuple, Union

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from norm_importer.grid_mapper import map_raw_grid_to_table_grid
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

logger = logging.getLogger("ingro_dfm.norm_importer.office_parser")

OFFICE_EXTENSIONS = {".docx", ".doc", ".rtf", ".txt", ".odt"}

DocBlock = Tuple[str, Union[str, List[List[str]]]]  # ("paragraph", text) | ("table", matrix)


def _read_text_with_fallback(file_path: Path) -> str:
    """Чтение текстового файла с автоопределением кодировки (UTF-8 или CP1251)."""
    for encoding in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return file_path.read_text(encoding="utf-8", errors="replace")


@contextmanager
def _converted_via_libreoffice(input_path: Path, target_ext: str = "docx") -> Iterator[Optional[Path]]:
    """
    Конвертирует .doc / .rtf / .odt в .docx во временном каталоге
    и гарантированно удаляет временный каталог после завершения работы.
    """
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        yield None
        return

    with tempfile.TemporaryDirectory(prefix="norm_importer_lo_") as tmp_str:
        tmp_dir = Path(tmp_str)
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", target_ext, "--outdir", str(tmp_dir), str(input_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            converted = tmp_dir / f"{input_path.stem}.{target_ext}"
            yield converted if converted.exists() else None
        except Exception as exc:
            logger.warning(f"Сбой конвертации LibreOffice для {input_path.name}: {exc}")
            yield None


def unmerge_docx_table(table: Table) -> List[List[str]]:
    """
    Разворачивает таблицу python-docx с объединёнными ячейками (по горизонтали и вертикали)
    в прямоугольную двумерную матрицу строк.
    """
    matrix: List[List[str]] = []
    for row in table.rows:
        row_cells: List[str] = []
        for cell in row.cells:
            clean_text = " ".join(cell.text.strip().split())
            row_cells.append(clean_text)
        matrix.append(row_cells)
    return matrix


def _iter_docx_blocks(doc: Document) -> List[DocBlock]:
    """Возвращает абзацы и таблицы документа в точном порядке их следования в теле документа."""
    blocks: List[DocBlock] = []
    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, doc)
            text = para.text.strip()
            if text:
                blocks.append(("paragraph", text))
        elif isinstance(child, CT_Tbl):
            tbl = Table(child, doc)
            blocks.append(("table", unmerge_docx_table(tbl)))
    return blocks


def _iter_txt_blocks(text: str) -> List[DocBlock]:
    """Извлекает абзацы и таблицы из .txt в порядке следования в документе."""
    blocks: List[DocBlock] = []
    current_table: List[List[str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if len(current_table) >= 2:
                blocks.append(("table", current_table))
            current_table = []
            continue

        if re.fullmatch(r"[\-\+\=\|\s]+", stripped):
            continue

        if "|" in stripped:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            current_table.append(cells)
        elif "\t" in line:
            cells = [c.strip() for c in line.split("\t")]
            current_table.append(cells)
        else:
            if len(current_table) >= 2:
                blocks.append(("table", current_table))
                current_table = []
            blocks.append(("paragraph", stripped))

    if len(current_table) >= 2:
        blocks.append(("table", current_table))

    return blocks


def _group_blocks_into_card_sections(
    blocks: List[DocBlock],
) -> List[Tuple[List[str], List[List[str]], List[str]]]:
    """
    Группирует последовательность (абзацы, таблицы) в локальные секции карт:
    (header_paragraphs, table_grid, note_paragraphs).
    """
    sections: List[Tuple[List[str], List[List[str]], List[str]]] = []
    pending_headers: List[str] = []
    current_header: Optional[List[str]] = None
    current_table: Optional[List[List[str]]] = None
    current_notes: List[str] = []

    for kind, payload in blocks:
        if kind == "paragraph":
            text = str(payload)
            is_new_card = bool(re.match(r"^Карта\s*(?:№\s*)?\d+", text, flags=re.IGNORECASE))
            if current_table is not None:
                if is_new_card:
                    sections.append((current_header or [], current_table, current_notes))
                    current_header = None
                    current_table = None
                    current_notes = []
                    pending_headers = [text]
                else:
                    current_notes.append(text)
            else:
                if is_new_card and pending_headers:
                    # Если за предыдущим заголовком не было таблицы, начинаем новую секцию
                    pending_headers = [text]
                else:
                    pending_headers.append(text)
        elif kind == "table":
            if current_table is not None:
                sections.append((current_header or [], current_table, current_notes))
                current_notes = []
            current_header = list(pending_headers)
            pending_headers = []
            current_table = payload  # type: ignore[assignment]

    if current_table is not None:
        sections.append((current_header or [], current_table, current_notes))

    return sections


def _parse_blocks_to_document(
    blocks: List[DocBlock],
    file_path: Path,
    source_format: SourceFormat,
    extraction_method: str,
    initial_warnings: List[str],
    initial_manual_review: bool,
) -> NormDocDocument:
    warnings = list(initial_warnings)
    requires_manual_review = initial_manual_review
    sections = _group_blocks_into_card_sections(blocks)

    doc_title_prefix: List[str] = []
    for kind, payload in blocks:
        if kind == "table":
            break
        text = str(payload)
        if re.match(r"^Карта\s*(?:№\s*)?\d+", text, flags=re.IGNORECASE):
            break
        doc_title_prefix.append(text)

    cards: List[NormCard] = []
    for idx, (local_headers, grid, local_notes) in enumerate(sections, start=1):
        try:
            header_context = [*doc_title_prefix, *local_headers]
            header_lines = [
                p for p in header_context
                if not re.match(r"^(?:Примечани[ея]|\d+[\.\)]\s+)", p.strip(), flags=re.IGNORECASE)
            ]
            pre_notes = [
                p for p in header_context
                if re.match(r"^(?:Примечани[ея]|\d+[\.\)]\s+)", p.strip(), flags=re.IGNORECASE)
            ]
            parsed_header = parse_card_header(header_lines, fallback_stem=file_path.stem, card_index=idx)
            warnings.extend(parsed_header.warnings)
            if parsed_header.warnings:
                requires_manual_review = True

            rules, note_warnings = parse_notes_with_diagnostics(
                [*pre_notes, *local_notes],
                result_unit=parsed_header.result_unit,
            )
            warnings.extend(note_warnings)
            if note_warnings:
                requires_manual_review = True

            table_grid, grid_warnings = map_raw_grid_to_table_grid(grid)
            warnings.extend(grid_warnings)

            card_id = parsed_header.card_id
            if any(c.card_id == card_id for c in cards):
                card_id = f"{card_id}_{idx:02d}"

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
            warnings.append(f"Таблица {idx} пропущена из-за ошибки структуры: {exc}")

    if not cards:
        all_paragraphs = [str(payload) for kind, payload in blocks if kind == "paragraph"]
        parsed_header = parse_card_header(all_paragraphs, fallback_stem=file_path.stem, card_index=1)
        rules, note_warnings = parse_notes_with_diagnostics(all_paragraphs, result_unit=parsed_header.result_unit)
        warnings.extend(note_warnings)
        requires_manual_review = True
        warnings.append("В документе не обнаружены валидные нормативные таблицы; создана пустая карточка-заглушка.")
        cards.append(
            NormCard(
                card_id=f"{file_path.stem.upper()}_EMPTY_01",
                card_title=parsed_header.card_title,
                applicability_conditions=parsed_header.applicability,
                calculation_formula=parsed_header.calculation_formula,
                result_unit=parsed_header.result_unit,
                table_grid=TableGrid(
                    row_param_name="unknown",
                    rows_range=["stub"],
                    cols_range=["stub"],
                    values_matrix=[[None]],
                ),
                notes_and_coefficients=rules,
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


def parse_office_file(file_path: Path) -> NormDocDocument:
    """Главная точка входа парсера для .docx, .doc, .rtf, .odt, .txt."""
    ext = file_path.suffix.lower()
    warnings: List[str] = []
    requires_manual_review = False

    format_map = {
        ".docx": SourceFormat.DOCX,
        ".doc": SourceFormat.DOC,
        ".rtf": SourceFormat.RTF,
        ".odt": SourceFormat.ODT,
        ".txt": SourceFormat.TXT,
    }
    source_format = format_map.get(ext, SourceFormat.TXT)

    if ext in {".doc", ".rtf", ".odt"}:
        with _converted_via_libreoffice(file_path, "docx") as converted:
            if converted is not None:
                doc = Document(str(converted))
                blocks = _iter_docx_blocks(doc)
                return _parse_blocks_to_document(
                    blocks=blocks,
                    file_path=file_path,
                    source_format=source_format,
                    extraction_method="python-docx",
                    initial_warnings=warnings,
                    initial_manual_review=requires_manual_review,
                )

        warnings.append(f"LibreOffice не найден или сбой конвертации: выполнен текстовый fallback-разбор для {ext}.")
        requires_manual_review = True
        raw_text = _read_text_with_fallback(file_path)
        blocks = _iter_txt_blocks(raw_text)
        return _parse_blocks_to_document(
            blocks=blocks,
            file_path=file_path,
            source_format=source_format,
            extraction_method="txt_table_parser",
            initial_warnings=warnings,
            initial_manual_review=requires_manual_review,
        )

    if ext == ".docx":
        doc = Document(str(file_path))
        blocks = _iter_docx_blocks(doc)
        return _parse_blocks_to_document(
            blocks=blocks,
            file_path=file_path,
            source_format=source_format,
            extraction_method="python-docx",
            initial_warnings=warnings,
            initial_manual_review=requires_manual_review,
        )

    raw_text = _read_text_with_fallback(file_path)
    blocks = _iter_txt_blocks(raw_text)
    return _parse_blocks_to_document(
        blocks=blocks,
        file_path=file_path,
        source_format=source_format,
        extraction_method="txt_table_parser",
        initial_warnings=warnings,
        initial_manual_review=requires_manual_review,
    )