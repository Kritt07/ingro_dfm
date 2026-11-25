import json
from typer.testing import CliRunner
from norm_importer.cli import app
from normdoc2json.ocr import OCRPage, ocr_document
from normdoc2json.ocr_tables import OCRTable


def install_page(monkeypatch, headers, confidence):
    table = OCRTable((0, 0, 100, 100), [headers, ["5", "0.28", "0.45"]], [],
                     [[confidence] * 3, [.99] * 3])
    monkeypatch.setattr("normdoc2json.ocr.iter_ocr_pages",
                        lambda *a, **k: iter([OCRPage("scan.png", 2, [table])]))
    return table


def test_suspicious_headers_have_local_evidence(monkeypatch):
    table = install_page(monkeypatch, ["?", None, "20"], .85)
    doc = ocr_document("scan.png")
    note = next(w for w in doc.source_metadata.warnings if w.startswith("B18:"))
    assert "Page 2 table 1" in note
    assert "R1C2" in note and "85%" in note
    assert "не определено" in note
    assert json.dumps(table.values[:1], ensure_ascii=False) in note
    assert doc.source_metadata.requires_manual_review
    assert doc.cards[0].table_grid.values_matrix == [[.28, .45]]


def test_even_high_confidence_headers_require_review_in_strict_cli(monkeypatch, tmp_path):
    install_page(monkeypatch, ["Диаметр D", "L до 10", "L до 20"], .99)
    source = tmp_path / "scan.png"
    source.write_bytes(b"invalid png for mocked OCR")
    output = tmp_path / "result.json"
    result = CliRunner().invoke(app, ["-i", str(source), "-o", str(output), "--strict"])
    assert result.exit_code == 1
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["source_metadata"]["requires_manual_review"]
    assert any(w.startswith("B18:") for w in data["source_metadata"]["warnings"])
    assert data["cards"][0]["table_grid"]["values_matrix"] == [[.28, .45]]
