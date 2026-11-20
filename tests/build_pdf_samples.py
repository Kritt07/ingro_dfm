from pathlib import Path
import json
import pymupdf

ROOT = Path(__file__).parent / 'fixtures' / 'pdf_tables'
GRID = [['D', '15', '30'], ['6', '0,28', ''], ['12', '0', '0,88']]

def build():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, ruled in [('ruled', True), ('borderless', False)]:
        doc = pymupdf.open()
        p = doc.new_page()
        p.insert_text((50, 40), 'Normative test card')
        for r, row in enumerate(GRID):
            for c, value in enumerate(row):
                p.insert_text((55+c*100, 80+r*30), value)
        if ruled:
            for x in [50,150,250,350]: p.draw_line((x,60),(x,150))
            for y in [60,90,120,150]: p.draw_line((50,y),(350,y))
        p.insert_text((50,180), 'Note: preserve this text.')
        doc.save(ROOT / (name+'.pdf'))
        doc.close()
    (ROOT/'expected.json').write_text(json.dumps(GRID), encoding='utf-8')

if __name__ == '__main__': build()
