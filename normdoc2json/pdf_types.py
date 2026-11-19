"""Промежуточный контракт извлечения PDF, без семантической нормализации."""
from dataclasses import dataclass, field

BBox = tuple[float, float, float, float]

@dataclass
class TextBlock:
    """Текст и прямоугольник в пунктах PDF от верхнего левого угла."""
    bbox: BBox
    text: str

@dataclass
class PDFTable:
    """Сетка строк; индексы объединений от единицы, границы включительные."""
    page_number: int
    bbox: BBox
    values: list[list[str | None]]
    cell_bboxes: list[list[BBox | None]]
    merged_ranges: list[tuple[int, int, int, int]] = field(default_factory=list)
    method: str = 'lines'

@dataclass
class PDFPage:
    """Страница с таблицами и окружающим текстом; номер от единицы."""
    page_number: int
    kind: str
    blocks: list[TextBlock] = field(default_factory=list)
    tables: list[PDFTable] = field(default_factory=list)

@dataclass
class PDFExtraction:
    """Результат для семантического парсера и source_metadata."""
    source_file: str
    source_format: str
    pages: list[PDFPage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def requires_manual_review(self) -> bool:
        """Нужна ли проверка извлечения человеком."""
        return bool(self.warnings)
