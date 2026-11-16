"""DFM recommendations engine.

Implements the checklist described in the specification (section 4). The
functions operate on a *passport* dictionary (the JSON contract defined in
`schema_passport.py`). They return a list of human‑readable warning strings
and, where appropriate, an estimate of the time saved (minutes).
"""

from typing import Dict, List, Tuple

# Helper constants for quick lookup
RA_STANDARD = [100, 50, 25, 12.5, 6.3, 3.2, 2.5, 1.6, 0.8, 0.4, 0.2, 0.1]
IT_MIN = 6
IT_MAX = 14

def _surface_key(surface: Dict) -> str:
    """Return a concise identifier for a surface, e.g. ``S1@12``.
    """
    return f"{surface.get('code', '?')}@{surface.get('z_coord_mm', 0)}"

def check_single_grinding_shaft(passport: Dict) -> List[str]:
    """Rule 1: одиночная шлифуемая шейка.

    If exactly one surface has `Ra <= 0.8` *or* `IT == 6`, emit a warning.
    The estimated extra time is taken from the spec: +5.9 min total, of which
    3.4 min is `T_pz`.
    """
    candidates = [s for s in passport.get('surfaces', [])
                  if s.get('Ra_um', 999) <= 0.8 or s.get('IT', 99) == 6]
    if len(candidates) == 1:
        surf = _surface_key(candidates[0])
        return [
            f"Поверхность {surf} в одиночку вызывает круглошлифовальную операцию (+5.9 мин на деталь при q=5, из которых 3.4 мин — T_pz). "
            "Ослабьте до Ra 1.6 или сгруппируйте шлифование."
        ]
    return []

def check_v4_antipattern(passport: Dict) -> List[str]:
    """Rule 2: анти‑паттерн V4 (ковровые допуски).
    """
    warnings = []
    for s in passport.get('surfaces', []):
        if s.get('purpose') == 'свободная' and (
            s.get('Ra_um', 0) <= 1.6 or s.get('IT', 99) <= 9
        ):
            # Estimate time saving: assume the rough operation takes 5 min per
            # surface and the refined one 2 min.
            saved = 5 - 2
            surf = _surface_key(s)
            warnings.append(
                f"Антипаттерн V4: поверхность {surf} имеет Ra ≤ 1.6 или IT ≤ 9. "
                f"Рекомендация – вернуть Ra 6.3 / IT12, экономия ≈ {saved} мин."
            )
    return warnings

def check_ra_series(passport: Dict) -> List[str]:
    """Rule 3: проверка ряда ГОСТ 2789‑73.
    """
    warnings = []
    for s in passport.get('surfaces', []):
        ra = s.get('Ra_um')
        if ra is not None and ra not in RA_STANDARD:
            surf = _surface_key(s)
            warnings.append(
                f"Ошибка: Ra={ra} у поверхности {surf} не входит в стандартный ряд ГОСТ 2789‑73."
            )
    return warnings

def check_tool_unification(passport: Dict) -> List[str]:
    """Rule 4: унификация инструментов.
    """
    # For simplicity we only look at distinct radii of grooves.
    radii = set()
    for s in passport.get('surfaces', []):
        extra = s.get('extra_params', {})
        r = extra.get('radius_R_mm')
        if r is not None:
            radii.add(r)
    if len(radii) > 1:
        return [
            f"Обнаружено {len(radii)} разных радиусов галтелей {sorted(radii)}. "
            "Рекомендация – унифицировать их под один резец (≥ 1.6 mm)."
        ]
    return []

def check_heat_treatment_and_grinding(passport: Dict) -> List[str]:
    """Rule 5: согласованность ТТ и шлифования.
    """
    warnings = []
    has_tt = passport.get('has_heat_treatment', False)
    # Check for grinding surface (Ra <= 0.8 or IT == 6)
    has_grind = any(
        s.get('Ra_um', 999) <= 0.8 or s.get('IT', 99) == 6
        for s in passport.get('surfaces', [])
    )
    if has_tt and not has_grind:
        warnings.append(
            "Ошибка: указана термообработка (has_heat_treatment=True) без шлифования посадочных шеек."
        )
    if has_grind and not has_tt and passport.get('material_key') == '45':
        warnings.append(
            "Ошибка: шлифование Ra 0.4 на сырой стали 45 без термообработки."
        )
    return warnings

def check_low_kim(passport: Dict) -> List[str]:
    """Rule 6: низкий КИМ.
    """
    kim = passport.get('kim_ratio')
    if kim is not None and kim < 0.5:
        return [
            f"Низкий КИМ ({kim:.2f} < 0.50). Предложено заменить круглый прокат на ступенчатую поковку."
        ]
    return []

def run_all(passport: Dict) -> Tuple[List[str], float]:
    """Execute all DFM checks and return warnings + total estimated time saved.
    """
    warnings = []
    saved_total = 0.0
    for fn in [
        check_single_grinding_shaft,
        check_v4_antipattern,
        check_ra_series,
        check_tool_unification,
        check_heat_treatment_and_grinding,
        check_low_kim,
    ]:
        res = fn(passport)
        warnings.extend(res)
        # Simple heuristic: if a warning mentions "экономия" or "saved" extract number.
        for w in res:
            import re
            m = re.search(r"([0-9]+(?:\.[0-9]*)?)\s*мин", w)
            if m:
                saved_total += float(m.group(1))
    return warnings, saved_total

__all__ = [
    "run_all",
    "check_single_grinding_shaft",
    "check_v4_antipattern",
    "check_ra_series",
    "check_tool_unification",
    "check_heat_treatment_and_grinding",
    "check_low_kim",
]
