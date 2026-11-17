"""Build reproducible routing fixtures from a small synthetic table."""

from dataclasses import asdict
import json
from pathlib import Path

from PIL import Image, ImageDraw
import pymupdf

from normdoc2json import inspect_file


def build_samples(destination: Path) -> None:
    """Write synthetic text, image and PDF inputs with inspection metadata."""
    destination.mkdir(parents=True, exist_ok=True)
    picture = Image.new("RGB", (600, 300), "white")
    drawing = ImageDraw.Draw(picture)
    drawing.text((30, 30), "Diameter (mm) | Time (min)\n10 | 0.45\n20 | 0.80", fill="black")
    for extension in ("png", "jpeg", "bmp", "webp"):
        picture.save(destination / f"table.{extension}")
    picture.save(destination / "table.tiff", save_all=True, append_images=[picture], dpi=(300, 300))
    for kind in ("text", "scanned", "hybrid"):
        with pymupdf.open() as document:
            page = document.new_page()
            if kind in {"text", "hybrid"}:
                page.insert_text((30, 30), "Diameter | Time\n10 | 0.45\n20 | 0.80")
            if kind in {"scanned", "hybrid"}:
                page.insert_image(pymupdf.Rect(30, 80, 330, 230), filename=str(destination / "table.png"))
            document.save(destination / f"{kind}.pdf")
    (destination / "table.csv").write_text("Диаметр;Время\n10;0,45\n20;0,80\n", encoding="utf-8")
    results = [asdict(inspect_file(path)) for path in sorted(destination.iterdir())
               if path.suffix not in {".json", ".md"}]
    for result in results:
        result["path"] = Path(result["path"]).name
    (destination / "manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    build_samples(Path("tests/fixtures/router"))
