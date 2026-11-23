"""Check the external OCR boundary without requiring system binaries."""
from types import SimpleNamespace
import numpy as np
import pytest
from normdoc2json.ocr_engine import TesseractEngine


def test_tsv_and_languages(monkeypatch):
    def run(args, **kwargs):
        if '--list-langs' in args:
            return SimpleNamespace(returncode=0, stdout='List:\nrus\neng\n', stderr='')
        return SimpleNamespace(returncode=0, stderr='', stdout=(
            'level\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
            '5\t1\t1\t1\t2\t3\t10\t12\t91.5\t0,28\n'))
    monkeypatch.setattr('subprocess.run', run)
    engine = TesseractEngine(executable='test')
    word = engine.recognize(np.zeros((30, 30), dtype='uint8'))[0]
    assert word.text == '0,28' and word.bbox == (2, 3, 12, 15)
    assert word.confidence == .915
    with pytest.raises(RuntimeError, match='Missing'):
        TesseractEngine(lang='fra', executable='test')


def test_engine_failure(monkeypatch):
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(returncode=1, stderr='broken', stdout=''))
    with pytest.raises(RuntimeError, match='broken'):
        TesseractEngine(executable='test')
