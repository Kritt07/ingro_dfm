from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from norm_importer.schema import ApplicabilityConditions


@dataclass
class ParsedCardHeader:
    card_id: str
    card_title: str
    calculation_formula: str
    result_unit: str
    applicability: ApplicabilityConditions


OPERATION_PATTERNS = [
    (r"сверлен|зенкерован|развертыван|рассверливан", "Сверление"),
    (r"точен|растачиван|подрезан|отрезк|нарезан\w*\s+резьб", "Точение"),
    (r"фрезерован", "Фрезерование"),
    (r"шлифован", "Шлифование"),
    (r"строган|долблен", "Строгание"),
    (r"протягиван", "Протягивание"),
]

TOOL_MATERIAL_PATTERN = re.compile(
    r"\b(Р6М5|Р18|Р9|Т5К10|Т15К6|Т30К4|ВК8|ВК6|ВК3М|CBN|эльбор|быстрорежущ\w+|тверд\w+\s+сплав\w*)\b",
    flags=re.IGNORECASE,
)

MATERIAL_PATTERNS = [
    re.compile(
        r"((?:сталь|чугун\s*(?:серый|ковкий|высокопрочный)?|алюмини\w*\s*сплав\w*|бронз\w*|латун\w*|титан\w*\s*сплав\w*)"
        r"[^;\n\)]{0,45}?(?:HB|HRC|ГПа|МПа)?)",
        flags=re.IGNORECASE,
    )
]

EQUIPMENT_PATTERN = re.compile(
    r"([А-ЯЁа-яё\-]+\s*(?:сверлильн\w+|токарн\w+|фрезерн\w+|шлифовальн\w+|расточн\w+)\s*станк\w*)",
    flags=re.IGNORECASE,
)


def extract_formula(lines: List[str]) -> str:
    """Извлекает расчётную формулу карты из текстовых строк шапки."""
    for line in lines:
        clean = " ".join(line.strip().split())
        if not clean:
            continue

        # Ищем явные конструкции вида "Формула: T = ..." или "T_шт = ..."
        match = re.search(
            r"(?:формула(?:\s+расч[её]та)?\s*[:\-]?\s*)?"
            r"\b(T(?:_[a-zA-Zа-яА-Я0-9]+|[а-яА-Яa-zA-Z0-9]*)|N_вр)\s*=\s*(.+)$",
            clean,
            flags=re.IGNORECASE,
        )
        if match:
            expr = match.group(2).strip().rstrip(".;")
            expr = expr.replace("×", "*").replace("·", "*").replace(",", ".")
            return expr

    return "Ttbl"


def extract_surface_and_accuracy(text: str) -> Dict[str, Any]:
    """Извлекает параметры шероховатости (Ra/Rz) и квалитет (IT) из текста шапки."""
    extra: Dict[str, Any] = {}

    ra_match = re.search(r"\bRa\s*[=:]?\s*(\d+(?:[.,]\d+)?(?:\s*(?:\.\.\.|-|–)\s*\d+(?:[.,]\d+)?)?)", text)
    if ra_match:
        extra["roughness_ra"] = ra_match.group(1).replace(",", ".").replace(" ", "")

    rz_match = re.search(r"\bRz\s*[=:]?\s*(\d+(?:[.,]\d+)?(?:\s*(?:\.\.\.|-|–)\s*\d+(?:[.,]\d+)?)?)", text)
    if rz_match:
        extra["roughness_rz"] = rz_match.group(1).replace(",", ".").replace(" ", "")

    it_match = re.search(
        r"(?:(\d+(?:\s*(?:\.\.\.|-|–)\s*\d+)?)\s*квалитет|\bIT\s*(\d+(?:\s*(?:\.\.\.|-|–)\s*\d+)?))",
        text,
        flags=re.IGNORECASE,
    )
    if it_match:
        raw_it = it_match.group(1) or it_match.group(2)
        extra["it_grade"] = raw_it.replace(" ", "")

    ld_match = re.search(r"\bL\s*/\s*D\s*([<>≤≥=]+\s*\d+(?:[.,]\d+)?)", text, flags=re.IGNORECASE)
    if ld_match:
        extra["ld_ratio"] = ld_match.group(1).replace(",", ".").replace(" ", "")

    return extra


def parse_card_header(
    lines: List[str],
    fallback_stem: str = "DOC",
    card_index: int = 1,
) -> ParsedCardHeader:
    """
    Выполняет полный семантический разбор шапки нормировочной карты.
    Возвращает card_id, card_title, формулу и структуру ApplicabilityConditions.
    """
    non_empty = [" ".join(line.strip().split()) for line in lines if line and line.strip()]
    full_text = "\n".join(non_empty)

    card_number: Optional[str] = None
    card_title = f"Карта {card_index:02d} ({fallback_stem})"

    for line in non_empty:
        card_match = re.search(r"Карта\s*(?:№\s*)?(\d+[а-яА-Яa-zA-Z]?)", line, flags=re.IGNORECASE)
        if card_match:
            card_number = card_match.group(1).upper()
            card_title = line
            break

    clean_stem = re.sub(r"[^A-Za-z0-9_]+", "_", fallback_stem).strip("_").upper() or "DOC"
    if card_number:
        card_id = f"{clean_stem}_CARD_{card_number.zfill(2)}"
    else:
        card_id = f"{clean_stem}_CARD_{card_index:02d}"

    operation_type = "Механическая обработка"
    for pattern, op_name in OPERATION_PATTERNS:
        if re.search(pattern, full_text, flags=re.IGNORECASE):
            operation_type = op_name
            break

    production_type: Optional[str] = None
    if re.search(r"единичн\w*\s+и\s+мелкосерийн\w*", full_text, flags=re.IGNORECASE):
        production_type = "Единичное и мелкосерийное"
    elif re.search(r"среднесерийн\w*", full_text, flags=re.IGNORECASE):
        production_type = "Среднесерийное"
    elif re.search(r"крупносерийн\w*|массов\w*", full_text, flags=re.IGNORECASE):
        production_type = "Крупносерийное и массовое"

    material_group: Optional[str] = None
    for pat in MATERIAL_PATTERNS:
        mat_match = pat.search(full_text)
        if mat_match:
            material_group = mat_match.group(1).strip().rstrip(".,;")
            break

    equipment_filter: Optional[str] = None
    eq_match = EQUIPMENT_PATTERN.search(full_text)
    if eq_match:
        equipment_filter = eq_match.group(1).strip()

    tool_material: Optional[str] = None
    tool_match = TOOL_MATERIAL_PATTERN.search(full_text)
    if tool_match:
        tool_material = tool_match.group(1).upper()

    extra_params = extract_surface_and_accuracy(full_text)

    formula = extract_formula(non_empty)
    result_unit = "hour" if re.search(r"нормо-?час", full_text, flags=re.IGNORECASE) else "min"

    applicability = ApplicabilityConditions(
        operation_type=operation_type,
        production_type=production_type,
        material_group=material_group,
        equipment_filter=equipment_filter,
        tool_material=tool_material,
        extra_params=extra_params,
    )

    return ParsedCardHeader(
        card_id=card_id,
        card_title=card_title,
        calculation_formula=formula,
        result_unit=result_unit,
        applicability=applicability,
    )
