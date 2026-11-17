"""Проверять маршрутизацию на тестовых документах и фотографиях с телефона."""

from pathlib import Path
import zipfile

from PIL import Image
import pymupdf
import pytest

from normdoc2json import InspectionError, inspect_file


def test_pdf_page_routing(tmp_path):
    """Проверить типы текстовой, сканированной и пустой страниц PDF."""
    picture = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "white").save(picture)
    path = tmp_path / "mixed.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 40), "Normative table")
        document.new_page().insert_image(pymupdf.Rect(0, 0, 100, 100), filename=str(picture))
        document.new_page()
        document.save(path)
    result = inspect_file(path)
    assert result.source_format == "pdf_hybrid"
    assert result.page_kinds == ["pdf_text", "pdf_scanned", "pdf_empty"]


@pytest.mark.parametrize("kind", ["docx", "xlsx", "odt", "ods"])
def test_office_signature_over_extension(tmp_path, kind):
    """Проверить определение офисного формата при неверном расширении."""
    path = tmp_path / "wrong.dat"
    with zipfile.ZipFile(path, "w") as archive:
        if kind in {"docx", "xlsx"}:
            member = "word/document.xml" if kind == "docx" else "xl/workbook.xml"
            archive.writestr(member, "<document/>")
        else:
            suffix = "text" if kind == "odt" else "spreadsheet"
            archive.writestr("mimetype", f"application/vnd.oasis.opendocument.{suffix}")
    assert inspect_file(path).source_format == kind


def test_multipage_tiff(tmp_path):
    """Проверить число страниц и разрешение многостраничного TIFF."""
    path = tmp_path / "scan.tiff"
    page = Image.new("RGB", (20, 20), "white")
    page.save(path, save_all=True, append_images=[page], dpi=(300, 300))
    result = inspect_file(path)
    assert result.page_count == 2
    assert result.dpi == (300, 300)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_text_encoding(tmp_path, encoding):
    """Проверить восстановление текста CSV в определённой кодировке."""
    path = tmp_path / "table.csv"
    content = "Диаметр;Время\n10;0,45\n"
    path.write_bytes(content.encode(encoding))
    result = inspect_file(path)
    assert path.read_bytes().decode(result.encoding) == content


@pytest.mark.parametrize("content", [b"", b"%PDF-damaged", b"PK\x03\x04broken"])
def test_damaged_documents(tmp_path, content):
    """Проверить отклонение пустых и повреждённых документов."""
    path = tmp_path / "broken.pdf"
    path.write_bytes(content)
    with pytest.raises(InspectionError):
        inspect_file(path)


def test_missing_file(tmp_path):
    """Проверить ошибку при обращении к отсутствующему файлу."""
    with pytest.raises(InspectionError):
        inspect_file(tmp_path / "missing.txt")


@pytest.mark.parametrize(
    "filename",
    [
        "card01_straight.jpg",
        "card01_tilted.jpg",
        "card02_straight.jpg",
        "card02_tilted.jpg",
        "card03_straight.jpg",
        "card03_tilted.jpg",
    ],
)
def test_phone_photo_routing(filename):
    """Проверить формат и метаданные каждого снимка печатной карты."""
    path = Path(__file__).parent / "fixtures" / "phone_photos" / filename

    result = inspect_file(path)

    assert result.path == str(path)
    assert result.source_format == "jpeg"
    assert result.mime_type == "image/jpeg"
    assert result.page_count == 1
    assert result.dpi == (72.0, 72.0)
    assert result.encoding is None
    assert result.page_kinds == []
    assert result.warnings == []
