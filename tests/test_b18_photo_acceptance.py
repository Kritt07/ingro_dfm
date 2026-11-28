"""Real-photo acceptance: known B18 failures remain visible, not xfailed.

Numeric accuracy thresholds in the specification do not measure axis correctness.
Run: python -m pytest -q tests/test_b18_photo_acceptance.py
"""
import json
from pathlib import Path
import pytest
from normdoc2json.ocr import iter_ocr_pages, ocr_document
from normdoc2json.ocr_engine import TesseractEngine

FOLDER = Path(__file__).parent / "fixtures" / "phone_photos"
EXPECTED = json.loads((FOLDER / "expected.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=sorted(FOLDER.glob("*.jpg")), ids=lambda p: p.stem)
def photo(request):
    try:
        engine = TesseractEngine()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    return request.param, list(iter_ocr_pages(request.param, engine=engine))


def test_numeric_accuracy_specification(photo):
    path, pages = photo
    ref = EXPECTED[path.stem.split("_")[0]]
    tables = [t for p in pages for t in p.tables]
    assert len(tables) == 1
    raw = tables[0].values
    correct = total = 0
    for r, row in enumerate(ref["values"]):
        if r < ref["header_rows"]:
            continue
        for c, value in enumerate(row[1:], 1):
            if value == "-":
                continue
            total += 1
            try:
                correct += float(str(raw[r][c]).replace(",", ".")) == float(value.replace(",", "."))
            except (ValueError, TypeError, IndexError):
                pass
    assert correct / total >= .85, f"{correct}/{total}: below specification 85%"


def test_final_axes_match_original(photo, monkeypatch):
    path, pages = photo
    monkeypatch.setattr("normdoc2json.ocr.iter_ocr_pages", lambda *a, **k: iter(pages))
    doc = ocr_document(path)
    assert len(doc.cards) == 1
    grid = doc.cards[0].table_grid
    card = path.stem.split("_")[0]
    ref = EXPECTED[card]
    expected_rows = [float(row[0]) for row in ref["values"][ref["header_rows"]:]]
    if card == "card02":
        expected_cols = ["Открытый паз | L ≤ 20 мм", "Открытый паз | 20 < L ≤ 40 мм",
                         "Закрытый паз | L ≤ 20 мм", "Закрытый паз | 20 < L ≤ 40 мм"]
        expected_param = "width_b_mm"
    else:
        expected_cols = [10., 20., 30., 50.] if card == "card01" else [10., 20., 30., 40., 60.]
        expected_param = "diameter_d_mm"
    actual = {"rows": grid.rows_range, "cols": grid.cols_range,
              "row_param": grid.row_param_name, "col_param": grid.col_param_name}
    expected = {"rows": expected_rows, "cols": expected_cols,
                "row_param": expected_param, "col_param": "length_l_mm"}
    assert actual == expected, f"B18 {path.name}: raw header={tables_header(pages, ref)}"


def tables_header(pages, ref):
    return [t.values[:ref["header_rows"]] for p in pages for t in p.tables]
