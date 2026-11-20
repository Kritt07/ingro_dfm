import numpy as np
import pytest
from PIL import Image
from normdoc2json.image_io import iter_image_pages
from normdoc2json import InspectionError


@pytest.mark.parametrize('extension', ['jpg', 'jpeg', 'png', 'tif', 'tiff', 'bmp', 'webp'])
def test_formats(tmp_path, extension):
    path = tmp_path / ('карта.' + extension)
    Image.new('RGB', (40, 30), 'white').save(path)
    pages = list(iter_image_pages(path))
    assert len(pages) == 1
    assert pages[0].image.shape == (30, 40, 3)
    assert pages[0].page_number == 1


def test_tiff_pages_and_dpi(tmp_path):
    path = tmp_path / 'pages.tiff'
    Image.new('RGB', (40, 30), 'white').save(
        path, save_all=True, append_images=[Image.new('RGB', (20, 10), 'black')], dpi=(150, 150))
    pages = list(iter_image_pages(path))
    assert [p.page_number for p in pages] == [1, 2]
    assert pages[0].dpi == (150, 150)
    assert np.all(pages[1].image == 0)


def test_transparency_and_orientation(tmp_path):
    path = tmp_path / 'transparent.png'
    Image.new('RGBA', (20, 10), (0, 0, 0, 0)).save(path)
    assert np.all(next(iter_image_pages(path)).image == 255)
    path = tmp_path / 'rotated.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (20, 10), 'white').save(path, exif=exif)
    assert next(iter_image_pages(path)).image.shape == (20, 10, 3)


def test_bad_file(tmp_path):
    path = tmp_path / 'bad.png'
    path.write_bytes(b'broken')
    with pytest.raises(InspectionError):
        list(iter_image_pages(path))
