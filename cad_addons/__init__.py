"""CAD-адаптеры Siemens NX и КОМПАС-3D."""

from .base_extractor import BaseCADExtractor, PMIFaceBinding, RawCADModelSnapshot, detect_is_rotational_part

__all__ = ["BaseCADExtractor", "PMIFaceBinding", "RawCADModelSnapshot", "detect_is_rotational_part"]
