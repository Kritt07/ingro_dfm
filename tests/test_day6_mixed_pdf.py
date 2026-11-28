import pymupdf
from normdoc2json.pdf import _extract_tables


def test_ruled_and_borderless_on_same_page():
    with pymupdf.open() as doc:
        page = doc.new_page()
        for y in (40, 70, 100, 130):
            page.draw_line((40, y), (240, y))
        for x in (40, 140, 240):
            page.draw_line((x, 40), (x, 130))
        for y in (60, 90, 120, 220, 250, 280):
            page.insert_text((50, y), "10")
            page.insert_text((150, y), "20")
        tables = _extract_tables(page, 1)
        assert len(tables) == 2
        assert [t.method for t in tables] == ["lines", "text"]
        assert tables[1].values == [["10", "20"]] * 3
