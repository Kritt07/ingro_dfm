"""JSON schema for the *Passport of a detail* used across the project.

The schema follows the description in the specification (section 3). It is a
plain Python dictionary that can be fed to libraries such as ``jsonschema``
for validation.
"""

# The top‑level object is a mapping with four required blocks.
SCHEMA_PASS = {
    "type": "object",
    "required": ["identification", "geometry", "surfaces", "production"],
    "properties": {
        "identification": {
            "type": "object",
            "required": ["part_name", "material_key", "hardness_hb", "has_heat_treatment"],
            "properties": {
                "part_name": {"type": "string"},
                "material_key": {"type": "string", "enum": ["45", "40Х", "12Х18Н10Т", "Д16Т"]},
                "hardness_hb": {"type": "number"},
                "has_heat_treatment": {"type": "boolean"},
            },
        },
        "geometry": {
            "type": "object",
            "required": ["D_max_mm", "L_total_mm", "LD_ratio", "part_mass_kg"],
            "properties": {
                "D_max_mm": {"type": "number"},
                "L_total_mm": {"type": "number"},
                "LD_ratio": {"type": "number"},
                "part_mass_kg": {"type": "number"},
            },
        },
        "surfaces": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "surf_type", "D_mm", "L_mm", "z_coord_mm", "Ra_um", "IT", "purpose", "extra_params", "confidence"],
                "properties": {
                    "code": {"type": "string"},
                    "surf_type": {"type": "string"},
                    "D_mm": {"type": "number"},
                    "L_mm": {"type": "number"},
                    "z_coord_mm": {"type": "number"},
                    "Ra_um": {"type": "number"},
                    "IT": {"type": "integer"},
                    "purpose": {"type": "string"},
                    "extra_params": {"type": "object"},
                    "confidence": {"type": "string", "enum": ["auto (PMI)", "auto (geometry)", "default (Ra 6.3)", "manual"]},
                },
            },
        },
        "production": {
            "type": "object",
            "required": ["stock_type", "D_stock_mm", "L_stock_mm", "stock_mass_kg", "kim_ratio", "batch_size_q", "machine_model"],
            "properties": {
                "stock_type": {"type": "string", "enum": ["bar", "forging", "casting"]},
                "D_stock_mm": {"type": "number"},
                "L_stock_mm": {"type": "number"},
                "stock_mass_kg": {"type": "number"},
                "kim_ratio": {"type": "number"},
                "batch_size_q": {"type": "integer"},
                "machine_model": {"type": "string"},
            },
        },
    },
}

__all__ = ["SCHEMA_PASS"]
