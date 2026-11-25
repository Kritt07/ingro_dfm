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


def detect_axis_semantics(header_text: str, default_name: str) -> Tuple[str, AxisCondition]:
    """Определяет семантическое имя параметра и условие ('до' / 'свыше') по тексту шапки."""
    clean = " ".join(header_text.strip().split())
    lower = clean.lower()

    condition = AxisCondition.UP_TO
    if re.search(r"\bсв(?:ыше|\.)\b|более|>", lower):
        condition = AxisCondition.OVER
    elif re.search(r"\bдо\b|не\s+более|≤|<=", lower):
        condition = AxisCondition.UP_TO

    param_name = default_name
    for pattern, canonical_name in AXIS_KEYWORDS:
        if re.search(pattern, clean, flags=re.IGNORECASE):
            param_name = canonical_name
            break

    return param_name, condition


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
        [" ".join(str(c or "").strip().split()) for c in row]
        for row in raw_grid
        if any(str(c or "").strip() for c in row)
    ]

    if len(cleaned_grid) < 2 or len(cleaned_grid[0]) < 2:
        raise ValueError("Сырая таблица должна содержать минимум 2 строки и 2 столбца.")

    data_start_idx = 1
    for r_idx in range(1, len(cleaned_grid)):
        if _is_numeric_row_label(cleaned_grid[r_idx][0]):
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

    leaf_col_headers = header_rows[-1][1:]
    # Отбрасываем пустые хвостовые столбцы
    while leaf_col_headers and not leaf_col_headers[-1]:
        leaf_col_headers.pop()

    if not leaf_col_headers:
        raise ValueError("Пустой заголовок столбцов в нижней строке шапки.")

    col_nums = extract_numeric_tokens(leaf_col_headers)
    if len(header_rows) > 1 and any(
        len(set(c for c in h[1:] if c)) > 1 for h in header_rows[:-1]
    ):
        cols_range = [" | ".join(dict.fromkeys(h[c] for h in header_rows if c < len(h) and h[c]))
                      or f"col_{c}" for c in range(1, len(leaf_col_headers)+1)]
        warnings.append("Многоуровневая ось сохранена строковыми условиями; требуется проверка.")
    elif any(len(re.findall(r"[+-]?\d+(?:[.,]\d+)?", cell)) > 1 for cell in leaf_col_headers):
        cols_range = leaf_col_headers
        warnings.append("Интервалы столбцов сохранены строковыми условиями; требуется проверка.")
    elif len(col_nums) == len(leaf_col_headers):
        cols_range: List[float | str] = col_nums
    else:
        cols_range = [c if c else f"col_{i+1}" for i, c in enumerate(leaf_col_headers)]
        warnings.append("Часть заголовков столбцов не является числами; сохранены строковые метки.")

    rows_range: List[float | str] = []
    values_matrix: List[List[str]] = []

    for row in data_rows:
        row_label = row[0]
        if not row_label:
            continue
        row_nums = extract_numeric_tokens([row_label])
        rows_range.append(row_nums[0] if row_nums else row_label)

        row_cells = row[1 : 1 + len(cols_range)]
        if len(row_cells) < len(cols_range):
            row_cells.extend([""] * (len(cols_range) - len(row_cells)))
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
