import json
from pathlib import Path
import pymupdf
import pytest
from normdoc2json import extract_pdf, InspectionError

ROOT = Path(__file__).parent / 'fixtures' / 'pdf_tables'

@pytest.mark.parametrize('name', ['ruled', 'borderless'])
def test_reference_grid(name):
    result = extract_pdf(ROOT / (name+'.pdf'))
    table = result.pages[0].tables[0]
    assert [[v or '' for v in r] for r in table.values] == json.loads((ROOT/'expected.json').read_text())
    assert table.page_number == 1
    assert len(table.cell_bboxes) == 3
    assert any('Note:' in b.text for b in result.pages[0].blocks)
    assert result.requires_manual_review == (name == 'borderless')

def test_bad_file(tmp_path):
    path = tmp_path/'bad.pdf'
    path.write_bytes(b'%PDF-broken')
    with pytest.raises(InspectionError): extract_pdf(path)

def test_page_failure_continues(tmp_path, monkeypatch):
    import normdoc2json.pdf as module
    path = tmp_path/'pages.pdf'
    with pymupdf.open(ROOT/'ruled.pdf') as source:
        with pymupdf.open() as doc:
            doc.insert_pdf(source)
            doc.insert_pdf(source)
            doc.save(path)
    original = module._read_page
    def read(page, number, kind):
        if number == 1: raise ValueError('test failure')
        return original(page, number, kind)
    monkeypatch.setattr(module, '_read_page', read)
    result = extract_pdf(path)
    assert result.pages[0].page_number == 2
    assert result.requires_manual_review

def test_empty_page(tmp_path):
    path = tmp_path/'empty.pdf'
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path)
    result = extract_pdf(path)
    assert not result.pages[0].tables
    assert result.requires_manual_review

def test_merged_header(tmp_path):
    path = tmp_path/'merged.pdf'
    with pymupdf.open() as doc:
        p = doc.new_page()
        for y in [50,80,110,140]: p.draw_line((50,y),(350,y))
        for x in [50,150,350]: p.draw_line((x,50),(x,140))
        p.draw_line((250,80),(250,140))
        for x,y,text in [(55,70,'D'),(155,70,'Lengths'),(55,100,'6'),(155,100,'0,2'),(255,100,'0,3'),(55,130,'12'),(155,130,'0,4'),(255,130,'0,5')]:
            p.insert_text((x,y),text)
        doc.save(path)
    t = extract_pdf(path).pages[0].tables[0]
    assert (1,2,1,3) in t.merged_ranges
    assert t.values[0] == ['D','Lengths','Lengths']

def test_two_tables(tmp_path):
    path = tmp_path/'two.pdf'
    with pymupdf.open() as doc:
        p=doc.new_page()
        for top in [50,250]:
            for y in [top,top+30,top+60]: p.draw_line((50,y),(250,y))
            for x in [50,150,250]: p.draw_line((x,top),(x,top+60))
            for x,y,text in [(55,top+20,'D'),(155,top+20,'15'),(55,top+50,'6'),(155,top+50,'0,2')]: p.insert_text((x,y),text)
        doc.save(path)
    assert len(extract_pdf(path).pages[0].tables) == 2
