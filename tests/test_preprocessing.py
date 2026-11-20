import cv2
import numpy as np
import pytest
from PIL import Image
from normdoc2json.image_io import ImagePage
from normdoc2json.preprocessing import preprocess_page, iter_preprocessed_images


def table():
    image = np.full((600, 800, 3), 255, np.uint8)
    for y in range(100, 501, 80):
        cv2.line(image, (100, y), (700, y), (0, 0, 0), 2)
    for x in range(100, 701, 100):
        cv2.line(image, (x, 100), (x, 500), (0, 0, 0), 2)
    cv2.putText(image, '0,28 - 1.5', (220, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    return image


@pytest.mark.parametrize('angle', [-15, -7, 0, 7, 15])
def test_deskew(angle):
    image = table()
    matrix = cv2.getRotationMatrix2D((400, 300), angle, 1)
    rotated = cv2.warpAffine(image, matrix, (800, 600), borderValue=(255, 255, 255))
    result = preprocess_page(ImagePage('test', 1, rotated, (300, 300)))
    assert abs(result.rotation_degrees + angle) < 0.6
    assert set(np.unique(result.image)) == {0, 255}
    assert not result.requires_manual_review


def test_preserve_marks_and_grid():
    source = table()
    result = preprocess_page(ImagePage('test', 1, source, (300, 300)))
    mask = source[:, :, 0] == 0
    assert np.mean(result.image[mask] == 0) > 0.98
    # Запятая и минус входят в проверяемые чёрные пиксели текста.
    assert np.mean(result.image[140:160, 220:420] == 0) > 0


def test_dpi_and_limits():
    page = ImagePage('test', 1, table(), (150, 150))
    result = preprocess_page(page)
    assert result.scale == (2, 2)
    assert result.image.shape == (1200, 1600)
    assert preprocess_page(page, max_pixels=100).image is None
    page.dpi = None
    assert preprocess_page(page).requires_manual_review


def test_blank_and_invalid():
    result = preprocess_page(ImagePage('test', 1, np.full((50, 50, 3), 255, np.uint8)))
    assert result.requires_manual_review
    with pytest.raises(ValueError):
        preprocess_page(ImagePage('test', 1, table()), target_dpi=100)


def test_continue_after_page_error(tmp_path, monkeypatch):
    import normdoc2json.preprocessing as module
    path = tmp_path / 'pages.tiff'
    image = Image.fromarray(table())
    image.save(path, save_all=True, append_images=[image], dpi=(300, 300))
    original = module.preprocess_page
    def failing(page, **kwargs):
        if page.page_number == 1:
            raise ValueError('test failure')
        return original(page, **kwargs)
    monkeypatch.setattr(module, 'preprocess_page', failing)
    results = list(iter_preprocessed_images(path))
    assert results[0].image is None
    assert results[0].requires_manual_review
    assert results[1].image is not None
