"""Kompas‑3D extractor placeholder.

Analogous to the NX extractor, this stub simply reads a JSON file that is
assumed to be produced by a Kompas‑3D export routine and returns the parsed
passport dictionary.
"""

import json
from pathlib import Path
from typing import Dict, Any

def extract_from_kompas(file_path: str) -> Dict[str, Any]:
    """Load a passport JSON exported from КОМПАС‑3D.

    Parameters
    ----------
    file_path: str
        Path to the JSON file.
    Returns
    -------
    dict
        Passport data structured according to ``schema_passport.py``.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Kompas extractor: file not found – {file_path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def extract_passport_v2(snapshot_json_path: str | None = None):
    """Эволюционный мост v2.0: извлекает PartPassport v2.0 через cad_addons.kompas_addon."""
    from ingro_dfm.cad_addons.kompas_addon.kompas_brep_extractor import KompasBRepExtractor

    extractor = KompasBRepExtractor()
    if snapshot_json_path is not None:
        return extractor.extract_passport(snapshot_json_path=Path(snapshot_json_path))
    return extractor.extract_passport()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Kompas‑3D extractor stub")
    parser.add_argument("input", help="Path to JSON passport file")
    args = parser.parse_args()
    passport = extract_from_kompas(args.input)
    print(json.dumps(passport, ensure_ascii=False, indent=2))
