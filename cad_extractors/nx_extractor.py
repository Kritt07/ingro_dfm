"""NX extractor placeholder.

In a real implementation this script would use the Siemens NX Open API to
extract geometry, PMI surface finish, dimensions and thread features, then
populate the JSON passport defined in `schema_passport.py`.

For the purpose of this prototype we simply read a JSON file supplied by the
user (simulating the output of the CAD extractor) and return its contents.
"""

import json
from pathlib import Path
from typing import Dict, Any

def extract_from_nx(file_path: str) -> Dict[str, Any]:
    """Return a passport dictionary from a given file.

    *file_path* is expected to be a path to a JSON file that already follows the
    passport schema. The function loads the JSON and returns the dict.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"NX extractor: file not found – {file_path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def extract_passport_v2(snapshot_json_path: str | None = None):
    """Эволюционный мост v2.0: извлекает PartPassport v2.0 через cad_addons.nx_addon."""
    from ingro_dfm.cad_addons.nx_addon.nx_brep_extractor import NXBRepExtractor

    extractor = NXBRepExtractor()
    if snapshot_json_path is not None:
        return extractor.extract_passport(snapshot_json_path=Path(snapshot_json_path))
    return extractor.extract_passport()

if __name__ == "__main__":
    # Simple CLI for quick testing.
    import argparse
    parser = argparse.ArgumentParser(description="NX extractor stub")
    parser.add_argument("input", help="Path to JSON passport file")
    args = parser.parse_args()
    passport = extract_from_nx(args.input)
    print(json.dumps(passport, ensure_ascii=False, indent=2))
