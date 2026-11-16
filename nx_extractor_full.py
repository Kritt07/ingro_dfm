"""Full NX extractor for Ingro DFM.

This script is meant to be run **inside Siemens NX** (Tools → Run NX Open → Python Script)
or via the NX batch mode (UGII.exe -batch -run). It:
1. Collects all required data from the currently opened part.
2. Builds a JSON passport that follows the schema defined in
   `cad_extractors/schema_passport.py`.
3. Calls the DFM core (`ingro_dfm.core.model.compute`) and prints the result.

The script uses only the standard NX Open Python API (nxopen) and the
Ingro‑DFM package that lives in the same directory tree.
"""

import json
import os
import sys
import traceback

# ---------------------------------------------------------------------
# 1. Connect to NX Open API
# ---------------------------------------------------------------------
try:
    import nxopen
except Exception as e:
    sys.stderr.write("❌ Unable to import nxopen – make sure the script is run from within Siemens NX.\n")
    sys.stderr.write(str(e) + "\n")
    sys.exit(1)

# ---------------------------------------------------------------------
# 2. Helper to read a user‑defined attribute (or return None)
# ---------------------------------------------------------------------
def _attr(part, name, default=None):
    try:
        return part.GetUserAttribute(name)
    except Exception:
        return default

# ---------------------------------------------------------------------
# 3. Build the passport dictionary according to the specification
# ---------------------------------------------------------------------
def collect_passport(part: nxopen.Part) -> dict:
    # Identification block
    identification = {
        "part_name": part.Name,
        "material_key": _attr(part, "MaterialKey", "45"),
        "hardness_hb": float(_attr(part, "HardnessHB", 180)),
        "has_heat_treatment": _attr(part, "HeatTreatment", "False") == "True",
    }

    # Geometry block – simple bounding‑box extraction
    bodies = part.Bodies
    if not bodies:
        raise RuntimeError("The part contains no B‑Rep bodies.")

    min_x, max_x = float("inf"), float("-inf")
    min_z, max_z = float("inf"), float("-inf")
    for body in bodies:
        for face in body.GetFaces():
            bb = face.GetBoundingBox()
            min_x = min(min_x, bb.MinX)
            max_x = max(max_x, bb.MaxX)
            min_z = min(min_z, bb.MinZ)
            max_z = max(max_z, bb.MaxZ)

    D_max_mm = round((max_x - min_x) * 1000.0, 2)
    L_total_mm = round((max_z - min_z) * 1000.0, 2)
    LD_ratio = round(L_total_mm / D_max_mm, 3) if D_max_mm else 0.0
    part_mass_kg = float(_attr(part, "MassKg", 0.5))

    geometry = {
        "D_max_mm": D_max_mm,
        "L_total_mm": L_total_mm,
        "LD_ratio": LD_ratio,
        "part_mass_kg": part_mass_kg,
    }

    # Surfaces block – we enumerate every face; PMI data (Ra, IT) are expected
    # as user attributes on the face. If they are missing we fall back to
    # standard values from the specification.
    surfaces = []
    for i, body in enumerate(bodies, start=1):
        for j, face in enumerate(body.GetFaces(), start=1):
            code = f"S{i}_{j}"
            # Basic type detection – for the prototype we treat everything as
            # a cylinder; a real implementation would inspect the geometry.
            surf_type = "cylinder"
            bb = face.GetBoundingBox()
            D_mm = round((bb.MaxX - bb.MinX) * 1000.0, 2)
            L_mm = round((bb.MaxZ - bb.MinZ) * 1000.0, 2)
            z_coord_mm = round(bb.MinZ * 1000.0, 2)
            Ra_um = float(_attr(face, "Ra", 6.3))
            IT = int(_attr(face, "IT", 12))
            purpose = "свободная"  # default purpose
            extra_params = {}
            confidence = "auto (geometry)"
            surfaces.append({
                "code": code,
                "surf_type": surf_type,
                "D_mm": D_mm,
                "L_mm": L_mm,
                "z_coord_mm": z_coord_mm,
                "Ra_um": Ra_um,
                "IT": IT,
                "purpose": purpose,
                "extra_params": extra_params,
                "confidence": confidence,
            })

    # Production block – values can be stored as user attributes on the part
    production = {
        "stock_type": _attr(part, "StockType", "bar"),
        "D_stock_mm": round(float(_attr(part, "D_stock_mm", D_max_mm)), 2),
        "L_stock_mm": round(float(_attr(part, "L_stock_mm", L_total_mm)), 2),
        "stock_mass_kg": round(float(_attr(part, "StockMassKg", part_mass_kg)), 3),
        "kim_ratio": round(float(_attr(part, "KimRatio", 0.8)), 3),
        "batch_size_q": int(_attr(part, "BatchSize", 5)),
        "machine_model": _attr(part, "MachineModel", "1К62"),
    }

    passport = {
        "identification": identification,
        "geometry": geometry,
        "surfaces": surfaces,
        "production": production,
    }
    return passport

# ---------------------------------------------------------------------
# 4. Main – compute DFM and print results
# ---------------------------------------------------------------------
def main():
    try:
        session = nxopen.Session.GetSession()
        part = session.Parts.Work
        if part is None:
            raise RuntimeError("No active part is open in NX.")

        passport = collect_passport(part)

        # Save passport next to the part file for reference/debugging
        passport_path = os.path.splitext(part.FullPath)[0] + "_passport.json"
        with open(passport_path, "w", encoding="utf-8") as f:
            json.dump(passport, f, ensure_ascii=False, indent=2)

        # Add project root to sys.path so we can import ingro_dfm modules
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if project_root not in sys.path:
            sys.path.append(project_root)

        from ingro_dfm.core.model import compute
        result = compute(passport)

        # Pretty print the result in the NX Python output window
        print("\n=== Ingro DFM Result ===")
        print(f"Nvr (minutes)          : {result['Nvr']:.2f}")
        print(f"Ut (technological lvl): {result['Ut']:.3f}")
        print(f"Warnings count         : {len(result['warnings'])}")
        for w in result['warnings']:
            print(f"  • {w}")
        print(f"Estimated saved minutes: {result['saved_minutes']:.2f}")
        print(f"Passport saved as      : {passport_path}\n")

    except Exception as exc:
        print("\n❌ Error while extracting data from NX:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
