from __future__ import annotations

import re
from typing import List, Optional, Tuple

from norm_importer.schema import AxisCondition, TableGrid

AXIS_KEYWORDS: List[Tuple[str, str]] = [
    (r"диаметр|\bD\b|Ø", "diameter_d_mm"),
    (r"длин|глубин|\bL\b|\bH\b", "length_l_mm"),
    (r"припуск|подач|\bt\b|\bS\b", "allowance_t_mm"),
    (r"ширин|\bB\b", "width_b_mm"),
    (r"масс|\bM\b|вес", "mass_kg"),
    (r"стол|габарит", "table_size_mm"),
    (r"шаг|\bP\b", "thread_pitch_mm"),
    (r"квалитет|\bIT\b", "it_grade"),
]

INTERVAL_PATTERN = re.compile(
    r"^\s*[+-]?\d+(?:[.,]\d+)?\s*(?:-|–|—|\.\.\.|\.\.)\s*[+-]?\d+(?:[.,]\d+)?\s*$"
)

SINGLE_NUMBER_PATTERN = re.compile(
    r"^\s*(?:(?:до|св\.?|свыше|не\s+более|≤|>=|<|>)\s*)?([+-]?\d+(?:[.,]\d+)?)\s*$",
    flags=re.IGNORECASE,
)

BILATERAL_RANGE_PATTERN = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*<\s*[A-Za-zА-Яа-яЁё]+\s*(?:≤|<=|<)\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:мм|см|м|кг|шт)?\s*$"
)

def _cell_to_clean_str(cell: object) -> str:
    if cell is None:
        return ""
    return " ".join(str(cell).strip().split())


def detect_axis_semantics(header_text: str, default_name: str) -> Tuple[str, AxisCondition]:
    """Определяет семантическое имя параметра и условие ('до' / 'свыше') по тексту шапки."""
    clean = " ".join(header_text.strip().split())
    lower = clean.lower()

    condition = AxisCondition.UP_TO
    # Сначала проверяем отрицательные конструкции ("не более", "не свыше") и "до"
    if re.search(r"\bне\s+(?:более|свыше)\b|\bдо\b|≤|<=", lower):
        condition = AxisCondition.UP_TO
    elif re.search(r"(?:^|\s)св\.(?=\s*\d|\s*$)|\bсвыше\b|\bболее\b|>", lower):
        condition = AxisCondition.OVER

    param_name = default_name
    for pattern, canonical_name in AXIS_KEYWORDS:
        if re.search(pattern, clean, flags=re.IGNORECASE):
            param_name = canonical_name
            break

    return param_name, condition

