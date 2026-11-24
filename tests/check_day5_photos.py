"""Measure photo numeric cells against the printed originals (not OCR confidence)."""
import argparse
import json
import logging
from pathlib import Path
import time
from normdoc2json.ocr import iter_ocr_pages


def numeric(value):
    """Normalize only decimal punctuation; never guess missing digits."""
    try:
        return float(str(value).strip().replace(',','.'))
    except (ValueError,TypeError):
        return None


def main():
    """Run the six photographs and write reproducible accuracy/timing results."""
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    logging.disable(logging.WARNING)
    folder=Path(__file__).parent/'fixtures/phone_photos'
    expected=json.loads((folder/'expected.json').read_text(encoding='utf-8'))
    results=[]
    for path in sorted(folder.glob('*.jpg')):
        start=time.perf_counter()
        pages=list(iter_ocr_pages(path))
        reference=expected[path.stem.split('_')[0]]
        tables=[t for p in pages for t in p.tables]
        grid=tables[0].values if len(tables)==1 else []
        correct,total=0,0
        for r,row in enumerate(reference['values']):
            if r<reference['header_rows']:continue
            for c,value in enumerate(row):
                if c==0 or numeric(value) is None:continue
                total+=1
                if r<len(grid) and c<len(grid[r]) and numeric(grid[r][c])==numeric(value):correct+=1
        result={'file':path.name,'seconds':round(time.perf_counter()-start,3),
                'correct_numeric_cells':correct,'total_numeric_cells':total,
                'accuracy':correct/total,'grids':[t.values for t in tables],
                'warnings':[w for p in pages for w in p.warnings]}
        results.append(result)
        print(f'{path.name}: {correct}/{total}, {result["seconds"]}s',flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
