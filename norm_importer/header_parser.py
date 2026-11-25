from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from norm_importer.schema import ApplicabilityConditions


@dataclass
class ParsedCardHeader:
    card_id: str
    card_title: str
    calculation_formula: str
    result_unit: str
    applicability: ApplicabilityConditions
    warnings: List[str] = field(default_factory=list)


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

EQUIPMENT_PATTERN = re.compile(
    r"([А-ЯЁа-яё\-]+\s*(?:сверлильн\w+|токарн\w+|фрезерн\w+|шлифовальн\w+|расточн\w+)\s*станк\w*)",
    flags=re.IGNORECASE,
)

MATERIAL_WITH_HARDNESS_PATTERN = re.compile(
    r"((?:сталь|чугун(?:\s+(?:серый|ковкий|высокопрочный))?|алюмини\w*\s+сплав\w*|бронз\w*|латун\w*|титан\w*\s+сплав\w*)"
    r"(?:[\s,:\-]*(?:(?:HB|HRC|HV|ГПа|МПа)\s*)?\d+(?:[.,]\d+)?(?:\s*(?:\.\.\.|\.\.|-|–|—)\s*\d+(?:[.,]\d+)?)?\s*(?:HB|HRC|HV|ГПа|МПа))?)",
    flags=re.IGNORECASE,
)

HARDNESS_ONLY_PATTERN = re.compile(
    r"((?:HB|HRC|HV)\s*\d+(?:[.,]\d+)?(?:\s*(?:\.\.\.|\.\.|-|–|—)\s*\d+(?:[.,]\d+)?)?(?:\s*(?:ГПа|МПа))?|"
    r"\d+(?:[.,]\d+)?(?:\s*(?:\.\.\.|\.\.|-|–|—)\s*\d+(?:[.,]\d+)?)?\s*(?:HB|HRC|HV))",
    flags=re.IGNORECASE,
)

LD_RATIO_PATTERN = re.compile(
    r"(?:(\d+(?:[.,]\d+)?)\s*([<>≤≥]=?)\s*)?"
    r"\bL\s*/\s*D\b"
    r"\s*([<>≤≥]=?|=)\s*(\d+(?:[.,]\d+)?)",
    flags=re.IGNORECASE,
)

CYRILLIC_VAR_REPLACEMENTS: List[Tuple[str, str]] = [
    (r"\b[ТT]_?табл\.?\b", "Ttbl"),
    (r"\b[ТT]_?шт\.?\b", "Tsht"),
    (r"\b[ТT]_?оп\.?\b", "Top"),
    (r"\b[ТT]_?вспом\.?\b", "Tvsp"),
    (r"\b[ТT]_?осн\.?\b", "Tosn"),
    (r"\b[ТT]_?ву\b", "Tvu"),
    (r"\b[ТT]_?выд\b", "Tvid"),
    (r"\b[КK]_?([а-яА-Яa-zA-Z0-9]+)\b", r"K_\1"),
]


def _normalize_formula_expression(raw_expr: str) -> str:
    expr = raw_expr.strip().rstrip(".;")
    expr = expr.replace("×", "*").replace("·", "*").replace(",", ".")
    for pattern, repl in CYRILLIC_VAR_REPLACEMENTS:
        expr = re.sub(pattern, repl, expr, flags=re.IGNORECASE)
    return " ".join(expr.split())


def extract_formula_with_diagnostics(lines: List[str]) -> Tuple[str, List[str]]:
    """Извлекает расчётную формулу карты и диагностирует нераспознанные явные формулы."""
    warnings: List[str] = []
    for line in lines:
        clean = " ".join(line.strip().split())
        if not clean:
            continue

        has_formula_prefix = bool(re.search(r"\bформула(?:\s+расч[её]та)?\s*[:\-]", clean, flags=re.IGNORECASE))
        match = re.search(
            r"(?:формула(?:\s+расч[её]та)?\s*[:\-]?\s*)?"
            r"(?<![A-Za-zА-Яа-яЁё0-9_])"
            r"(?:[ТT](?:_[a-zA-Zа-яА-ЯёЁ0-9]+|[а-яА-ЯёЁa-zA-Z0-9]*)|[NН]_?вр)"
            r"\s*=\s*(.+)$",
            clean,
            flags=re.IGNORECASE,
        )
        if match:
            expr = _normalize_formula_expression(match.group(1))
            if expr:
                return expr, warnings

        if has_formula_prefix:
            warnings.append(f"Не удалось распознать выражение в строке формулы: '{clean}'; использовано Ttbl.")

    return "Ttbl", warnings