def _parse_axis_label(label: str, warnings: List[str], axis_kind: str) -> float | str:
    """Разбирает метку оси: одиночное число -> float, интервалы '5–10' и '20 < L ≤ 40' -> строка + диагностика."""
    cleaned = label.strip()
    if INTERVAL_PATTERN.match(cleaned) or BILATERAL_RANGE_PATTERN.match(cleaned):
        warnings.append(
            f"Интервал на оси ({axis_kind}) '{cleaned}' сохранён как строковая метка без потери верхней границы."
        )
        return cleaned

    single_match = SINGLE_NUMBER_PATTERN.match(cleaned)
    if single_match:
        return float(single_match.group(1).replace(",", "."))

    prefixed_match = re.search(
        r"(?:^|\s)(?:[A-Za-zА-Яа-яЁё]+\s+)?(?:до|св\.?|свыше|≤|>=|<|>)\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:мм|см|м|кг)?\s*$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if prefixed_match:
        return float(prefixed_match.group(1).replace(",", "."))

    return cleaned

def extract_numeric_tokens(cells: List[str]) -> List[float]:
    """Извлекает числовые границы диапазонов из списка ячеек."""
    values: List[float] = []
    for item in cells:
        match = re.search(r"([+-]?\d+(?:[.,]\d+)?)", str(item))
        if match:
            values.append(float(match.group(1).replace(",", ".")))
    return values


def _is_numeric_row_label(cell_text: str) -> bool:
    """Проверяет, является ли левая ячейка началом строк данных (число, интервал или 'св. 2500')."""
    cleaned = cell_text.strip()
    if not cleaned:
        return False
    return bool(re.match(r"^(?:св\.?\s*|до\s*)?[+-]?\d+(?:[.,]\d+)?", cleaned, flags=re.IGNORECASE))


def _row_has_numeric_data(row: List[str]) -> bool:
    """Проверяет, есть ли в ячейках данных строки хотя бы одно числовое значение."""
    from norm_importer.schema import _parse_and_validate_cell
    try:
        values = [_parse_and_validate_cell(cell) for cell in row[1:]]
        return any(value is not None for value in values)
    except (ValueError, TypeError):
        return False


def map_raw_grid_to_table_grid(
    raw_grid: List[List[str]],
    default_row_param: str = "row_param",
    default_col_param: str = "col_param",
) -> Tuple[TableGrid, List[str]]:
    """
    Преобразует сырую двумерную сетку ячеек (с многоуровневой шапкой)
    в валидированную модель TableGrid.
    """
    warnings: List[str] = []
    cleaned_grid = [
        [_cell_to_clean_str(c) for c in row]
        for row in raw_grid
        if any(_cell_to_clean_str(c) != "" for c in row)
    ]

    if len(cleaned_grid) < 2 or len(cleaned_grid[0]) < 2:
        raise ValueError("Сырая таблица должна содержать минимум 2 строки и 2 столбца.")

    data_start_idx = 1
    for r_idx in range(1, len(cleaned_grid)):
        first_cell = cleaned_grid[r_idx][0]
        if _is_numeric_row_label(first_cell) or (first_cell == "" and _row_has_numeric_data(cleaned_grid[r_idx])):
            data_start_idx = r_idx
            break

    header_rows = cleaned_grid[:data_start_idx]
    data_rows = cleaned_grid[data_start_idx:]

    if not data_rows:
        raise ValueError("Не найдены строки с нормативными данными после заголовка.")

    left_header_text = " ".join(h[0] for h in header_rows if h[0])
    top_header_text = " ".join(
        cell for h in header_rows for cell in h[1:] if cell
    ) or " ".join(header_rows[0][1:])

    row_param_name, row_condition = detect_axis_semantics(left_header_text, default_row_param)
    col_param_name, col_condition = detect_axis_semantics(top_header_text, default_col_param)

    max_width = max(len(r) for r in cleaned_grid)
    padded_headers = [r + [""] * (max_width - len(r)) for r in header_rows]
    padded_data = [r + [""] * (max_width - len(r)) for r in data_rows]

    effective_cols = max_width - 1
    while effective_cols > 0:
        header_empty = all(h[effective_cols] == "" for h in padded_headers)
        data_empty = all(d[effective_cols] == "" for d in padded_data)
        if header_empty and data_empty:
            effective_cols -= 1
        else:
            break

    if effective_cols < 1:
        raise ValueError("Пустой заголовок столбцов и отсутствие данных в столбцах.")

    filled_upper_rows: List[List[str]] = []
    for r in range(len(padded_headers) - 1):
        row_copy = list(padded_headers[r])
        last_val = ""
        for c in range(1, effective_cols + 1):
            if row_copy[c]:
                last_val = row_copy[c]
            elif last_val:
                row_copy[c] = last_val
        filled_upper_rows.append(row_copy)

    raw_leaf_headers = [padded_headers[-1][c] for c in range(1, effective_cols + 1)]
    upper_headers = [
        " / ".join(
            dict.fromkeys(filled_upper_rows[r][c] for r in range(len(filled_upper_rows)) if filled_upper_rows[r][c])
        )
        for c in range(1, effective_cols + 1)
    ]

    has_duplicate_leaves = len([x for x in raw_leaf_headers if x]) != len(set(x for x in raw_leaf_headers if x))
    has_distinct_groups = any(len(set(row[1:effective_cols + 1])) > 1 for row in filled_upper_rows)
    has_intervals = any(INTERVAL_PATTERN.match(h) or BILATERAL_RANGE_PATTERN.match(h) for h in raw_leaf_headers)
    cols_range: List[float | str] = []
    has_non_numeric_cols = False

    for idx in range(effective_cols):
        leaf = raw_leaf_headers[idx]
        upper = upper_headers[idx]

        if not leaf and not upper:
            label = f"col_{idx + 1}"
            cols_range.append(label)
            has_non_numeric_cols = True
            warnings.append(f"Пустой заголовок у непустого столбца {idx + 1}; назначена метка '{label}'.")
        elif not leaf and upper:
            parsed = _parse_axis_label(upper, warnings, "столбцы")
            cols_range.append(parsed)
            if isinstance(parsed, str):
                has_non_numeric_cols = True
        elif (has_duplicate_leaves or has_distinct_groups) and upper and upper != leaf:
            combined = f"{upper} | {leaf}"
            cols_range.append(combined)
            has_non_numeric_cols = True
        else:
            parsed = leaf if has_intervals else _parse_axis_label(leaf, warnings, "столбцы")
            cols_range.append(parsed)
            if isinstance(parsed, str):
                has_non_numeric_cols = True

    if has_non_numeric_cols:
        warnings.append("Часть заголовков столбцов представлена строковыми или составными метками.")

    rows_range: List[float | str] = []
    values_matrix: List[List[str]] = []

    for r_idx, row in enumerate(padded_data, start=1):
        row_label = row[0]
        row_cells = row[1 : 1 + effective_cols]

        if not row_label:
            if not any(cell != "" for cell in row_cells):
                continue
            fallback_label = f"row_{r_idx}"
            rows_range.append(fallback_label)
            warnings.append(
                f"Строка данных {r_idx}: неизвестная метка оси; сохранена с меткой '{fallback_label}'."
            )
        else:
            rows_range.append(_parse_axis_label(row_label, warnings, "строки"))

        values_matrix.append(row_cells)

    if not rows_range:
        raise ValueError("После фильтрации пустых строк не осталось ни одной строки данных.")

    table_grid = TableGrid(
        row_param_name=row_param_name,
        row_condition=row_condition,
        col_param_name=col_param_name,
        col_condition=col_condition,
        rows_range=rows_range,
        cols_range=cols_range,
        values_matrix=values_matrix,
    )
    return table_grid, warnings
