from __future__ import annotations

import re
from typing import List, Optional, Tuple

from norm_importer.schema import ModifierOperation, NoteCoefficientRule

TEXT_CONDITION_RULES: List[Tuple[str, str, bool | str]] = [
    (r"\bглух\w*\s+отверст", "is_blind_hole", True),
    (r"\bглубок\w*\s+отверст", "l_to_d_ratio_gt_3", True),
    (r"\bтонкостен\w*|\bсварн\w*\s+конструкц", "is_thin_walled", True),
    (r"\bс\s+покрыти\w*", "has_coating", True),
    (r"\bбез\s+корк\w*", "without_crust", True),
    (r"\bподжати\w*\s+центр\w*", "with_tailstock_center", True),
    (r"\bместн\w*\s+подъ[её]мник", "local_hoist", True),
    (r"\bчугун\w*", "material_group", "cast_iron"),
    (r"\bл[её]гк\w*\s+сплав\w*|\bалюмини\w*", "material_group", "aluminum"),
]

NEGATED_CONDITION_PATTERN = re.compile(
    r"\b(?:не\s+глух\w*|неглух\w*|не\s+глубок\w*|неглубок\w*|не\s+тонкостен\w*|нетонкостен\w*|без\s+покрыти\w*)\b",
    flags=re.IGNORECASE,
)


def clean_ocr_numeric_token(raw_value: str) -> str:
    """
    Пост-обработка типичных ошибок OCR в числовых ячейках и коэффициентах:
    - замена букв 'О'/'O' на '0', 'З' на '3', 'Б' на '6', 'I'/'l'/'|' на '1' в числовом окружении;
    - удаление пробелов и приведение разделителей (',', ';', ':') к '.'.
    """
    text = raw_value.strip()
    if not text or text in {"-", "–", "—", "null", "None"}:
        return text

    text = re.sub(r"\s*([,.;:])\s*", ".", text)

    if re.search(r"\d", text):
        text = re.sub(r"[ОOоo]", "0", text)
        text = text.replace("З", "3")
        text = text.replace("Б", "6")
        text = re.sub(r"[Il|]", "1", text)

    return text


def clean_ocr_text_block(text: str) -> str:
    """Склеивает пробелы внутри чисел и исправляет OCR-искажения в числовых токенах текста."""
    collapsed = re.sub(
        r"(?<=[\dОOоoЗБIl|])\s*([,.;:])\s*(?=[\dОOоoЗБIl|])",
        ".",
        text,
    )

    def _fix_token(match: re.Match[str]) -> str:
        token = match.group(0)
        fixed = clean_ocr_numeric_token(token)
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", fixed):
            return fixed
        return token

    return re.sub(r"\b[\dОOоoЗБIl|]+\.[\dОOоoЗБIl|]+\b", _fix_token, collapsed)


def _parse_strict_number(raw_token: str) -> Optional[float]:
    """Проверяет числовой фрагмент целиком; при невосстановимом или оборванном токене возвращает None."""
    cleaned_token = raw_token.rstrip(".;:)")
    fixed = clean_ocr_numeric_token(cleaned_token)
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", fixed):
        return float(fixed)
    return None


def _convert_time_to_card_unit(value: float, unit_token: str, result_unit: str) -> Optional[float]:
    """Переводит поправку времени в единицу измерения карты ('min' или 'hour')."""
    u = unit_token.strip().lower().rstrip(".")
    if re.fullmatch(r"(?:с|сек|секунд\w*)", u):
        minutes = value / 60.0
    elif re.fullmatch(r"(?:м|мин|минут\w*)", u):
        minutes = value
    elif re.fullmatch(r"(?:ч|час\w*|нормо-?час\w*)", u):
        minutes = value * 60.0
    else:
        return None

    if result_unit == "min":
        return round(minutes, 6)
    if result_unit == "hour":
        return round(minutes / 60.0, 6)
    return None


