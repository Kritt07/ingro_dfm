"""Постраничная загрузка растров без зависимости от OCR."""
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterator
import math

import numpy as np
from PIL import Image, ImageOps

from .format_router import InspectionError


@dataclass
class ImagePage:
    source_file: str
    page_number: int
    image: np.ndarray | None
    dpi: tuple[float, float] | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def requires_manual_review(self) -> bool:
        return bool(self.warnings)


def iter_image_pages(path: str | Path) -> Iterator[ImagePage]:
    """Выдавать RGB uint8 по одной странице; номера от 1, EXIF учтён.

    Ошибка открытия — InspectionError; ошибка кадра — запись без изображения.
    Файл закрывается при исчерпании или закрытии генератора.
    """
    path = Path(path)
    try:
        source = Image.open(path)
    except (OSError, ValueError) as exc:
        raise InspectionError(f'Не удалось открыть изображение {path}: {exc}') from exc
    with source:
        if source.format not in {'JPEG', 'PNG', 'TIFF', 'BMP', 'WEBP'}:
            raise InspectionError(f'Неподдерживаемый формат изображения: {source.format}')
        for index in range(getattr(source, 'n_frames', 1)):
            try:
                source.seek(index)
                raw_dpi = source.info.get('dpi')
                dpi: tuple[float, float] | None = None
                if raw_dpi and len(raw_dpi) == 2:
                    values = (float(raw_dpi[0]), float(raw_dpi[1]))
                    if all(math.isfinite(x) and x > 0 for x in values):
                        dpi = values
                # EXIF поворот на 90 градусов меняет местами оси DPI.
                orientation = source.getexif().get(274, 1)
                frame = ImageOps.exif_transpose(source)
                if dpi and orientation in {5, 6, 7, 8}:
                    dpi = (dpi[1], dpi[0])
                rgba = frame.convert('RGBA')
                background = Image.new('RGBA', rgba.size, 'white')
                background.alpha_composite(rgba)
                pixels = np.array(background.convert('RGB'))
                yield ImagePage(str(path), index + 1, pixels, dpi)
            except (OSError, ValueError, EOFError) as exc:
                yield ImagePage(str(path), index + 1, None,
                                warnings=[f'Ошибка страницы {index + 1}: {exc}'])
