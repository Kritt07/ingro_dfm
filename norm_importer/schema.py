from __future__ import annotations

import math
import re
from enum import Enum
from typing import Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

RANGE_PATTERN = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[-–—]\s*([+-]?\d+(?:\.\d+)?)\s*$")


def _ensure_finite_float(value: float, context: str = "числовое значение") -> float:
    if not math.isfinite(value):
        raise ValueError(f"Недопустимое нечисловое или бесконечное {context}: {value}")
    return value


class SourceFormat(str, Enum):
    PDF_VECTOR = "pdf_vector"
    PDF_SCANNED = "pdf_scanned"
    PDF_HYBRID = "pdf_hybrid"
    DOCX = "docx"
    DOC = "doc"
    RTF = "rtf"
    ODT = "odt"
    TXT = "txt"
    XLSX = "xlsx"
    XLS = "xls"
    CSV = "csv"
    ODS = "ods"
    IMAGE = "image"
    TIFF = "tiff"


class AxisCondition(str, Enum):
    UP_TO = "up_to"
    OVER = "over"
    EXACT = "exact"


class ModifierOperation(str, Enum):
    MULTIPLY = "multiply"
    ADD = "add"
    SUBTRACT = "subtract"
    OVERRIDE = "override"


class SourceMetadata(BaseModel):
    source_file: str = Field(..., description="Имя или путь к исходному файлу")
    source_format: SourceFormat = Field(..., description="Определённый формат документа")
    page_number: Optional[int] = Field(default=None, ge=1, description="Номер страницы источника")
    extraction_method: str = Field(..., description="Метод извлечения")
    ocr_confidence_avg: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Средняя уверенность OCR")
    requires_manual_review: bool = Field(default=False, description="Флаг необходимости ручной проверки")
    warnings: List[str] = Field(default_factory=list, description="Диагностические предупреждения")


class ApplicabilityConditions(BaseModel):
    operation_type: str = Field(..., description="Вид обработки")
    production_type: Optional[str] = Field(default=None, description="Тип производства")
    material_group: Optional[str] = Field(default=None, description="Группа обрабатываемого материала и твёрдость")
    equipment_filter: Optional[str] = Field(default=None, description="Тип или параметры оборудования")
    tool_material: Optional[str] = Field(default=None, description="Материал режущей части инструмента")
    extra_params: dict[str, Any] = Field(default_factory=dict, description="Дополнительные условия")


CellValue = Union[float, List[float], None]


def _parse_and_validate_cell(cell: Any) -> CellValue:
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise ValueError(f"Булево значение недопустимо в ячейке таблицы: {cell}")
    if isinstance(cell, (int, float)):
        return _ensure_finite_float(float(cell), "значение ячейки")
    if isinstance(cell, list):
        if len(cell) != 2:
            raise ValueError(f"Диапазон в ячейке должен содержать ровно 2 границы, получено {len(cell)}: {cell}")
        if isinstance(cell[0], bool) or isinstance(cell[1], bool):
            raise ValueError(f"Булево значение недопустимо в границах диапазона: {cell}")
        low = _ensure_finite_float(float(cell[0]), "нижняя граница диапазона")
        high = _ensure_finite_float(float(cell[1]), "верхняя граница диапазона")
        if low > high:
            raise ValueError(f"Обратный порядок границ диапазона: {low} > {high}")
        return [low, high]
    if isinstance(cell, str):
        from norm_importer.notes_parser import clean_ocr_numeric_token
        cleaned = clean_ocr_numeric_token(cell)
        if cleaned in {"", "-", "–", "—", "null", "None"}:
            return None

        range_match = RANGE_PATTERN.match(cleaned)
        if range_match:
            low = _ensure_finite_float(float(range_match.group(1)), "нижняя граница диапазона")
            high = _ensure_finite_float(float(range_match.group(2)), "верхняя граница диапазона")
            if low > high:
                raise ValueError(f"Обратный порядок границ диапазона: {low} > {high}")
            return [low, high]

        return _ensure_finite_float(float(cleaned), "значение ячейки")
    raise ValueError(f"Неподдерживаемый тип значения ячейки: {type(cell)}")


