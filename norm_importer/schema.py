from __future__ import annotations

from enum import Enum
from typing import Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


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
    UP_TO = "up_to"        # «до» (берём первую строку/столбец, где val <= max)
    OVER = "over"          # «свыше»
    EXACT = "exact"        # точное совпадение


class ModifierOperation(str, Enum):
    MULTIPLY = "multiply"
    ADD = "add"
    SUBTRACT = "subtract"
    OVERRIDE = "override"


class SourceMetadata(BaseModel):
    source_file: str = Field(..., description="Имя или путь к исходному файлу")
    source_format: SourceFormat = Field(..., description="Определённый формат документа")
    page_number: Optional[int] = Field(default=None, ge=1, description="Номер страницы источника")
    extraction_method: str = Field(..., description="Метод извлечения (pdfplumber, docx, openpyxl, ocr_paddle_v2 и др.)")
    ocr_confidence_avg: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Средняя уверенность OCR")
    requires_manual_review: bool = Field(default=False, description="Флаг необходимости ручной проверки")
    warnings: List[str] = Field(default_factory=list, description="Диагностические предупреждения")


class ApplicabilityConditions(BaseModel):
    operation_type: str = Field(..., description="Вид обработки (Сверление, Точение, Фрезерование и др.)")
    production_type: Optional[str] = Field(default=None, description="Тип производства")
    material_group: Optional[str] = Field(default=None, description="Группа обрабатываемого материала и твёрдость")
    equipment_filter: Optional[str] = Field(default=None, description="Тип или параметры оборудования")
    tool_material: Optional[str] = Field(default=None, description="Материал режущей части инструмента")
    extra_params: dict[str, Any] = Field(default_factory=dict, description="Дополнительные условия (Ra, квалитет, L/D)")


CellValue = Union[float, List[float], None]


class TableGrid(BaseModel):
    row_param_name: str = Field(..., description="Имя параметра по строкам (например, diameter_d_mm)")
    row_condition: AxisCondition = Field(default=AxisCondition.UP_TO)
    col_param_name: Optional[str] = Field(default=None, description="Имя параметра по столбцам (null для 1D-таблиц)")
    col_condition: Optional[AxisCondition] = Field(default=AxisCondition.UP_TO)
    rows_range: List[Union[float, str]] = Field(..., min_length=1, description="Границы интервалов строк")
    cols_range: List[Union[float, str]] = Field(default_factory=list, description="Границы интервалов столбцов")
    values_matrix: List[List[CellValue]] = Field(..., min_length=1, description="Матрица нормативных значений")

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
            norm_row: list[Any] = []
            for cell in row:
                if cell is None:
                    norm_row.append(None)
                elif isinstance(cell, (int, float)):
                    norm_row.append(float(cell))
                elif isinstance(cell, str):
                    cleaned = cell.strip().replace(",", ".")
                    if cleaned in {"", "-", "–", "—", "null", "None"}:
                        norm_row.append(None)
                    elif "-" in cleaned or "–" in cleaned:
                        sep = "–" if "–" in cleaned else "-"
                        parts = [p.strip() for p in cleaned.split(sep) if p.strip()]
                        if len(parts) == 2:
                            norm_row.append([float(parts[0]), float(parts[1])])
                        else:
                            norm_row.append(float(cleaned))
                    else:
                        norm_row.append(float(cleaned))
                else:
                    norm_row.append(cell)
            normalized.append(norm_row)
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
    note_id: str = Field(..., description="Идентификатор правила (NOTE_01)")
    raw_text: str = Field(..., description="Исходный текст примечания из карты")
    condition_key: str = Field(..., description="Ключ условия в паспорте детали (is_blind_hole и др.)")
    condition_value: Union[bool, float, int, str] = Field(..., description="Значение условия срабатывания")
    modifier_operation: ModifierOperation = Field(default=ModifierOperation.MULTIPLY)
    target_variable: str = Field(default="Ttbl", description="Целевая переменная формулы")
    factor: float = Field(..., description="Числовой коэффициент или поправка")


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
