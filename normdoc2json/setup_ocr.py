"""Download official Tesseract fast language data for subsequent offline use."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    """Install selected language files and record their SHA256 checksums."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('.ocr_models'))
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    manifest={}
    for lang in ('rus','eng'):
        url=f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/{lang}.traineddata'
        data=urlopen(url,timeout=60).read()
        if len(data)<100000:
            raise RuntimeError(f'Invalid language download: {lang}')
        temporary=args.output/f'{lang}.tmp'
        temporary.write_bytes(data)
        temporary.replace(args.output/f'{lang}.traineddata')
        manifest[lang]={'url':url,'sha256':hashlib.sha256(data).hexdigest()}
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Offline OCR data ready: {args.output.resolve()}')


if __name__=='__main__':
    main()