def extract_formula(lines: List[str]) -> str:
    """Извлекает расчётную формулу карты из текстовых строк шапки."""
    formula, _ = extract_formula_with_diagnostics(lines)
    return formula


def detect_result_unit(lines: List[str], formula: str) -> Tuple[str, List[str]]:
    """Определяет единицу измерения результата ('min', 'hour', 'pct') и проверяет противоречия."""
    warnings: List[str] = []
    detected_units: set[str] = set()

    for line in lines:
        clean = " ".join(line.strip().split())
        if not clean:
            continue

        explicit_match = re.search(
            r"(?:единиц[аы]\s+измерения|ед\.?\s*изм\.?|размерность)\s*[:\-]?\s*([а-яА-Яa-zA-Z%\-\.]+)",
            clean,
            flags=re.IGNORECASE,
        )
        if explicit_match:
            token = explicit_match.group(1).strip().lower().rstrip(".")
            if token in {"ч", "час", "часа", "часов", "нормо-час", "нормочас", "hour", "h"}:
                detected_units.add("hour")
            elif token in {"мин", "минута", "минуты", "минут", "min", "m"}:
                detected_units.add("min")
            elif token in {"%", "проц", "процент", "проценты", "pct"}:
                detected_units.add("pct")
            else:
                warnings.append(f"Неизвестная единица измерения в шапке: '{explicit_match.group(1)}'.")

        if re.search(r"нормо-?час", clean, flags=re.IGNORECASE):
            detected_units.add("hour")

    if len(detected_units) > 1:
        warnings.append(f"Обнаружены противоречивые единицы измерения в шапке: {sorted(detected_units)}.")
        unit = "hour" if "hour" in detected_units else "min"
    elif len(detected_units) == 1:
        unit = next(iter(detected_units))
    else:
        unit = "min"

    if unit == "hour" and re.search(r"/\s*60\b", formula):
        warnings.append("Возможный конфликт: единица измерения указана в часах, но формула содержит деление на 60.")

    return unit, warnings


def extract_surface_and_accuracy(text: str) -> Dict[str, Any]:
    """Извлекает параметры шероховатости (Ra/Rz), квалитет (IT), твёрдость и ограничения L/D."""
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

    ld_match = LD_RATIO_PATTERN.search(text)
    if ld_match:
        left_num, left_op, right_op, right_num = ld_match.groups()
        right_part = f"{right_op}{right_num.replace(',', '.')}"
        if left_num and left_op:
            left_part = f"{left_num.replace(',', '.')}{left_op}"
            extra["ld_ratio"] = f"{left_part}L/D{right_part}"
        else:
            extra["ld_ratio"] = right_part

    hardness_match = HARDNESS_ONLY_PATTERN.search(text)
    if hardness_match:
        extra["hardness"] = " ".join(hardness_match.group(1).strip().split())

    return extra


def parse_card_header(
    lines: List[str],
    fallback_stem: str = "DOC",
    card_index: int = 1,
) -> ParsedCardHeader:
    """
    Выполняет полный семантический разбор шапки нормировочной карты.
    Возвращает card_id, card_title, формулу, единицу измерения и структуру ApplicabilityConditions.
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
    mat_match = MATERIAL_WITH_HARDNESS_PATTERN.search(full_text)
    if mat_match:
        material_group = " ".join(mat_match.group(1).strip().rstrip(".,;").split())

    equipment_filter: Optional[str] = None
    eq_match = EQUIPMENT_PATTERN.search(full_text)
    if eq_match:
        equipment_filter = eq_match.group(1).strip()

    tool_material: Optional[str] = None
    tool_match = TOOL_MATERIAL_PATTERN.search(full_text)
    if tool_match:
        tool_material = tool_match.group(1).upper()

    extra_params = extract_surface_and_accuracy(full_text)

    formula, formula_warnings = extract_formula_with_diagnostics(non_empty)
    result_unit, unit_warnings = detect_result_unit(non_empty, formula)

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
        warnings=[*formula_warnings, *unit_warnings],
    )
