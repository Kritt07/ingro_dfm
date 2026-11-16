"""Утилиты парсинга PMI, технических требований (ТТ), Rz->Ra и допусков ЕСДП (ГОСТ 25346)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from ingro_dfm.core_schema.part_passport import GeomToleranceType
from ingro_dfm.database.loader import load_drilling_db

logger = logging.getLogger(__name__)

# Таблица перевода Rz -> Ra по ГОСТ 2789-73 (соотв. разд. 2.3 ТЗ)
_RZ_TO_RA_PAIRS: Tuple[Tuple[float, float], ...] = (
    (320.0, 80.0),
    (160.0, 40.0),
    (80.0, 20.0),
    (40.0, 10.0),
    (20.0, 5.0),
    (10.0, 2.5),
    (6.3, 1.25),
    (3.2, 0.63),
    (1.6, 0.32),
    (0.8, 0.16),
    (0.4, 0.08),
    (0.2, 0.04),
    (0.1, 0.02),
)

_RA_STANDARD_GRID: Tuple[float, ...] = (
    80.0, 50.0, 40.0, 25.0, 20.0, 12.5, 10.0, 6.3, 5.0, 3.2, 2.5, 1.6, 1.25, 0.8, 0.63, 0.4, 0.32, 0.2, 0.16, 0.1, 0.05, 0.02
)


def rz_to_ra(rz_um: float) -> float:
    """Переводит Rz (мкм) в эквивалентный Ra (мкм) по таблице ГОСТ 2789-73."""
    if rz_um <= 0:
        return 12.5
    db = load_drilling_db()
    pairs = db.get("rz_to_ra_gost") or _RZ_TO_RA_PAIRS
    best = min(pairs, key=lambda p: abs(float(p[0]) - float(rz_um)))
    if abs(float(best[0]) - float(rz_um)) / max(float(best[0]), 1e-9) <= 0.15:
        return float(best[1])
    # Для промежуточных значений — Rz / 4 и привязка к стандартному ряду
    approx_ra = float(rz_um) / 4.0
    return min(_RA_STANDARD_GRID, key=lambda r: abs(r - approx_ra))


def parse_roughness_text(text: str) -> Optional[float]:
    """Извлекает значение Ra (или Rz с переводом в Ra) из строки PMI/ТТ."""
    if not text:
        return None
    s = text.replace(",", ".")
    m_ra = re.search(r"(?:Ra|Rа)\s*=?\s*(\d+(?:\.\d+)?)", s, flags=re.IGNORECASE)
    if m_ra:
        return float(m_ra.group(1))
    m_rz = re.search(r"Rz\s*=?\s*(\d+(?:\.\d+)?)", s, flags=re.IGNORECASE)
    if m_rz:
        return rz_to_ra(float(m_rz.group(1)))
    return None


def esdp_unit_um(nominal_mm: float) -> float:
    """Единица допуска i (мкм) по ГОСТ 25346 для размеров <= 500 мм (и верхних до 3150 мм)."""
    d = max(1.0, float(nominal_mm))
    if d <= 500.0:
        return 0.45 * (d ** (1.0 / 3.0)) + 0.001 * d
    return 0.004 * d + 2.1


def it_from_tolerance_um(nominal_mm: float, tol_um: float) -> int:
    """Определяет номер квалитета IT (1..17) по размеру (мм) и полю допуска (мкм)."""
    tol = max(0.1, float(tol_um))
    i_um = esdp_unit_um(nominal_mm)
    multipliers = load_drilling_db().get("esdp_it_multipliers", {})
    ratio = tol / max(i_um, 1e-6)
    candidates = sorted((int(k), float(v)) for k, v in multipliers.items())
    for it_num, mult in candidates:
        if ratio <= mult * 1.18:
            return it_num
    if ratio < 7.0:
        return 4 if ratio >= 4.0 else 3
    return 17


def parse_tolerance_text(text: str, nominal_mm: float = 30.0) -> Tuple[Optional[int], Optional[float]]:
    """Парсит буквенный квалитет ('H7', 'g6', 'js6', '±IT14/2') или отклонения ('+0.025 / 0', '±0.05')."""
    if not text:
        return None, None
    s = text.replace(",", ".").strip()

    # 1. Явный IT (например "IT12", "±IT14/2")
    m_it = re.search(r"IT\s*(\d{1,2})", s, flags=re.IGNORECASE)
    if m_it:
        it_val = max(1, min(17, int(m_it.group(1))))
        mult = float(load_drilling_db().get("esdp_it_multipliers", {}).get(str(it_val), 400))
        return it_val, round(mult * esdp_unit_um(nominal_mm), 2)

    # 2. Символьное поле допуска (H7, h7, g6, js6, k6, H14)
    m_sym = re.search(r"\b([A-Za-z]{1,2})(\d{1,2})\b", s)
    if m_sym and m_sym.group(1).lower() not in ("ra", "rz", "hb", "hr"):
        it_val = max(1, min(17, int(m_sym.group(2))))
        mult = float(load_drilling_db().get("esdp_it_multipliers", {}).get(str(it_val), 100))
        return it_val, round(mult * esdp_unit_um(nominal_mm), 2)

    # 3. Симметричное отклонение (±0.025)
    m_sym_num = re.search(r"[±\+\-]{1,2}\s*(\d+(?:\.\d+)?)\s*(?:мм|mm)?", s)
    if "±" in s or "+/-" in s:
        m_pm = re.search(r"(?:±|\+/-)\s*(\d+(?:\.\d+)?)", s)
        if m_pm:
            tol_mm = 2.0 * float(m_pm.group(1))
            tol_um = tol_mm * 1000.0
            return it_from_tolerance_um(nominal_mm, tol_um), round(tol_um, 2)

    # 4. Пара предельных отклонений (+0.025 / 0, +0.021/-0.005)
    m_pair = re.search(r"([+-]?\d+(?:\.\d+)?)\s*/\s*([+-]?\d+(?:\.\d+)?)", s)
    if m_pair:
        upper = float(m_pair.group(1))
        lower = float(m_pair.group(2))
        tol_um = abs(upper - lower) * 1000.0
        if tol_um > 0:
            return it_from_tolerance_um(nominal_mm, tol_um), round(tol_um, 2)

    return None, None


def map_fcf_symbol_to_enum(symbol_or_text: str) -> GeomToleranceType:
    """Преобразует строковое обозначение допуска формы/расположения (FCF) в Enum."""
    s = (symbol_or_text or "").lower()
    if any(k in s for k in ("pos", "concentric", "symmetry", "позиц", "соосн", "симметр")):
        return GeomToleranceType.POSITION
    if any(k in s for k in ("perp", "parallel", "angular", "перпенд", "параллел", "наклон")):
        return GeomToleranceType.ORIENTATION
    if any(k in s for k in ("cyl", "flat", "round", "runout", "круглост", "цилиндр", "плоскост", "биени")):
        return GeomToleranceType.FORM_RUNOUT
    return GeomToleranceType.NONE


@dataclass
class ParsedTechRequirements:
    default_ra_um: float = 12.5
    default_it_grade: int = 14
    has_heat_treatment: bool = False
    hardness_hb_or_hrc: Optional[str] = None
    has_coating: bool = False
    ra_source_found: bool = False
    it_source_found: bool = False


def parse_tech_requirements(lines: Iterable[str]) -> ParsedTechRequirements:
    """Парсит неструктурированные Технические Требования (ТТ) по правилам §2.3."""
    full_text = "\n".join(line.strip() for line in lines if line and line.strip())
    res = ParsedTechRequirements()
    if not full_text:
        return res

    low = full_text.lower()

    # Неуказанная шероховатость
    for pattern in (
        r"(?:неуказан\w*\s+шероховатост\w*|остальн\w*\s+поверхност\w*).*?(R[az]\s*=?\s*\d+(?:[.,]\d+)?)",
        r"(R[az]\s*=?\s*\d+(?:[.,]\d+)?)\s*(?:\([^)]*\))?\s*(?:для\s+неуказан|прочих|остальных)?",
    ):
        m = re.search(pattern, full_text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            ra = parse_roughness_text(m.group(1))
            if ra is not None:
                res.default_ra_um = ra
                res.ra_source_found = True
                break

    # Неуказанные предельные отклонения (H14, h14, ±IT14/2, IT12)
    m_def_it = re.search(r"(H1\d|h1\d|±\s*IT\s*\d+|IT\s*\d+)", full_text, flags=re.IGNORECASE)
    if m_def_it:
        it_val, _ = parse_tolerance_text(m_def_it.group(1))
        if it_val is not None:
            res.default_it_grade = it_val
            res.it_source_found = True

    # Термообработка и твердость
    if any(k in low for k in ("закал", "цементац", "азотир", "улучшен", "термообработ", "нормализац", "отжиг")):
        res.has_heat_treatment = True

    m_hrc = re.search(r"(\d{2}(?:\s*\.\.\s*\d{2})?)\s*HRC[эe]?", full_text, flags=re.IGNORECASE)
    m_hrc_rev = re.search(r"HRC[эe]?\s*(\d{2}(?:\s*\.\.\s*\d{2})?)", full_text, flags=re.IGNORECASE)
    m_hb = re.search(r"(\d{2,3}(?:\s*\.\.\s*\d{2,3})?)\s*HB", full_text, flags=re.IGNORECASE)
    m_hb_rev = re.search(r"HB\s*(\d{2,3}(?:\s*\.\.\s*\d{2,3})?)", full_text, flags=re.IGNORECASE)

    if m_hrc or m_hrc_rev:
        raw_h = (m_hrc or m_hrc_rev).group(1).replace(" ", "")
        res.hardness_hb_or_hrc = f"{raw_h} HRC"
        res.has_heat_treatment = True
    elif m_hb or m_hb_rev:
        raw_hb = (m_hb or m_hb_rev).group(1).replace(" ", "")
        res.hardness_hb_or_hrc = f"{raw_hb} HB"
        first_num = int(re.findall(r"\d+", raw_hb)[0])
        if first_num >= 240:
            res.has_heat_treatment = True

    # Покрытия
    if any(k in low for k in ("хим.окс", "хим.пас", "анод.окс", "ц9.хр", "покрыт", "цинк", "хром", "никел")):
        res.has_coating = True

    return res


def extract_hb_numeric(hardness_str: Optional[str]) -> Optional[float]:
    """Приближенно переводит строку HRC/HB в эквивалент HB (для табличных коэффициентов)."""
    if not hardness_str:
        return None
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", hardness_str.replace(",", "."))]
    if not nums:
        return None
    val = sum(nums) / len(nums)
    if "hrc" in hardness_str.lower() or val < 85:
        # Аппроксимация HRC -> HB: 20 HRC ~ 226 HB, 45 HRC ~ 421 HB, 60 HRC ~ 653 HB
        return round(val * 10.0, 1)
    return val
