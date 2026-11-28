from __future__ import annotations

import re
from typing import List, Optional, Tuple

from norm_importer.schema import AxisCondition, TableGrid

AXIS_KEYWORDS: List[Tuple[str, str]] = [
    (r"диаметр|\bD\b|[Ø∅⌀]", "diameter_d_mm"),
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
    r"^\s*(?:(?:до|св\.?|свыше|не\s+более|≤|<=|>)\s*)?([+-]?\d+(?:[.,]\d+)?)\s*$",
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
    if _is_interval_label(cleaned):
        warnings.append(
            f"Интервал на оси ({axis_kind}) '{cleaned}' сохранён как строковая метка без потери верхней границы."
        )
        return cleaned

    # The schema can express <= and >, but cannot express < or >=. Keep
    # these conditions in the label rather than changing their inclusivity.
    if re.search(r"(?<!<)<(?![=])|≥|>=|(?<![<>])=", cleaned.replace("<=", "≤")):
        warnings.append(f"Условие оси ({axis_kind}) '{cleaned}' сохранено без изменения границы.")
        return cleaned

    single_match = SINGLE_NUMBER_PATTERN.match(cleaned)
    if single_match:
        return float(single_match.group(1).replace(",", "."))

    prefixed_match = re.fullmatch(
        r"(?:[A-Za-zА-Яа-яЁё]+\s*)?(?:до|св\.?|свыше|не\s+более|≤|<=|>)\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:мм|см|м|кг)?",
        cleaned,
        flags=re.IGNORECASE,
    )
    if prefixed_match:
        return float(prefixed_match.group(1).replace(",", "."))

    return cleaned


def _is_interval_label(label: str) -> bool:
    """Never reduce a two-bound condition to its final numeric suffix."""
    return bool(INTERVAL_PATTERN.fullmatch(label) or BILATERAL_RANGE_PATTERN.fullmatch(label)
                or (len(re.findall(r"[+-]?\d+(?:[.,]\d+)?", label)) > 1
                    and re.search(r"[<>≤≥]|\bдо\b|\bот\b|\bсв\.?(?=\s*\d)|\bсвыше\b", label, re.I)))


def _explicit_conditions(labels):
    conditions = set()
    for label in labels:
        if re.search(r"\bдо\b|не\s+(?:более|свыше)|≤|<=", label, re.I):
            conditions.add(AxisCondition.UP_TO)
        positive = re.sub(r"не\s+(?:более|свыше)", "", label, flags=re.I)
        if re.search(r"\bсв\.?(?=\s*\d|\s*$)|\bсвыше\b|>(?!=)", positive, re.I):
            conditions.add(AxisCondition.OVER)
    return conditions


def _expand_merged_cells(grid, merged_ranges):
    """Apply explicit spans before locating the data rows (1-based inclusive)."""
    width = max((len(row) for row in grid), default=0)
    expanded = [list(row) + [""] * (width - len(row)) for row in grid]
    for r0, c0, r1, c1 in merged_ranges:
        if not (1 <= r0 <= r1 <= len(expanded) and 1 <= c0 <= c1 <= width):
            raise ValueError(f"Некорректное объединение ячеек: {(r0, c0, r1, c1)}")
        values = {expanded[r][c] for r in range(r0 - 1, r1)
                  for c in range(c0 - 1, c1) if expanded[r][c]}
        if len(values) > 1:
            raise ValueError(f"Противоречивый текст в объединении: {(r0, c0, r1, c1)}")
        value = next(iter(values), "")
        for r in range(r0 - 1, r1):
            for c in range(c0 - 1, c1):
                expanded[r][c] = value
    return expanded

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
    *,
    merged_ranges: Optional[List[Tuple[int, int, int, int]]] = None,
) -> Tuple[TableGrid, List[str]]:
    """
    Преобразует сырую двумерную сетку ячеек (с многоуровневой шапкой)
    в валидированную модель TableGrid.
    """
    warnings: List[str] = []
    cleaned_grid = [
        [_cell_to_clean_str(c) for c in row]
        for row in raw_grid
    ]
    if merged_ranges is not None:
        cleaned_grid = _expand_merged_cells(cleaned_grid, merged_ranges)
    cleaned_grid = [row for row in cleaned_grid if any(row)]

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
    for text, default, axis in (
        (left_header_text, default_row_param, "строки"),
        (top_header_text, default_col_param, "столбцы"),
    ):
        detected = {name for pattern, name in AXIS_KEYWORDS if re.search(pattern, text, re.I)}
        if not detected:
            warnings.append(f"Не определён параметр оси ({axis}) по шапке {text!r}; "
                            f"использовано резервное имя '{default}'. Требуется ручная проверка.")
        elif len(detected) > 1:
            warnings.append(f"Неоднозначный параметр оси ({axis}): {sorted(detected)}; "
                            "требуется ручная проверка.")
            if axis == "строки":
                row_param_name = default
            else:
                col_param_name = default

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
            elif last_val and merged_ranges is None:
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
    has_intervals = any(_is_interval_label(h) for h in raw_leaf_headers)
    explicit_conditions = _explicit_conditions(raw_leaf_headers)
    mixed_conditions = len(explicit_conditions) > 1
    if mixed_conditions:
        warnings.append("Разные условия столбцов сохранены в исходных метках; единое col_condition их не описывает.")
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
            parsed = leaf if has_intervals or mixed_conditions else _parse_axis_label(leaf, warnings, "столбцы")
            cols_range.append(parsed)
            if isinstance(parsed, str):
                has_non_numeric_cols = True

    if has_non_numeric_cols:
        warnings.append("Часть заголовков столбцов представлена строковыми или составными метками.")

    rows_range: List[float | str] = []
    values_matrix: List[List[str]] = []
    row_conditions = _explicit_conditions([left_header_text, *(row[0] for row in padded_data)])
    mixed_row_conditions = len(row_conditions) > 1
    if mixed_row_conditions:
        warnings.append("Разные условия строк сохранены в исходных метках; единое row_condition их не описывает.")
    elif row_conditions:
        row_condition = next(iter(row_conditions))

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
            rows_range.append(row_label if mixed_row_conditions else _parse_axis_label(row_label, warnings, "строки"))

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
