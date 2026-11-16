"""Адаптер Siemens NX Open: извлечение PMI (шероховатость, размеры с допусками, FCF) и ТТ."""

from __future__ import annotations

import logging
from typing import Any, List, Tuple

from ingro_dfm.cad_addons.base_extractor import PMIFaceBinding

logger = logging.getLogger(__name__)


class NXPMIExtractor:
    """Читает PMI-объекты и технические требования из части Siemens NX."""

    def extract(self, part: Any) -> Tuple[List[PMIFaceBinding], List[str]]:
        bindings: List[PMIFaceBinding] = []
        notes: List[str] = []

        pmi_mgr = getattr(part, "PmiManager", None)
        if pmi_mgr is None:
            return bindings, notes

        # 1. Surface Finish PMI
        try:
            for sf in getattr(part.Annotations, "SurfaceFinishes", []):
                face_ids = self._associated_face_tags(sf)
                ra_text = " ".join(
                    str(getattr(sf, attr, "") or "")
                    for attr in ("SingleRoughness", "Roughness", "UpperTolerance", "LowerTolerance")
                ).strip()
                if face_ids and ra_text:
                    bindings.append(PMIFaceBinding(face_ids=face_ids, roughness_text=ra_text))
        except Exception as exc:
            logger.debug("NX SurfaceFinishes пропущены: %s", exc)

        # 2. PMI Dimensions (линейные/радиальные размеры и допуски)
        try:
            for dim in getattr(part.Annotations, "Dimensions", []):
                face_ids = self._associated_face_tags(dim)
                nominal = None
                tol_text = ""
                try:
                    nominal = float(dim.ComputedSize)
                except Exception:
                    pass
                try:
                    upper = float(dim.UpperMetricToleranceValue)
                    lower = float(dim.LowerMetricToleranceValue)
                    if abs(upper - lower) > 1e-6:
                        tol_text = f"{upper:+.4f}/{lower:+.4f}"
                except Exception:
                    pass
                if not tol_text:
                    try:
                        tol_text = str(dim.GetAppendedText().GetAboveText() or "")
                    except Exception:
                        pass
                if face_ids and tol_text:
                    bindings.append(PMIFaceBinding(face_ids=face_ids, tolerance_text=tol_text, nominal_mm=nominal))
        except Exception as exc:
            logger.debug("NX Dimensions пропущены: %s", exc)

        # 3. Feature Control Frames (FCF)
        try:
            for fcf in getattr(part.Annotations, "Fcfs", []):
                face_ids = self._associated_face_tags(fcf)
                sym = str(getattr(fcf, "Characteristic", ""))
                val = None
                try:
                    val = float(fcf.ToleranceValue)
                except Exception:
                    pass
                if face_ids and sym:
                    bindings.append(PMIFaceBinding(face_ids=face_ids, fcf_symbol=sym, fcf_value_mm=val))
        except Exception as exc:
            logger.debug("NX FCF пропущены: %s", exc)

        # 4. Notes / Технические требования
        try:
            for note in getattr(part.Annotations, "Notes", []):
                lines = list(note.GetText())
                notes.extend(str(line) for line in lines if str(line).strip())
        except Exception as exc:
            logger.debug("NX Notes пропущены: %s", exc)

        return bindings, notes

    @staticmethod
    def _associated_face_tags(pmi_obj: Any) -> List[int]:
        tags: List[int] = []
        try:
            n = int(pmi_obj.NumberOfAssociativities)
            for idx in range(1, n + 1):
                assoc = pmi_obj.GetAssociativity(idx)
                obj = getattr(assoc, "FirstObject", None)
                if obj is not None and hasattr(obj, "Tag"):
                    tags.append(int(obj.Tag))
        except Exception:
            try:
                for obj in pmi_obj.GetAssociatedObjects():
                    if hasattr(obj, "Tag"):
                        tags.append(int(obj.Tag))
            except Exception:
                pass
        return tags


__all__ = ["NXPMIExtractor"]
