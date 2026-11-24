from __future__ import annotations

import re
from typing import List, Optional, Tuple

from norm_importer.schema import ModifierOperation, NoteCoefficientRule

# Общие словесные условия (проверяются ПОСЛЕ явных числовых ограничений L/D)
TEXT_CONDITION_RULES: List[Tuple[str, str, bool | str]] = [
    (r"глух\w*\s+отверст", "is_blind_hole", True),
    (r"глубок\w*\s+отверст", "l_to_d_ratio_gt_3", True),
    (r"тонкостен\w*|сварн\w*\s+конструкц", "is_thin_walled", True),
    (r"с\s+покрыти\w*", "has_coating", True),
    (r"без\s+корк\w*", "without_crust", True),
    (r"поджати\w*\s+центр\w*", "with_tailstock_center", True),
    (r"местн\w*\s+подъ[её]мник", "local_hoist", True),
    (r"чугун", "material_group", "cast_iron"),
    (r"л[её]гк\w*\s+сплав|алюмини", "material_group", "aluminum"),
]


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
    # Не отбрасываем запятую на конце, чтобы оборванное "1," не превращалось в 1.0
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
    Явные одно- и двусторонние числовые ограничения L/D имеют приоритет над словесными признаками.
    """
    lower = line.lower()

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
            return "l_to_d_ratio_gt_5", True, None
        if not left_num and right_op == ">" and r_val == 3.0:
            return "l_to_d_ratio_gt_3", True, None

        right_part = f"{right_op}{right_num.replace(',', '.')}"
        if left_num and left_op:
            left_part = f"{left_num.replace(',', '.')}{left_op}"
            full_expr = f"{left_part}L/D{right_part}"
        else:
            full_expr = f"L/D{right_part}"

        return (
            "l_to_d_custom",
            full_expr,
            f"Нестандартное ограничение L/D ({full_expr}) сохранено как пользовательское условие.",
        )

    ld_mult = re.search(r"\bl\s*([<>≤≥]=?)\s*(\d+(?:[.,]\d+)?)\s*d\b", lower)
    if ld_mult:
        op, num_str = ld_mult.groups()
        val = float(num_str.replace(",", "."))
        if op == ">" and val == 5.0:
            return "l_to_d_ratio_gt_5", True, None
        if op == ">" and val == 3.0:
            return "l_to_d_ratio_gt_3", True, None
        return (
            "l_to_d_custom",
            f"L{op}{val}D",
            f"Нестандартное ограничение L{op}{val}D сохранено как пользовательское условие.",
        )

    for pattern, key, val in TEXT_CONDITION_RULES:
        if re.search(pattern, lower, flags=re.IGNORECASE):
            return key, val, None

    return f"custom_condition_{fallback_idx}", True, None

def _detect_target_variable(line: str) -> str:
    lower = line.lower()
    if "установ" in lower or "t_ву" in lower or "tvu" in lower:
        return "Tvu"
    if "выдерж" in lower or "tvid" in lower:
        return "Tvid"
    return "Ttbl"


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

        # 1. Мультипликативный коэффициент: захватываем весь токен до пробела/конца фразы
        mul_match = re.search(
            r"(?:коэффициент\w*|умножать\s+на|применять\s+с\s+[КK]\s*=|\b[КK]\s*=)\s*([^\s;]+)",
            clean_line,
            flags=re.IGNORECASE,
        )
        # 2. Добавление времени с обязательной проверкой следующей за числом единицы
        add_match = re.search(
            r"(?:добавлять|прибавить|увеличивать\s+на)\s+([^\s;]+)(?:\s+([а-яА-Яa-zA-Z\-]+))?",
            clean_line,
            flags=re.IGNORECASE,
        )
        # 3. Вычитание времени с обязательной проверкой следующей за числом единицы
        sub_match = re.search(
            r"(?:уменьшать\s+на|вычесть|вычитать)\s+([^\s;]+)(?:\s+([а-яА-Яa-zA-Z\-]+))?",
            clean_line,
            flags=re.IGNORECASE,
        )

        op: ModifierOperation
        factor: float

        if mul_match:
            raw_num = mul_match.group(1)
            parsed_num = _parse_strict_number(raw_num)
            if parsed_num is None:
                warnings.append(f"Неоднозначное или повреждённое значение коэффициента '{raw_num}' в примечании: {clean_line}")
                continue
            op = ModifierOperation.MULTIPLY
            factor = parsed_num

        elif add_match or sub_match:
            is_add = add_match is not None
            match = add_match if is_add else sub_match
            assert match is not None
            raw_num = match.group(1)
            raw_unit = match.group(2) or ""

            parsed_num = _parse_strict_number(raw_num)
            if parsed_num is None:
                warnings.append(f"Неоднозначное значение поправки времени '{raw_num}' в примечании: {clean_line}")
                continue

            if not raw_unit:
                warnings.append(f"Не указана единица измерения времени для поправки '{raw_num}' в примечании: {clean_line}")
                continue

            converted = _convert_time_to_card_unit(parsed_num, raw_unit, result_unit)
            if converted is None:
                warnings.append(f"Неизвестная единица времени '{raw_unit}' в примечании: {clean_line}")
                continue

            op = ModifierOperation.ADD if is_add else ModifierOperation.SUBTRACT
            factor = converted

        else:
            continue

        rule_idx += 1
        cond_key, cond_val, cond_warn = _detect_condition(clean_line, rule_idx)
        if cond_warn:
            warnings.append(cond_warn)
        target_var = _detect_target_variable(clean_line)

        rules.append(
            NoteCoefficientRule(
                note_id=f"NOTE_{rule_idx:02d}",
                raw_text=clean_line,
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
