"""Предобработка графики для OCR; координаты результата — пиксели."""
from dataclasses import dataclass, field
from collections.abc import Iterator
from pathlib import Path
import math

import cv2
import numpy as np
from .image_io import ImagePage, iter_image_pages


@dataclass
class PreparedPage:
    source_file: str
    page_number: int
    image: np.ndarray | None
    rotation_degrees: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)
    warnings: list[str] = field(default_factory=list)

    @property
    def requires_manual_review(self) -> bool:
        return bool(self.warnings)


def _deskew(gray: np.ndarray) -> tuple[np.ndarray, float, list[str]]:
    edges = cv2.Canny(gray, 50, 150)
    length = max(20, min(gray.shape) // 8)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1800, threshold=30,
                            minLineLength=length, maxLineGap=10)
    angles = []
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = math.degrees(math.atan2(float(y2-y1), float(x2-x1)))
            # Горизонтальные и вертикальные линии дают общую оценку наклона.
            angle = (angle + 45) % 90 - 45
            if abs(angle) <= 20:
                angles.append(angle)
    if len(angles) < 3:
        return gray, 0.0, ['Недостаточно линий для надёжного определения наклона']
    angle = float(np.median(angles))
    if np.median(np.abs(np.asarray(angles)-angle)) > 2:
        return gray, 0.0, ['Неоднозначный наклон: возможна перспектива или сложная сетка']
    if abs(angle) > 15.5:
        return gray, 0.0, ['Наклон выходит за поддерживаемые пределы ±15°']
    if abs(angle) < 0.15:
        return gray, 0.0, []
    h, w = gray.shape
    matrix = cv2.getRotationMatrix2D((w/2, h/2), angle, 1)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    nw, nh = math.ceil(w*cosine+h*sine), math.ceil(h*cosine+w*sine)
    matrix[0, 2] += (nw-w)/2
    matrix[1, 2] += (nh-h)/2
    return cv2.warpAffine(gray, matrix, (nw, nh), borderValue=255), angle, []


def preprocess_page(page: ImagePage, *, target_dpi: int = 300,
                    max_pixels: int = 40_000_000, deskew: bool = True) -> PreparedPage:
    """Подготовить страницу. Неизвестный DPI не угадывается.

    scale относится к EXIF-ориентированному входу; rotation — угол OpenCV.
    Размер после поворота расширяется, поэтому координаты входа и выхода различны.
    """
    if target_dpi < 300 or max_pixels < 1:
        raise ValueError('target_dpi должен быть >= 300, max_pixels > 0')
    warnings = list(page.warnings)
    result = PreparedPage(page.source_file, page.page_number, None, warnings=warnings)
    if page.image is None:
        if not warnings:
            warnings.append('Изображение страницы отсутствует')
        return result
    image = page.image
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('Ожидается RGB-массив uint8')
    h, w = image.shape[:2]
    if min(h, w) < 3:
        warnings.append('Изображение слишком мало для обработки')
        return result
    sx, sy = (1.0, 1.0)
    if page.dpi:
        if not all(math.isfinite(d) and d > 0 for d in page.dpi):
            raise ValueError('DPI должен быть положительным и конечным')
        sx, sy = (max(1.0, target_dpi/d) for d in page.dpi)
    else:
        warnings.append('DPI неизвестен: исходный размер сохранён')
    nw, nh = round(w*sx), round(h*sy)
    # Запас под расширение холста при повороте до 15 градусов.
    bound = math.ceil(nw + nh * 0.268) * math.ceil(nh + nw * 0.268) if deskew else nw*nh
    if bound > max_pixels:
        warnings.append('Превышен лимит пикселей с учётом поворота; страница пропущена')
        return result
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    if (nw, nh) != (w, h):
        gray = cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_CUBIC)
    result.scale = (nw/w, nh/h)
    if deskew:
        gray, result.rotation_degrees, notes = _deskew(gray)
        warnings.extend(notes)
    # Мягкая фильтрация сохраняет границы и мелкие знаки; морфологическое
    # раскрытие не применяется, поскольку оно может уничтожать запятые.
    clean = cv2.bilateralFilter(gray, 5, 20, 20)
    block = min(51, min(clean.shape) // 2 * 2 - 1)
    result.image = cv2.adaptiveThreshold(clean, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, max(3, block), 15)
    if not np.any(result.image == 0):
        warnings.append('После обработки страница не содержит тёмных пикселей')
    return result


def iter_preprocessed_images(path: str | Path, *, target_dpi: int = 300,
                             max_pixels: int = 40_000_000) -> Iterator[PreparedPage]:
    """Поток страниц для OCR; сбой страницы не прерывает последующие."""
    if target_dpi < 300 or max_pixels < 1:
        raise ValueError('target_dpi должен быть >= 300, max_pixels > 0')
    for page in iter_image_pages(path):
        try:
            yield preprocess_page(page, target_dpi=target_dpi, max_pixels=max_pixels)
        except (cv2.error, ValueError, OSError) as exc:
            yield PreparedPage(page.source_file, page.page_number, None,
                               warnings=page.warnings + [f'Ошибка предобработки: {exc}'])

