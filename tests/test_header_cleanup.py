import numpy as np

from normdoc2json.ocr_tables import clean_header_crop, recognize_cells
from normdoc2json.ocr_engine import OCRWord


def test_cleanup_preserves_detached_punctuation_and_removes_remote_specks():
    image = np.full((100, 240), 255, dtype=np.uint8)
    image[30:65, 40:50] = 0
    image[30:65, 70:80] = 0
    image[62:68, 85:89] = 0  # comma near baseline
    image[5:8, 150:153] = 0
    result = clean_header_crop(image)
    assert np.all(result[62:68, 85:89] == 0)
    assert np.all(result[5:8, 150:153] == 255)
    assert np.all(result[30:65, 40:50] == 0)


def test_disagreeing_header_reads_require_review_and_keep_coordinates():
    image = np.full((100, 240), 255, dtype=np.uint8)
    image[30:65, 40:50] = 0
    image[30:65, 70:80] = 0

    class Engine:
        calls = 0

        def recognize(self, image, psm=6):
            self.calls += 1
            return [OCRWord('D' if self.calls == 1 else 'O',
                            (20, 20, 30, 50), .95, (1, 1, 1))]

    words = recognize_cells([((0, 0, 240, 100), [(10, 10, 230, 90)])], image, Engine())
    assert words
    assert words[0].confidence < .8
    x0, y0, x1, y1 = words[0].bbox
    assert 10 <= x0 < x1 <= 230
    assert 10 <= y0 < y1 <= 90
