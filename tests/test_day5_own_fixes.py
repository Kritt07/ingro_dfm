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


def test_table_failure_does_not_drop_neighbor(monkeypatch):
    import numpy as np
    from normdoc2json.ocr import iter_ocr_pages
    from normdoc2json.image_io import ImagePage
    image=np.full((300,300,3),255,np.uint8)
    monkeypatch.setattr('normdoc2json.ocr._pages',lambda *a:iter([ImagePage('x',1,image,(300,300))]))
    regions=[((0,0,100,100),[]),((150,0,250,100),[])]
    monkeypatch.setattr('normdoc2json.ocr.detect_grid',lambda a:(regions,a))
    def recognize(regions,*args):
        if regions[0][0][0]==0:raise TimeoutError('bad table')
        return []
    monkeypatch.setattr('normdoc2json.ocr.recognize_cells',recognize)
    monkeypatch.setattr('normdoc2json.ocr.reconstruct_tables',lambda regions,*a:([OCRTable(regions[0][0],[],[],[])],[],[]))
    class Engine:
        def recognize(self,*a):raise TimeoutError('page text')
    page=list(iter_ocr_pages('x',engine=Engine()))[0]
    assert len(page.tables)==1 and page.tables[0].bbox==(150,0,250,100)
    assert any('bad table' in w for w in page.warnings)
    assert any('page text' in w for w in page.warnings)


def test_header_ocr_keeps_resolution_and_separate_cells():
    import numpy as np
    from normdoc2json.ocr_tables import recognize_cells
    image=np.full((400,400),255,np.uint8)
    image[20:100,20:150]=0
    image[20:100,220:350]=0
    calls=[]
    class Engine:
        def recognize(self,image,psm=6):
            calls.append(image.shape)
            return [OCRWord('L <= 20',(20,20,70,50),.95,(1,1,1))]
    words=recognize_cells([((0,0,400,200),[(0,0,200,200),(200,0,400,200)])],image,Engine())
    assert len(calls)==2 and all(h>100 for h,w in calls)
    assert len(words)==2 and words[0].bbox[0]<200<words[1].bbox[0]


def test_header_diagnostics_reach_document(monkeypatch):
    from norm_importer.header_parser import parse_card_header
    header = parse_card_header([], fallback_stem="scan")
    header.warnings = ["Unrecognized explicit formula"]
    table = OCRTable((0, 30, 200, 200), [["D", "10"], ["5", "0.28"]], [], [])
    page = OCRPage("scan.png", 2, [table])
    monkeypatch.setattr("normdoc2json.ocr.iter_ocr_pages", lambda *a, **k: iter([page]))
    monkeypatch.setattr("normdoc2json.ocr.table_header_lines", lambda *a: ["Card"])
    monkeypatch.setattr("norm_importer.header_parser.parse_card_header", lambda *a, **k: header)
    doc = ocr_document("scan.png")
    assert doc.source_metadata.warnings == ["Page 2 table 1: Unrecognized explicit formula"]
    assert doc.source_metadata.requires_manual_review
    assert len(doc.cards) == 1
