from __future__ import annotations

import re
from typing import List, Tuple

from norm_importer.schema import ModifierOperation, NoteCoefficientRule

CONDITION_RULES: List[Tuple[str, str, bool | str]] = [
    (r"глух\w*\s+отверст", "is_blind_hole", True),
    (r"глубок\w*\s+отверст|l\s*/\s*d\s*>\s*3|l\s*>\s*3\s*d", "l_to_d_ratio_gt_3", True),
    (r"l\s*/\s*d\s*>\s*5|l\s*>\s*5\s*d", "l_to_d_ratio_gt_5", True),
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
    Пост-обработка типичных ошибок OCR в числовых ячейках и коэффициентах.
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
    """Исправляет типичные OCR-искажения в тексте примечаний и формул."""
    cleaned = text
    # Исправление "коэффициент 1,З" / "K = О,85"
    cleaned = re.sub(
        r"(\b[КK]\s*=\s*|[кК]оэффициент\w*\s+|на\s+)([ОOоo])([,.\d])",
        lambda m: f"{m.group(1)}0{m.group(3)}",
        cleaned,
    )
    cleaned = re.sub(r"(?<=\d),([ОOоo])\b", ".0", cleaned)
    cleaned = re.sub(r"(?<=\d),З\b", ".3", cleaned)
    return cleaned


def _detect_condition(line: str, fallback_idx: int) -> Tuple[str, bool | str]:
    lower = line.lower()
    for pattern, key, val in CONDITION_RULES:
        if re.search(pattern, lower, flags=re.IGNORECASE):
            return key, val
    return f"custom_condition_{fallback_idx}", True


def _detect_target_variable(line: str) -> str:
    lower = line.lower()
    if "установ" in lower or "t_ву" in lower or "tvu" in lower:
        return "Tvu"
    if "выдерж" in lower or "tvid" in lower:
        return "Tvid"
    return "Ttbl"


def parse_notes_to_rules(notes_lines: List[str]) -> List[NoteCoefficientRule]:
    """
    Преобразует блок текстовых примечаний нормировочной карты в список
    структурированных правил NoteCoefficientRule (multiply, add, subtract).
    """
    rules: List[NoteCoefficientRule] = []
    rule_idx = 0

    for raw_line in notes_lines:
        clean_line = clean_ocr_text_block(" ".join(raw_line.strip().split()))
        if not clean_line:
            continue

        add_match = re.search(
            r"(?:добавлять|прибавить|увеличивать\s+на|\+)\s*(\d+(?:[.,]\d+)?)\s*(?:мин)?",
            clean_line,
            flags=re.IGNORECASE,
        )
        sub_match = re.search(
            r"(?:уменьшать\s+на|вычесть|вычитать)\s*(\d+(?:[.,]\d+)?)\s*(?:мин)?",
            clean_line,
            flags=re.IGNORECASE,
        )
        mul_match = re.search(
            r"(?:коэффициент\w*|умножать\s+на|применять\s+с\s+[КK]\s*=|\b[КK]\s*=)\s*(\d+(?:[.,]\d+)?)",
            clean_line,
            flags=re.IGNORECASE,
        )

        op: ModifierOperation
        factor: float

        if mul_match:
            op = ModifierOperation.MULTIPLY
            factor = float(mul_match.group(1).replace(",", "."))
        elif add_match:
            op = ModifierOperation.ADD
            factor = float(add_match.group(1).replace(",", "."))
        elif sub_match:
            op = ModifierOperation.SUBTRACT
            factor = float(sub_match.group(1).replace(",", "."))
        else:
            continue

        rule_idx += 1
        cond_key, cond_val = _detect_condition(clean_line, rule_idx)
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

    return rules
