from pathlib import Path
from typer.testing import CliRunner

from norm_importer.cli import app
from norm_importer.schema import NormDocDocument


runner = CliRunner()


def test_cli_single_file_conversion(tmp_path: Path):
    """Проверка конвертации одиночного файла в указанный JSON-файл."""
    input_file = tmp_path / "karta_04.txt"
    input_file.write_text("Карта 04. Сверление отверстий", encoding="utf-8")
    output_file = tmp_path / "out" / "karta_04_parsed.json"

    result = runner.invoke(
        app,
        [
            "--input", str(input_file),
            "--output", str(output_file),
            "--ocr-lang", "rus+eng",
        ],
    )

    assert result.exit_code == 0
    assert output_file.exists()

    doc = NormDocDocument.model_validate_json(output_file.read_text(encoding="utf-8"))
    assert doc.source_metadata.source_file == "karta_04.txt"


def test_cli_batch_directory_conversion(tmp_path: Path):
    """Проверка пакетного обхода директории с фильтрацией поддерживаемых форматов."""
    in_dir = tmp_path / "batch_in"
    in_dir.mkdir()
    (in_dir / "doc1.pdf").write_bytes((Path(__file__).parent / "fixtures/pdf_tables/ruled.pdf").read_bytes())
    (in_dir / "doc2.xlsx").write_bytes(b"PK")
    (in_dir / "ignored.exe").write_bytes(b"MZ")

    out_dir = tmp_path / "batch_out"

    result = runner.invoke(
        app,
        [
            "-i", str(in_dir),
            "-o", str(out_dir),
        ],
    )

    assert result.exit_code == 0
    assert (out_dir / "doc1_pdf.json").exists()
    assert (out_dir / "doc2_xlsx.json").exists()
    assert not (out_dir / "ignored_exe.json").exists()


def test_cli_strict_mode_returns_nonzero_on_manual_review(tmp_path: Path):
    """Проверка возврата ненулевого exit-code в режиме --strict при наличии предупреждений."""
    input_file = tmp_path / "scan.png"
    input_file.write_bytes(b"\x89PNG\r\n")
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "-i", str(input_file),
            "-o", str(output_dir),
            "--strict",
            "--debug-images",
        ],
    )

    assert result.exit_code == 1
    # A corrupt image must not produce a fabricated normative card.
    assert not (output_dir / "scan_png.json").exists()


def test_cli_empty_directory_exits_with_error(tmp_path: Path):
    """Проверка завершения с кодом 1, если во входной директории нет поддерживаемых файлов."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "-i", str(empty_dir),
            "-o", str(output_dir),
        ],
    )

    assert result.exit_code == 1

def test_cli_batch_directory_no_overwrite_same_stem(tmp_path: Path):
    """Проверка, что файлы с одинаковым именем и разным расширением не перезаписывают друг друга."""
    in_dir = tmp_path / "batch_in"
    in_dir.mkdir()
    (in_dir / "karta.pdf").write_bytes((Path(__file__).parent / "fixtures/pdf_tables/ruled.pdf").read_bytes())
    (in_dir / "karta.xlsx").write_bytes(b"PK")
    (in_dir / "ignored.exe").write_bytes(b"MZ")

    out_dir = tmp_path / "batch_out"

    result = runner.invoke(
        app,
        ["-i", str(in_dir), "-o", str(out_dir)],
    )

    assert result.exit_code == 0
    assert (out_dir / "karta_pdf.json").exists()
    assert (out_dir / "karta_xlsx.json").exists()
    assert not (out_dir / "ignored_exe.json").exists()
