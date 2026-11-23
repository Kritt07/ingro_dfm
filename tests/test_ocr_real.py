"""Optional real-engine integration, including TIFF/PDF and JSON round trip."""
import io
import time
import pytest
from PIL import Image, ImageDraw, ImageFont
import pymupdf
from normdoc2json.ocr_engine import TesseractEngine
from normdoc2json.ocr import iter_ocr_pages, ocr_document
from norm_importer.schema import NormDocDocument


def sample():
    image=Image.new('RGB',(1000,700),'white')
    draw=ImageDraw.Draw(image)
    try:
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',36)
    except OSError:
        font=ImageFont.truetype('DejaVuSans.ttf',36)
    for x in (100,350,600,850): draw.line((x,150,x,600),fill='black',width=3)
    for y in (150,300,450,600): draw.line((100,y,850,y),fill='black',width=3)
    for r,row in enumerate([['D','10','20'],['5','0,28','0'],['10','0,45','0,88']]):
        for c,value in enumerate(row):draw.text((130+c*250,190+r*150),value,font=font,fill='black')
    draw.text((100,40),'Карта 04. Сверление',font=font,fill='black')
    return image


@pytest.fixture
def engine():
    try: return TesseractEngine()
    except RuntimeError as exc: pytest.skip(str(exc))


def test_real_scan_tiff_pdf_json(tmp_path,engine):
    image=sample()
    png=tmp_path/'scan.png';image.save(png,dpi=(300,300))
    tiff=tmp_path/'scan.tiff';image.save(tiff,save_all=True,append_images=[image],dpi=(300,300))
    pdf=tmp_path/'scan.pdf'
    doc=pymupdf.open();page=doc.new_page(width=240,height=168)
    stream=io.BytesIO();image.save(stream,format='PNG')
    page.insert_image(page.rect,stream=stream.getvalue());doc.save(pdf);doc.close()
    start=time.perf_counter()
    for path,count in [(png,1),(tiff,2),(pdf,1)]:
        pages=list(iter_ocr_pages(path,engine=engine,debug_dir=tmp_path/'debug'))
        assert len(pages)==count
        for page in pages:
            assert len(page.tables)==1
            assert page.tables[0].values[1:]==[['5','0,28','0'],['10','0,45','0,88']]
    document=ocr_document(png,engine=engine)
    assert document.cards[0].table_grid.values_matrix==[[.28,0],[.45,.88]]
    assert NormDocDocument.model_validate_json(document.model_dump_json())==document
    from typer.testing import CliRunner
    from norm_importer.cli import app
    output=tmp_path/'result.json'
    result=CliRunner().invoke(app,['-i',str(png),'-o',str(output),'--strict','--debug-images'])
    # Header/notes handoff remains explicitly marked for semantic review.
    assert result.exit_code==1
    assert NormDocDocument.model_validate_json(output.read_text(encoding='utf-8')).cards[0].table_grid.values_matrix==[[.28,0],[.45,.88]]
    assert list((tmp_path/'scan.png.debug').glob('*.png'))
    print(f'Real OCR: {time.perf_counter()-start:.2f}s for 5 page passes')
