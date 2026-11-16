"""Адаптер КОМПАС-3D API 7: извлечение 3D PMI (шероховатости, размеры, допуски) и ТТ."""

from __future__ import annotations

import logging
from typing import Any, List, Tuple

from ingro_dfm.cad_addons.base_extractor import PMIFaceBinding

logger = logging.getLogger(__name__)


class KompasPMIExtractor:
    """Читает 3D-обозначения ISymbols3DContainer (IRough3D, IDimension3D, ITolerance3D) и ITechnicalDemand."""

    def extract(self, doc3d: Any) -> Tuple[List[PMIFaceBinding], List[str]]:
        bindings: List[PMIFaceBinding] = []
        notes: List[str] = []

        top_part = getattr(doc3d, "TopPart", None)
        if top_part is None:
            return bindings, notes

        # 1. Шероховатости IRough3D
        try:
            sym_cont = top_part.Symbols3DContainer
            for rough in getattr(sym_cont, "Roughs3D", []):
                face_ids = self._refs_from_base_obj(rough)
                txt = str(getattr(getattr(rough, "RoughParam", None), "Text", "") or "")
                if face_ids and txt:
                    bindings.append(PMIFaceBinding(face_ids=face_ids, roughness_text=txt))
        except Exception as exc:
            logger.debug("КОМПАС Roughs3D пропущены: %s", exc)

        # 2. 3D-размеры IDimension3D
        try:
            sym_cont = top_part.Symbols3DContainer
            for dim in getattr(sym_cont, "Dimensions3D", []):
                face_ids = self._refs_from_base_obj(dim)
                nominal = float(getattr(dim, "Value", 30.0) or 30.0)
                tol_txt = str(getattr(dim, "ToleranceText", "") or "")
                if not tol_txt:
                    hp = getattr(dim, "HighDeviation", None)
                    lp = getattr(dim, "LowDeviation", None)
                    if hp is not None and lp is not None:
                        tol_txt = f"{float(hp):+.4f}/{float(lp):+.4f}"
                if face_ids and tol_txt:
                    bindings.append(PMIFaceBinding(face_ids=face_ids, tolerance_text=tol_txt, nominal_mm=nominal))
        except Exception as exc:
            logger.debug("КОМПАС Dimensions3D пропущены: %s", exc)

        # 3. Допуски формы и расположения ITolerance3D
        try:
            sym_cont = top_part.Symbols3DContainer
            for tol3d in getattr(sym_cont, "Tolerances3D", []):
                face_ids = self._refs_from_base_obj(tol3d)
                sym = str(getattr(tol3d, "Type", ""))
                val = getattr(tol3d, "ToleranceValue", None)
                if face_ids and sym:
                    bindings.append(
                        PMIFaceBinding(
                            face_ids=face_ids,
                            fcf_symbol=sym,
                            fcf_value_mm=float(val) if val is not None else None,
                        )
                    )
        except Exception as exc:
            logger.debug("КОМПАС Tolerances3D пропущены: %s", exc)

        # 4. Технические требования (ITechnicalDemand)
        try:
            td = doc3d.TechnicalDemand if hasattr(doc3d, "TechnicalDemand") else top_part.TechnicalDemand
            raw_str = str(getattr(getattr(td, "Text", None), "Str", "") or "")
            for line in raw_str.splitlines():
                if line.strip():
                    notes.append(line.strip())
        except Exception as exc:
            logger.debug("КОМПАС TechnicalDemand пропущены: %s", exc)

        return bindings, notes

    @staticmethod
    def _refs_from_base_obj(symbol_obj: Any) -> List[int]:
        refs: List[int] = []
        for attr in ("BaseObject", "BaseObjects", "SecondObject"):
            obj = getattr(symbol_obj, attr, None)
            if obj is None:
                continue
            items = obj if isinstance(obj, (list, tuple)) else [obj]
            for it in items:
                ref = getattr(it, "Reference", None)
                if ref is not None:
                    refs.append(int(ref))
        return refs


__all__ = ["KompasPMIExtractor"]
