import numpy as np
from PIL import Image
from normdoc2json.ocr import iter_ocr_pages


def test_tiff_continues_after_engine_failure(tmp_path):
    frames=[Image.fromarray(np.full((100,100,3),255,np.uint8)) for _ in range(2)]
    path=tmp_path/'pages.tiff'
    frames[0].save(path,save_all=True,append_images=frames[1:],dpi=(300,300))
    class Engine:
        calls=0
        def recognize(self,image):
            self.calls+=1
            if self.calls==1: raise RuntimeError('test failure')
            return []
    pages=list(iter_ocr_pages(path,engine=Engine()))
    assert [p.page_number for p in pages]==[1,2]
    assert any('test failure' in w for w in pages[0].warnings)
    assert any('No closed table' in w for w in pages[1].warnings)


def test_pdf_pixel_limit(tmp_path):
    import pymupdf
    doc=pymupdf.open(); doc.new_page()
    path=tmp_path/'large.pdf';doc.save(path);doc.close()
    pages=list(iter_ocr_pages(path,engine=object(),max_pixels=100))
    assert pages[0].requires_manual_review
    assert 'pixel limit' in pages[0].warnings[0]