def _detect_condition(line: str, fallback_idx: int) -> Tuple[str, bool | str, Optional[str]]:
    """
    Определяет условие срабатывания примечания.
    Учитывает отрицания (B14) и составные условия (B15).
    """
    lower = line.lower()

    neg_match = NEGATED_CONDITION_PATTERN.search(lower)
    if neg_match:
        return (
            f"negated_condition_{fallback_idx}",
            neg_match.group(0),
            f"Отрицательное условие '{neg_match.group(0)}' не поддерживается автоматически и сохранено без инверсии: {line}",
        )

    matched_conditions: List[Tuple[str, bool | str]] = []

    ld_bilateral = re.search(
        r"(?:(\d+(?:[.,]\d+)?)\s*([<>≤≥]=?)\s*)?"
        r"\bl\s*/\s*d\b"
        r"\s*([<>≤≥]=?)\s*(\d+(?:[.,]\d+)?)",
        lower,
    )
    if ld_bilateral:
        left_num, left_op, right_op, right_num = ld_bilateral.groups()
        r_val = float(right_num.replace(",", "."))

        if not left_num and right_op == ">" and r_val == 5.0:
            matched_conditions.append(("l_to_d_ratio_gt_5", True))
        elif not left_num and right_op == ">" and r_val == 3.0:
            matched_conditions.append(("l_to_d_ratio_gt_3", True))
        else:
            right_part = f"{right_op}{right_num.replace(',', '.')}"
            if left_num and left_op:
                left_part = f"{left_num.replace(',', '.')}{left_op}"
                full_expr = f"{left_part}L/D{right_part}"
            else:
                full_expr = f"L/D{right_part}"
            matched_conditions.append(("l_to_d_custom", full_expr))

    ld_mult = re.search(r"\bl\s*([<>≤≥]=?)\s*(\d+(?:[.,]\d+)?)\s*d\b", lower)
    if ld_mult and not ld_bilateral:
        op, num_str = ld_mult.groups()
        val = float(num_str.replace(",", "."))
        if op == ">" and val == 5.0:
            matched_conditions.append(("l_to_d_ratio_gt_5", True))
        elif op == ">" and val == 3.0:
            matched_conditions.append(("l_to_d_ratio_gt_3", True))
        else:
            matched_conditions.append(("l_to_d_custom", f"L{op}{val}D"))

    for pattern, key, val in TEXT_CONDITION_RULES:
        if re.search(pattern, lower, flags=re.IGNORECASE):
            if (key, val) not in matched_conditions:
                matched_conditions.append((key, val))

    if len(matched_conditions) == 1:
        k, v = matched_conditions[0]
        warn = (
            f"Нестандартное ограничение L/D ({v}) сохранено как пользовательское условие."
            if k == "l_to_d_custom"
            else None
        )
        return k, v, warn

    if len(matched_conditions) > 1:
        serialized = ";".join(f"{k}={v}" for k, v in matched_conditions)
        return (
            "compound_condition",
            serialized,
            f"Обнаружено составное условие ({serialized}); проверьте применимость всех признаков: {line}",
        )

    return f"custom_condition_{fallback_idx}", True, None


def _detect_target_variable(line: str) -> str:
    lower = line.lower()
    if "установ" in lower or "t_ву" in lower or "tvu" in lower:
        return "Tvu"
    if "выдерж" in lower or "tvid" in lower:
        return "Tvid"
    return "Ttbl"


def _split_note_clauses(line: str) -> List[str]:
    """
    Разбивает сложный абзац примечания на независимые смысловые клаузы
    (по ';' или перед новым условием вида ', при ...'), чтобы привязать каждый коэффициент к своему условию.
    """
    parts = [p.strip() for p in line.split(";") if p.strip()]
    clauses: List[str] = []
    for part in parts:
        sub_parts = re.split(r",\s*(?=при\s+)", part, flags=re.IGNORECASE)
        clauses.extend(sp.strip() for sp in sub_parts if sp.strip())
    return clauses


MUL_PATTERN = re.compile(
    r"(?:(?:коэффициент\w*|умножать\s+на|применять\s+с)\s*(?:[КK]\s*=\s*)?|\b[КK]\s*=\s*)([^\s;]+)",
    flags=re.IGNORECASE,
)