class TableGrid(BaseModel):
    row_param_name: str = Field(..., description="Имя параметра по строкам")
    row_condition: AxisCondition = Field(default=AxisCondition.UP_TO)
    col_param_name: Optional[str] = Field(default=None, description="Имя параметра по столбцам")
    col_condition: Optional[AxisCondition] = Field(default=AxisCondition.UP_TO)
    rows_range: List[Union[float, str]] = Field(..., min_length=1, description="Границы интервалов строк")
    cols_range: List[Union[float, str]] = Field(default_factory=list, description="Границы интервалов столбцов")
    values_matrix: List[List[CellValue]] = Field(..., min_length=1, description="Матрица нормативных значений")

    @field_validator("rows_range", "cols_range")
    @classmethod
    def validate_axis_ranges(cls, items: List[Union[float, str]]) -> List[Union[float, str]]:
        validated: List[Union[float, str]] = []
        for item in items:
            if isinstance(item, float):
                validated.append(_ensure_finite_float(item, "граница оси"))
            else:
                validated.append(item)
        return validated

    @field_validator("values_matrix", mode="before")
    @classmethod
    def normalize_matrix_cells(cls, raw_matrix: Any) -> Any:
        if not isinstance(raw_matrix, list):
            return raw_matrix
        normalized: list[list[Any]] = []
        for row in raw_matrix:
            if not isinstance(row, list):
                normalized.append(row)
                continue
            normalized.append([_parse_and_validate_cell(cell) for cell in row])
        return normalized

    @model_validator(mode="after")
    def validate_dimensions(self) -> TableGrid:
        expected_rows = len(self.rows_range)
        actual_rows = len(self.values_matrix)
        if actual_rows != expected_rows:
            raise ValueError(
                f"Несовпадение числа строк: длина rows_range={expected_rows}, строк в values_matrix={actual_rows}"
            )

        expected_cols = len(self.cols_range) if self.cols_range else 1
        for idx, row in enumerate(self.values_matrix):
            if len(row) != expected_cols:
                raise ValueError(
                    f"Несовпадение числа столбцов в строке {idx}: ожидалось {expected_cols}, получено {len(row)}"
                )
        return self


class NoteCoefficientRule(BaseModel):
    note_id: str = Field(..., description="Идентификатор правила")
    raw_text: str = Field(..., description="Исходный текст примечания из карты")
    condition_key: str = Field(..., description="Ключ условия в паспорте детали")
    condition_value: Union[bool, float, int, str] = Field(..., description="Значение условия срабатывания")
    modifier_operation: ModifierOperation = Field(default=ModifierOperation.MULTIPLY)
    target_variable: str = Field(default="Ttbl", description="Целевая переменная формулы")
    factor: float = Field(..., description="Числовой коэффициент или поправка")

    @field_validator("factor")
    @classmethod
    def validate_factor(cls, val: float) -> float:
        return _ensure_finite_float(val, "коэффициент примечания")


class NormCard(BaseModel):
    card_id: str = Field(..., description="Уникальный код нормировочной карты")
    card_title: str = Field(..., description="Заголовок карты")
    applicability_conditions: ApplicabilityConditions
    calculation_formula: str = Field(..., description="Расчетная формула карты")
    result_unit: Literal["min", "hour", "pct"] = Field(default="min")
    table_grid: TableGrid
    notes_and_coefficients: List[NoteCoefficientRule] = Field(default_factory=list)


class NormDocDocument(BaseModel):
    schema_version: str = Field(default="1.0")
    source_metadata: SourceMetadata
    cards: List[NormCard] = Field(..., min_length=1)

    def to_json_file(self, output_path: str) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))
