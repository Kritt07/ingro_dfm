from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from docx import Document
from docx.table import Table
from norm_importer.grid_mapper import map_raw_grid_to_table_grid
from norm_importer.header_parser import parse_card_header
from norm_importer.notes_parser import parse_notes_to_rules

from norm_importer.schema import (
    ApplicabilityConditions,
    ModifierOperation,
    NormCard,
    NormDocDocument,
    NoteCoefficientRule,
    SourceFormat,
    SourceMetadata,
    TableGrid,
)

logger = logging.getLogger("ingro_dfm.norm_importer.office_parser")

OFFICE_EXTENSIONS = {".docx", ".doc", ".rtf", ".txt", ".odt"}


def _read_text_with_fallback(file_path: Path) -> str:
    """Чтение текстового файла с автоопределением кодировки (UTF-8 или CP1251)."""
    for encoding in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return file_path.read_text(encoding="utf-8", errors="replace")


def _convert_via_libreoffice(input_path: Path, target_ext: str = "docx") -> Optional[Path]:
    """Конвертация .doc / .rtf / .odt в .docx через LibreOffice headless (если установлен)."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None

    tmp_dir = Path(tempfile.mkdtemp(prefix="norm_importer_lo_"))
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", target_ext, "--outdir", str(tmp_dir), str(input_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        converted = tmp_dir / f"{input_path.stem}.{target_ext}"
        return converted if converted.exists() else None
    except Exception as exc:
        logger.warning(f"Сбой конвертации LibreOffice для {input_path.name}: {exc}")
        return None


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


def _extract_numeric_headers(header_row: List[str]) -> List[float]:
    """Извлекает числовые границы диапазонов из заголовка столбцов или строк."""
    values: List[float] = []
    for item in header_row:
        match = re.search(r"(\d+(?:[.,]\d+)?)", item)
        if match:
            values.append(float(match.group(1).replace(",", ".")))
    return values


def _parse_notes_to_rules(notes_lines: List[str]) -> List[NoteCoefficientRule]:
    """Преобразует текстовые примечания в структурированные правила поправочных коэффициентов."""
    rules: List[NoteCoefficientRule] = []
    for idx, line in enumerate(notes_lines, start=1):
        factor_match = re.search(
            r"(?:коэффициент\w*|умножать\s+на|применять\s+с\s+К\s*=)\s*(\d+(?:[.,]\d+)?)",
            line,
            flags=re.IGNORECASE,
        )
        if not factor_match:
            continue

        factor = float(factor_match.group(1).replace(",", "."))
        lower = line.lower()

        if "глух" in lower:
            cond_key, cond_val = "is_blind_hole", True
        elif "глубок" in lower or "l >" in lower or "l/d" in lower:
            cond_key, cond_val = "l_to_d_ratio_gt_3", True
        elif "чугун" in lower:
            cond_key, cond_val = "material_group", "cast_iron"
        else:
            cond_key, cond_val = f"custom_condition_{idx}", True

        rules.append(
            NoteCoefficientRule(
                note_id=f"NOTE_{idx:02d}",
                raw_text=line.strip(),
                condition_key=cond_key,
                condition_value=cond_val,
                modifier_operation=ModifierOperation.MULTIPLY,
                target_variable="Ttbl",
                factor=factor,
            )
        )
    return rules


def _extract_metadata_from_paragraphs(paragraphs: List[str], fallback_name: str) -> Tuple[str, str, str, List[str]]:
    """Выделяет заголовок карты, тип операции, формулу и блок примечаний из абзацев документа."""
    card_title = f"Карта из {fallback_name}"
    operation_type = "Механическая обработка"
    formula = "Ttbl"
    notes: List[str] = []
    in_notes_block = False

    for text in paragraphs:
        clean = " ".join(text.strip().split())
        if not clean:
            continue

        if re.match(r"^Карта\s+\d+", clean, flags=re.IGNORECASE):
            card_title = clean
            for op in ("Сверление", "Точение", "Фрезерование", "Шлифование", "Развертывание", "Зенкерование"):
                if op.lower() in clean.lower():
                    operation_type = op
                    break
            continue

        if "формула" in clean.lower() or re.search(r"\bT\w*\s*=", clean):
            formula_match = re.search(r"=\s*(.+)$", clean)
            if formula_match:
                formula = formula_match.group(1).strip()
            continue

        if re.match(r"^Примечани[ея]", clean, flags=re.IGNORECASE):
            in_notes_block = True
            after_colon = clean.split(":", 1)[-1].strip()
            if after_colon:
                notes.append(after_colon)
            continue

        if in_notes_block or re.match(r"^\d+[\.\)]\s+", clean):
            notes.append(clean)

    return card_title, operation_type, formula, notes

def _parse_txt_tables(text: str) -> Tuple[List[str], List[List[List[str]]]]:
    """Извлекает абзацы и псевдографические/разделённые табуляцией или '|' таблицы из .txt."""
    paragraphs: List[str] = []
    tables: List[List[List[str]]] = []
    current_table: List[List[str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if len(current_table) >= 2:
                tables.append(current_table)
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
                tables.append(current_table)
                current_table = []
            paragraphs.append(stripped)

    if len(current_table) >= 2:
        tables.append(current_table)

    return paragraphs, tables


def parse_office_file(file_path: Path) -> NormDocDocument:
    """Главная точка входа парсера для .docx, .doc, .rtf, .odt, .txt."""
    ext = file_path.suffix.lower()
    warnings: List[str] = []
    requires_manual_review = False
    working_path = file_path

    format_map = {
        ".docx": SourceFormat.DOCX,
        ".doc": SourceFormat.DOC,
        ".rtf": SourceFormat.RTF,
        ".odt": SourceFormat.ODT,
        ".txt": SourceFormat.TXT,
    }
    source_format = format_map.get(ext, SourceFormat.TXT)

    if ext in {".doc", ".rtf", ".odt"}:
        converted = _convert_via_libreoffice(file_path, "docx")
        if converted is not None:
            working_path = converted
        else:
            warnings.append(f"LibreOffice не найден: выполнен текстовый fallback-разбор для {ext}.")
            requires_manual_review = True

    paragraphs: List[str] = []
    raw_tables: List[List[List[str]]] = []
    extraction_method = "python-docx"

    if working_path.suffix.lower() == ".docx":
        doc = Document(str(working_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        raw_tables = [unmerge_docx_table(t) for t in doc.tables]
    else:
        extraction_method = "txt_table_parser"
        raw_text = _read_text_with_fallback(working_path)
        paragraphs, raw_tables = _parse_txt_tables(raw_text)

    header_lines = [
        p for p in paragraphs
        if not re.match(r"^(?:Примечани[ея]|\d+[\.\)]\s+)", p.strip(), flags=re.IGNORECASE)
    ]
    parsed_header = parse_card_header(header_lines, fallback_stem=file_path.stem)
    _, _, _, notes = _extract_metadata_from_paragraphs(paragraphs, file_path.name)
    rules = parse_notes_to_rules(notes)

    cards: List[NormCard] = []
    for idx, grid in enumerate(raw_tables, start=1):
        try:
            table_grid, grid_warnings = map_raw_grid_to_table_grid(grid)
            warnings.extend(grid_warnings)
            cards.append(
                NormCard(
                    card_id=parsed_header.card_id if len(raw_tables) == 1 else f"{parsed_header.card_id}_{idx:02d}",
                    card_title=parsed_header.card_title if len(raw_tables) == 1 else f"{parsed_header.card_title} (Таблица {idx})",
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