ADD_PATTERN = re.compile(
    r"(?:добавлять|прибавлять|прибавить|увеличивать\s+на)\s+([^\s;]+)(?:\s+([а-яА-Яa-zA-Z\-]+))?",
    flags=re.IGNORECASE,
)

SUB_PATTERN = re.compile(
    r"(?:уменьшать\s+на|вычесть|вычитать)\s+([^\s;]+)(?:\s+([а-яА-Яa-zA-Z\-]+))?",
    flags=re.IGNORECASE,
)


def _extract_clause_actions(
    clause: str,
    result_unit: str,
    warnings: List[str],
) -> List[Tuple[ModifierOperation, float]]:
    """Извлекает все последовательные действия (умножение, добавление, вычитание) в порядке их следования (B16)."""
    actions_with_pos: List[Tuple[int, ModifierOperation, float]] = []

    for m in MUL_PATTERN.finditer(clause):
        raw_num = m.group(1)
        parsed_num = _parse_strict_number(raw_num)
        if parsed_num is None:
            warnings.append(
                f"Неоднозначное или повреждённое значение коэффициента '{raw_num}' в примечании: {clause}"
            )
            continue
        actions_with_pos.append((m.start(), ModifierOperation.MULTIPLY, parsed_num))

    for is_add, pattern in ((True, ADD_PATTERN), (False, SUB_PATTERN)):
        for m in pattern.finditer(clause):
            raw_num = m.group(1)
            raw_unit = m.group(2) or ""
            parsed_num = _parse_strict_number(raw_num)
            if parsed_num is None:
                warnings.append(f"Неоднозначное значение поправки времени '{raw_num}' в примечании: {clause}")
                continue
            if not raw_unit:
                warnings.append(
                    f"Не указана единица измерения времени для поправки '{raw_num}' в примечании: {clause}"
                )
                continue
            converted = _convert_time_to_card_unit(parsed_num, raw_unit, result_unit)
            if converted is None:
                warnings.append(f"Неизвестная единица времени '{raw_unit}' в примечании: {clause}")
                continue
            op = ModifierOperation.ADD if is_add else ModifierOperation.SUBTRACT
            actions_with_pos.append((m.start(), op, converted))

    actions_with_pos.sort(key=lambda item: item[0])
    return [(op, val) for _, op, val in actions_with_pos]


def parse_notes_with_diagnostics(
    notes_lines: List[str],
    result_unit: str = "min",
) -> Tuple[List[NoteCoefficientRule], List[str]]:
    """
    Разбирает примечания в структурированные правила NoteCoefficientRule
    и возвращает кортеж (rules, warnings).
    """
    rules: List[NoteCoefficientRule] = []
    warnings: List[str] = []
    rule_idx = 0

    for raw_line in notes_lines:
        clean_line = clean_ocr_text_block(" ".join(raw_line.strip().split()))
        if not clean_line:
            continue

        clauses = _split_note_clauses(clean_line)
        for clause in clauses:
            actions = _extract_clause_actions(clause, result_unit, warnings)
            if not actions:
                continue

            cond_key, cond_val, cond_warn = _detect_condition(clause, rule_idx + 1)
            if cond_warn:
                warnings.append(cond_warn)
            target_var = _detect_target_variable(clause)

            for op, factor in actions:
                rule_idx += 1
                rules.append(
                    NoteCoefficientRule(
                        note_id=f"NOTE_{rule_idx:02d}",
                        raw_text=clause,
                        condition_key=cond_key,
                        condition_value=cond_val,
                        modifier_operation=op,
                        target_variable=target_var,
                        factor=factor,
                    )
                )

    return rules, warnings


def parse_notes_to_rules(
    notes_lines: List[str],
    result_unit: str = "min",
) -> List[NoteCoefficientRule]:
    """Обратно совместимая обёртка: возвращает только список правил."""
    rules, _ = parse_notes_with_diagnostics(notes_lines, result_unit=result_unit)
    return rules