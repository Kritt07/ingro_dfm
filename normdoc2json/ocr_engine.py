"""Tesseract TSV adapter; word boxes use prepared-image pixels."""
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from PIL import Image


@dataclass
class OCRWord:
    """Recognized word with pixel rectangle and confidence in [0, 1]."""
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    line: tuple[int, int, int]


class TesseractEngine:
    """Run a local Tesseract installation without network access."""

    def __init__(self, lang='rus+eng', executable=None, tessdata=None, timeout=60):
        self.executable = executable or shutil.which('tesseract')
        if not self.executable and os.name == 'nt':
            candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Tesseract-OCR/tesseract.exe'
            if candidate.exists():
                self.executable = str(candidate)
        if not self.executable:
            raise RuntimeError('Tesseract not installed; set executable or add it to PATH')
        self.lang, self.timeout = lang, timeout
        self.options = ['--tessdata-dir', str(tessdata)] if tessdata else []
        available = self._run(['--list-langs', *self.options]).splitlines()
        missing = set(lang.split('+')) - set(available)
        if missing:
            raise RuntimeError('Missing Tesseract languages: ' + ', '.join(sorted(missing)))

    def _run(self, args):
        result = subprocess.run([self.executable, *args], capture_output=True,
                                timeout=self.timeout, encoding='utf-8', errors='replace',
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Tesseract failed')
        return result.stdout

    def recognize(self, image, psm=11):
        """Recognize an entire image, returning original words and confidence."""
        with tempfile.TemporaryDirectory(prefix='ingro_ocr_') as folder:
            path = Path(folder) / 'page.png'
            Image.fromarray(image).save(path, dpi=(300, 300))
            raw = self._run([str(path), 'stdout', *self.options, '-l', self.lang,
                             '--oem', '1', '--psm', str(psm), 'tsv'])
        words = []
        for row in csv.DictReader(io.StringIO(raw), delimiter='\t', quoting=csv.QUOTE_NONE):
            if row['level'] != '5' or not row.get('text', '').strip():
                continue
            x, y, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
            words.append(OCRWord(row['text'], (x, y, x+w, y+h),
                                 max(0., min(1., float(row['conf']) / 100)),
                                 tuple(int(row[k]) for k in ('block_num', 'par_num', 'line_num'))))
        return words
