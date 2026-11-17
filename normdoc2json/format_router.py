"""Inspect source documents before selecting an extraction pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
import zipfile

from charset_normalizer import from_bytes
import olefile
from PIL import Image
import pymupdf


class InspectionError(ValueError):
    """A source cannot be inspected or its format is unsupported."""


@dataclass
class Inspection:
    """Routing metadata; PDF page kinds preserve mixed-document routing."""

    path: str
    source_format: str
    mime_type: str
    encoding: str | None = None
    page_count: int | None = None
    page_kinds: list[str] = field(default_factory=list)
    dpi: tuple[float, float] | None = None
    warnings: list[str] = field(default_factory=list)


def inspect_file(path: str | Path) -> Inspection:
    """Inspect a file, raising InspectionError on unreadable or invalid input."""
    source = Path(path)
    try:
        if not source.is_file():
            raise InspectionError(f"Expected an existing file: {source}")
        with source.open("rb") as stream:
            header = stream.read(8192)
        if not header:
            raise InspectionError(f"Empty file: {source}")
        result = _inspect(source, header)
        return result
    except InspectionError:
        raise
    except Exception as error:
        raise InspectionError(f"Cannot inspect {source}: {error}") from error


def _inspect(source: Path, header: bytes) -> Inspection:
    if b"%PDF-" in header[:1024]:
        return _inspect_pdf(source)
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
            formats = {
                "word/document.xml": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                "xl/workbook.xml": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            }
            for member, (kind, mime) in formats.items():
                if member in names:
                    return Inspection(str(source), kind, mime)
            if "mimetype" in names:
                mime = archive.read("mimetype").decode("ascii").strip()
                kinds = {"application/vnd.oasis.opendocument.text": "odt",
                         "application/vnd.oasis.opendocument.spreadsheet": "ods"}
                if mime in kinds:
                    return Inspection(str(source), kinds[mime], mime)
        raise InspectionError(f"Unsupported ZIP document: {source}")
    if header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        with olefile.OleFileIO(source) as document:
            if document.exists("WordDocument"):
                return Inspection(str(source), "doc", "application/msword")
            if document.exists("Workbook") or document.exists("Book"):
                return Inspection(str(source), "xls", "application/vnd.ms-excel")
        raise InspectionError(f"Unsupported OLE document: {source}")
    if header.startswith(b"{\\rtf"):
        return Inspection(str(source), "rtf", "application/rtf")
    image_signatures = (b"\x89PNG", b"\xff\xd8\xff", b"BM", b"II*\x00", b"MM\x00*", b"RIFF")
    if header.startswith(image_signatures):
        with Image.open(source) as picture:
            kind = (picture.format or "").lower()
            if kind not in {"jpeg", "png", "bmp", "tiff", "webp"}:
                raise InspectionError(f"Unsupported image: {source}")
            count = getattr(picture, "n_frames", 1)
            resolution = picture.info.get("dpi")
            dpi = None
            if resolution:
                dpi = (float(resolution[0]), float(resolution[1]))
            for index in range(count):
                picture.seek(index)
                picture.load()
            result = Inspection(str(source), kind, f"image/{kind}", page_count=count, dpi=dpi)
            if dpi is None:
                result.warnings.append("Image DPI is unavailable")
            return result
    if source.suffix.lower() in {".txt", ".csv"}:
        raw = source.read_bytes()
        detected = from_bytes(raw).best()
        if detected is None or "\x00" in str(detected):
            raise InspectionError(f"Cannot determine text encoding: {source}")
        kind = source.suffix.lower()[1:]
        mime = "text/csv" if kind == "csv" else "text/plain"
        return Inspection(str(source), kind, mime, encoding=detected.encoding)
    raise InspectionError(f"Unsupported or damaged document: {source}")


def _inspect_pdf(source: Path) -> Inspection:
    with pymupdf.open(source) as document:
        if document.needs_pass:
            raise InspectionError(f"Password-protected PDF: {source}")
        kinds = []
        warnings = []
        for index, page in enumerate(document):
            try:
                text = bool(page.get_text().strip())
                images = bool(page.get_image_info())
                kind = "pdf_text"
                if text and images:
                    kind = "pdf_hybrid"
                elif not text and images:
                    kind = "pdf_scanned"
                elif not text:
                    kind = "pdf_empty"
                kinds.append(kind)
            except Exception as error:
                kinds.append("pdf_unknown")
                warnings.append(f"Page {index + 1}: {error}")
        relevant = set(kinds) - {"pdf_empty", "pdf_unknown"}
        kind = "pdf_hybrid"
        if len(relevant) == 1:
            kind = next(iter(relevant))
        elif not relevant:
            kind = "pdf_unknown"
            warnings.append("No text or raster content detected")
        return Inspection(str(source), kind, "application/pdf", page_count=len(document),
                          page_kinds=kinds, warnings=warnings)
