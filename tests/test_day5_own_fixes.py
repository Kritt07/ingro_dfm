import pytest
from normdoc2json.ocr import OCRPage,ocr_document,table_header_lines
from normdoc2json.ocr_tables import OCRTable
from normdoc2json.ocr_engine import OCRWord


@pytest.mark.parametrize('second_box,second_title',[
    ((0,330,200,500),(0,300,200,320)),
    ((300,30,500,200),(300,0,500,20)),
])
def test_local_headers(monkeypatch,second_box,second_title):
    tables=[OCRTable(box,[['D','10'],['5','0.28']],[],[]) for box in [(0,30,200,200),second_box]]
    page=OCRPage('two.png',1,tables,blocks=[
        OCRWord('Карта 01. Сверление',(0,0,200,20),1,(1,1,1)),
        OCRWord('Карта 02. Фрезерование',second_title,1,(2,1,1))])
    monkeypatch.setattr('normdoc2json.ocr.iter_ocr_pages',lambda *a,**k:iter([page]))
    doc=ocr_document('two.png')
    assert [c.applicability_conditions.operation_type for c in doc.cards]==['Сверление','Фрезерование']
    page.blocks=page.blocks[:1]
    assert table_header_lines(page,tables[1])==[]
